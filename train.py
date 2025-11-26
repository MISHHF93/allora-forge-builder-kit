#!/usr/bin/env python3
"""Train the 7-day BTC/USD log-return model with a Python-only pipeline."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline_core import (
    add_forward_target,
    artifacts_available,
    artifacts_fresh_enough,
    generate_features,
    latest_feature_row,
    log_submission_record,
    save_artifacts,
    train_model,
)
from pipeline_utils import (
    CACHE_PATH,
    DEFAULT_TOPIC_ID,
    MIN_COVERAGE_RATIO,
    coverage_ratio,
    fetch_price_history,
    price_coverage_ok,
    setup_logging,
)

LOG_FILE = ("logs/train.log")


def maybe_skip_training(logger, df: pd.DataFrame, force: bool) -> bool:
    if force:
        return False
    if not artifacts_available():
        return False
    if not price_coverage_ok(df, min_days=int(os.getenv("FORECAST_DAYS_BACK", "90"))):
        return False
    model_path = Path("artifacts/model.pkl")
    features_path = Path("artifacts/features.json")
    if artifacts_fresh_enough(CACHE_PATH, [model_path, features_path]):
        logger.info(
            "Cached data and artifacts are fresh; skipping retraining. Set FORCE_RETRAIN=1 to override."
        )
        return True
    return False


def main() -> int:
    logger = setup_logging("train", log_file=LOG_FILE)
    days_back = int(os.getenv("FORECAST_DAYS_BACK", "90"))
    horizon_hours = int(os.getenv("FORECAST_HORIZON_HOURS", "168"))
    force_refresh = os.getenv("FORCE_FETCH", "0").lower() in {"1", "true", "yes"}
    force_retrain = os.getenv("FORCE_RETRAIN", "0").lower() in {"1", "true", "yes"}

    logger.info("Starting training run: days_back=%s, horizon=%s, force_retrain=%s", days_back, horizon_hours, force_retrain)

    prices, fetch_meta = fetch_price_history(days_back, logger, force_refresh=force_refresh)
    coverage = fetch_meta.coverage or coverage_ratio(prices, days_back)
    if prices.empty or coverage < MIN_COVERAGE_RATIO:
        logger.error(
            "Price history unavailable or below coverage threshold (%.2f%%): %s",
            coverage * 100,
            fetch_meta.reason or fetch_meta.source,
        )
        return 1

    if not price_coverage_ok(prices, days_back):
        logger.warning(
            "Proceeding with partial price coverage (%.2f%%). Recent data points: %s", coverage * 100, len(prices)
        )

    latest_ts = pd.to_datetime(prices["timestamp"]).max()
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.tz_localize(timezone.utc)
    if datetime.now(timezone.utc) - latest_ts > pd.Timedelta(hours=6):
        logger.error("Latest price data is stale; aborting training run.")
        return 1

    if maybe_skip_training(logger, prices, force_retrain):
        return 0

    trimmed = prices.sort_values("timestamp").tail(days_back * 24)
    features = generate_features(trimmed)
    labeled = add_forward_target(features, horizon_hours)

    feature_cols = [c for c in labeled.columns if c not in {"timestamp", "close", "target"}]
    if labeled.empty or len(feature_cols) == 0:
        logger.error("No training samples available after feature engineering.")
        return 1

    model = train_model(labeled, feature_cols)
    save_artifacts(model, feature_cols)

    latest = latest_feature_row(features, feature_cols)
    preview = float(model.predict(latest)[0])
    logger.info("Training complete. Example prediction on latest row: %.8f", preview)

    # Record metadata for traceability
    log_submission_record(
        timestamp=datetime.now(timezone.utc),
        topic_id=DEFAULT_TOPIC_ID,
        prediction=preview,
        worker=os.getenv("ALLORA_WALLET_ADDR", "unknown"),
        status=f"train_artifacts_saved:{len(labeled)}rows",
        extra={"fetch_source": fetch_meta.source, "rows": fetch_meta.rows},
    )

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
