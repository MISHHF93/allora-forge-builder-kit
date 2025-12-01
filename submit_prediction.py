#!/usr/bin/env python3
"""Prepare and persist a forecast payload using validated market data."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from network_gate import query_window_status
from pipeline_core import (
    FEATURE_COLUMNS,
    generate_features,
    latest_feature_row,
    log_submission_record,
    validate_prediction,
)
from pipeline_utils import (
    ARTIFACTS_DIR,
    DEFAULT_TOPIC_ID,
    MIN_COVERAGE_RATIO,
    DataFetcher,
    coverage_ratio,
    price_coverage_ok,
    setup_logging,
)

MODEL_BUNDLE_PATH = ARTIFACTS_DIR / "model_bundle.joblib"
LOG_FILE = Path("logs/submit.log")
PAYLOAD_PATH = ARTIFACTS_DIR / "latest_submission.json"


class _ConstantModel:
    """Lightweight fallback model that returns a constant log-return prediction."""

    def __init__(self, value: float = 0.001):
        self.value = float(value)

    def predict(self, X):
        import numpy as np
        return np.full(len(X), self.value)


def load_bundle(logger):
    if not MODEL_BUNDLE_PATH.exists():
        logger.warning(
            "Model bundle missing at %s; using constant fallback prediction.",
            MODEL_BUNDLE_PATH,
        )
        return _ConstantModel(), FEATURE_COLUMNS, {"trained_at": None, "fallback": True, "horizon_hours": 168}

    bundle = joblib.load(MODEL_BUNDLE_PATH)
    model = bundle.get("model")
    feature_names = bundle.get("feature_names", FEATURE_COLUMNS)
    horizon_hours = bundle.get("horizon_hours", 168)
    return model, feature_names, bundle, horizon_hours


def get_prediction_label(horizon_hours: int) -> str:
    if horizon_hours <= 24:
        return "prediction_log_return_1d"
    elif horizon_hours <= 168:
        return "prediction_log_return_7d"
    elif horizon_hours <= 336:
        return "prediction_log_return_14d"
    else:
        return f"prediction_log_return_{horizon_hours}h"


def submit_prediction_to_chain(topic_id: int, value: float, wallet: str, logger) -> tuple[bool, str]:
    from subprocess import run, CalledProcessError

    payload = {
        "topic_id": topic_id,
        "value": value
    }
    PAYLOAD_PATH.write_text(json.dumps(payload))

    cmd = [
        "allorad", "tx", "emissions", "insert-worker-payload",
        "--payload", str(PAYLOAD_PATH),
        "--from", wallet,
        "--keyring-backend", "test",
        "--chain-id", os.getenv("CHAIN_ID", "allora-testnet-1"),
        "--node", os.getenv("NODE_RPC", "https://allora-rpc.testnet.allora.network/"),
        "--fees", os.getenv("FEES", "5000stake"),
        "--gas", os.getenv("GAS", "200000"),
        "--yes",
        "--broadcast-mode", "sync",
        "--output", "json"
    ]

    try:
        logger.info("📨 Submitting prediction: topic_id=%s value=%.6f", topic_id, value)
        result = run(cmd, capture_output=True, text=True, check=True)
        logger.debug("TX output: %s", result.stdout)
        return True, result.stdout
    except CalledProcessError as e:
        logger.error("❌ TX failed with code %s: %s", e.returncode, e.stderr.strip())
        return False, e.stderr.strip()


def main() -> int:
    logger = setup_logging("submit", log_file=LOG_FILE)
    topic_id = int(os.getenv("TOPIC_ID", os.getenv("ALLORA_TOPIC_ID", DEFAULT_TOPIC_ID)))
    worker = os.getenv("ALLORA_WALLET_ADDR", "unknown")
    days_back = int(os.getenv("FORECAST_DAYS_BACK", "120"))
    force_refresh = os.getenv("FORCE_FETCH", "0").lower() in {"1", "true", "yes"}

    logger.info("Loading model bundle for topic %s", topic_id)
    try:
        model, feature_names, bundle_meta, horizon_hours = load_bundle(logger)
    except Exception as exc:
        logger.error("Failed to load model bundle: %s", exc)
        return 1

    prediction_label = get_prediction_label(horizon_hours)
    logger.info("Using prediction horizon: %s hours -> %s", horizon_hours, prediction_label)

    window_status = query_window_status(topic_id, worker, logger)
    if not window_status.ok_to_submit():
        logger.warning(
            "Submission blocked: topic_active=%s worker_can_submit=%s cli_found=%s errors=%s",
            window_status.topic_active,
            window_status.worker_can_submit,
            window_status.cli_found,
            window_status.errors,
        )
        return 2

    fetcher = DataFetcher(logger)
    prices, fetch_meta = fetcher.fetch_price_history(
        days_back, force_refresh=force_refresh, allow_fallback=True, freshness_hours=3
    )
    coverage = fetch_meta.coverage or coverage_ratio(prices, days_back)

    if prices.empty or coverage < MIN_COVERAGE_RATIO:
        logger.error("Price data insufficient: coverage=%.2f%% source=%s", coverage * 100, fetch_meta.source)
        return 1

    if fetch_meta.fallback_used:
        logger.warning("Using synthetic/fallback data for submission: %s", fetch_meta.source)

    if not price_coverage_ok(prices, min_days=days_back, freshness_hours=3):
        logger.warning("Proceeding with partial coverage: %.2f%%", coverage * 100)

    features = generate_features(prices)
    if features.empty:
        logger.error("No features generated from price history")
        return 1

    try:
        x_live_raw = latest_feature_row(features, feature_names)
    except Exception as exc:
        logger.error("Feature mismatch detected: %s", exc)
        return 1
    x_live = pd.DataFrame([x_live_raw], columns=feature_names)

    prediction = float(model.predict(x_live)[0])

    if not validate_prediction(prediction):
        logger.error("Prediction failed validation (non-finite, out of bounds, or degenerate)")
        return 1

    submission_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic_id": topic_id,
        prediction_label: prediction,
        "horizon_hours": horizon_hours,
        "data_source": fetch_meta.source,
        "uses_synthetic_data": fetch_meta.fallback_used,
    }

    PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PAYLOAD_PATH.open("w") as f:
        json.dump(submission_payload, f, indent=2)
    logger.info("Saved submission payload to %s", PAYLOAD_PATH)

    submission_result, tx_hash = submit_prediction_to_chain(
        topic_id=topic_id, value=prediction, wallet=worker, logger=logger
    )

    log_submission_record(
        timestamp=datetime.now(timezone.utc),
        topic_id=topic_id,
        prediction=prediction,
        worker=worker,
        status="submitted" if submission_result else "submit_failed",
        extra={
            "fetch_source": fetch_meta.source,
            "coverage": coverage,
            "bundle_trained_at": bundle_meta.get("trained_at"),
            "window_errors": window_status.errors,
            "tx_hash": tx_hash,
            "horizon_hours": horizon_hours,
            "uses_synthetic_data": fetch_meta.fallback_used,
        },
    )

    return 0 if submission_result else 1


if __name__ == "__main__":
    sys.exit(main())

