#!/usr/bin/env python3
"""Generate and submit a 7-day BTC/USD log-return forecast using saved artifacts."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from pipeline_core import (
    DEFAULT_TOPIC_ID,
    artifacts_available,
    fetch_price_history,
    generate_features,
    latest_feature_row,
    load_artifacts,
    log_submission_record,
    price_coverage_ok,
    setup_logging,
    validate_prediction,
)

LOG_FILE = Path("logs/submit.log")


def main() -> int:
    logger = setup_logging("submit", log_file=LOG_FILE)
    days_back = int(os.getenv("FORECAST_DAYS_BACK", "120"))
    topic_id = int(os.getenv("TOPIC_ID", os.getenv("ALLORA_TOPIC_ID", DEFAULT_TOPIC_ID)))
    force_refresh = os.getenv("FORCE_FETCH", "0").lower() in {"1", "true", "yes"}

    logger.info("Loading artifacts for topic %s", topic_id)
    if not artifacts_available():
        logger.error("Model artifacts missing. Run train.py first.")
        return 1

    try:
        model, feature_cols = load_artifacts()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to load artifacts: %s", exc)
        return 1

    prices, fetch_meta = fetch_price_history(days_back, logger, force_refresh=force_refresh)
    if prices.empty or not price_coverage_ok(prices, min_days=days_back):
        logger.error("Price data unavailable for submission: %s", fetch_meta.reason or fetch_meta.source)
        return 1

    features = generate_features(prices.sort_values("timestamp"))
    if features.empty:
        logger.error("No features available for submission.")
        return 1

    x_live = latest_feature_row(features, feature_cols)
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

    # Submission via CLI/SDK is environment-specific; here we persist the payload
    artifact_path = Path("artifacts") / "latest_submission.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("w") as f:
        json.dump(submission_payload, f, indent=2)
    logger.info("Saved submission payload to %s", artifact_path)

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
