import os
import joblib
from datetime import datetime, timezone
from dotenv import load_dotenv

from pipeline_core import FEATURE_COLUMNS, add_forward_target, generate_features, train_model
from pipeline_utils import ARTIFACTS_DIR, DataFetcher, setup_logging

# ✅ Load environment variables
load_dotenv()

# ✅ Training config from env
DAYS_BACK = int(os.getenv("TRAINING_DAYS_BACK", "90"))
HORIZON = int(os.getenv("HORIZON_HOURS", "168"))  # 7 days
FORCE_RETRAIN = os.getenv("FORCE_RETRAIN", "0").lower() in {"1", "true", "yes"}

LOG_PATH = ARTIFACTS_DIR / "train.log"

def main() -> int:
    logger = setup_logging("train", log_file=LOG_PATH)
    logger.info(
        "Starting training run: days_back=%s, horizon=%s, force_retrain=%s",
        DAYS_BACK,
        HORIZON,
        FORCE_RETRAIN,
    )

    fetcher = DataFetcher(logger)

    # ✅ Fetch historical prices (fallback enabled)
    prices, fetch_meta = fetcher.fetch_price_history(
        DAYS_BACK,
        force_refresh=FORCE_RETRAIN,
        allow_fallback=True,
        freshness_hours=3,
    )

    if prices.empty:
        logger.error("❌ Training aborted: No price data available (%s).", fetch_meta.source)
        return 1

    # ✅ Feature engineering
    features_df = generate_features(prices)
    if features_df.empty:
        logger.error("❌ No features generated from fetched data.")
        return 1

    # ✅ Create forward return targets
    feature_target_df = add_forward_target(features_df, horizon_hours=HORIZON)
    feature_target_df = feature_target_df.dropna(subset=FEATURE_COLUMNS + ["target"])

    if feature_target_df.empty:
        logger.error("❌ Not enough data to create targets; check coverage and horizon.")
        return 1

    # ✅ Train model
    model = train_model(feature_target_df, FEATURE_COLUMNS)

    # ✅ Bundle everything
    bundle = {
        "model": model,
        "feature_names": FEATURE_COLUMNS,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "horizon_hours": HORIZON,
        "data_source": fetch_meta.source,
        "rows_used": len(feature_target_df),
    }

    # ✅ Save bundle
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    bundle_path = ARTIFACTS_DIR / "model_bundle.joblib"
    joblib.dump(bundle, bundle_path)

    # ✅ Log sample prediction
    sample_row = feature_target_df[FEATURE_COLUMNS].iloc[-1:]
    sample_pred = float(model.predict(sample_row)[0])
    logger.info(
        "✅ Training complete using %s rows from %s. Example pred=%.6f",
        len(feature_target_df),
        fetch_meta.source,
        sample_pred,
    )
    logger.info("📦 Model bundle saved to %s", bundle_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

