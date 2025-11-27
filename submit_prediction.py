#!/usr/bin/env python3
"""Generate and submit a 7-day BTC/USD log-return forecast using saved artifacts."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import joblib  # ✅ Added to load model_bundle.joblib

from pipeline_core import (
    generate_features,
    latest_feature_row,
    log_submission_record,
    validate_prediction,
)
from pipeline_utils import (
    DEFAULT_TOPIC_ID,
    MIN_COVERAGE_RATIO,
    coverage_ratio,
    fetch_price_history,
    price_coverage_ok,
    setup_logging,
)

LOG_FILE = Path("logs/submit.log")

def main() -> int:
    logger = setup_logging("submit", log_file=LOG_FILE)
    days_back = int(os.getenv("FORECAST_DAYS_BACK", "120"))
    topic_id = int(os.getenv("TOPIC_ID", os.getenv("ALLORA_TOPIC_ID", DEFAULT_TOPIC_ID)))
    force_refresh = os.getenv("FORCE_FETCH", "0").lower() in {"1", "true", "yes"}

    logger.info("Loading model bundle for topic %s", topic_id)
    try:
        model_bundle = joblib.load("model_bundle.joblib")
        model = model_bundle["model"]
        feature_names = model_bundle["feature_names"]
    except Exception as exc:
        logger.error("Failed to load model_bundle.joblib: %s", exc)
        return 1

    prices, fetch_meta = fetch_price_history(days_back, logger, force_refresh=force_refresh)
    coverage = fetch_meta.coverage or coverage_ratio(prices, days_back)
    if prices.empty or coverage < MIN_COVERAGE_RATIO:
        logger.error(
            "Price data unavailable or below coverage threshold (%.2f%%): %s",
            coverage * 100,
            fetch_meta.reason or fetch_meta.source,
        )
        return 1

    if not price_coverage_ok(prices, min_days=days_back):
        logger.warning(
            "Proceeding with partial price coverage (%.2f%%). Recent data points: %s",
            coverage * 100, len(prices)
        )

    features = generate_features(prices.sort_values("timestamp"))
    if features.empty:
        logger.error("No features available for submission.")
        return 1

    # ✅ Ensure input to model has correct feature structure
    x_live_raw = latest_feature_row(features, feature_names)
    x_live = pd.DataFrame([x_live_raw], columns=feature_names)

    prediction = float(model.predict(x_live)[0])

    if not validate_prediction(prediction):
        logger.error("Prediction failed validation (non-finite or out of bounds).")
        return 1

    worker = os.getenv("ALLORA_WALLET_ADDR", "unknown")
    submission_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic_id": topic_id,
        "prediction_log_return_7d": prediction,
    }

    logger.info("Prediction ready for submission: %.8f", prediction)

    # Save payload (for submission via CLI/SDK)
    artifact_path = Path("artifacts") / "latest_submission.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("w") as f:
        json.dump(submission_payload, f, indent=2)
    logger.info("Saved submission payload to %s", artifact_path)

    # Record submission metadata
    log_submission_record(
        timestamp=datetime.now(timezone.utc),
        topic_id=topic_id,
        prediction=prediction,
        worker=worker,
        status="prediction_ready",
        extra={"fetch_source": fetch_meta.source, "rows": fetch_meta.rows},
    )

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

