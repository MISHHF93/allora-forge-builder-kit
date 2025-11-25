#!/usr/bin/env python3
"""Train the 7-day BTC/USD log-return model with a Python-only pipeline."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from pipeline_core import (
    add_forward_target,
    artifacts_available,
    fetch_price_history,
    generate_features,
    latest_feature_row,
    log_submission_record,
    price_coverage_ok,
    save_artifacts,
    setup_logging,
    train_model,
    DEFAULT_TOPIC_ID,
)

LOG_FILE = ("logs/train.log")


def maybe_skip_training(logger, df: pd.DataFrame, force: bool) -> bool:
    if force:
        return False
    if not artifacts_available():
        return False
    if not price_coverage_ok(df, min_days=int(os.getenv("FORECAST_DAYS_BACK", "90"))):
        return False
    logger.info("Cached data and artifacts are fresh; skipping retraining. Set FORCE_RETRAIN=1 to override.")
    return True


def main() -> int:
    logger = setup_logging("train", log_file=LOG_FILE)
    days_back = int(os.getenv("FORECAST_DAYS_BACK", "90"))
    horizon_hours = int(os.getenv("FORECAST_HORIZON_HOURS", "168"))
    force_refresh = os.getenv("FORCE_FETCH", "0").lower() in {"1", "true", "yes"}
    force_retrain = os.getenv("FORCE_RETRAIN", "0").lower() in {"1", "true", "yes"}

    logger.info("Starting training run: days_back=%s, horizon=%s, force_retrain=%s", days_back, horizon_hours, force_retrain)

    prices, fetch_meta = fetch_price_history(days_back, logger, force_refresh=force_refresh)
    if prices.empty or not price_coverage_ok(prices, days_back):
        logger.error("Price history unavailable or incomplete: %s", fetch_meta.reason or fetch_meta.source)
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
