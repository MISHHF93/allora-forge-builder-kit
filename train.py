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
HORIZON = int(os.getenv("HORIZON_HOURS", "168"))  # Default 7 days
FORCE_RETRAIN = os.getenv("FORCE_RETRAIN", "0").lower() in {"1", "true", "yes"}

# ✅ Target end date from environment (optional)
TARGET_END_DATE = os.getenv("TARGET_END_DATE")  # Format: "2025-12-15 13:00"

LOG_PATH = ARTIFACTS_DIR / "train.log"

def calculate_dynamic_horizon(target_end_date_str=None):
    """Calculate horizon needed to reach target end date"""
    if not target_end_date_str:
        return HORIZON  # Use default from env
    
    try:
        # Parse target end date
        target_end = datetime.strptime(target_end_date_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        current_time = datetime.now(timezone.utc)
        
        # Calculate hours remaining
        hours_remaining = (target_end - current_time).total_seconds() / 3600
        
        # Add buffer and round up
        horizon_needed = max(int(hours_remaining) + 12, 24)  # Minimum 1 day horizon
        
        print(f"🎯 Dynamic horizon calculation:")
        print(f"   Current time: {current_time}")
        print(f"   Target end: {target_end}")
        print(f"   Hours needed: {hours_remaining:.1f}")
        print(f"   Horizon set to: {horizon_needed} hours")
        
        return horizon_needed
        
    except Exception as e:
        print(f"⚠️  Failed to calculate dynamic horizon: {e}, using default: {HORIZON}")
        return HORIZON

def main() -> int:
    logger = setup_logging("train", log_file=LOG_PATH)
    
    # ✅ Calculate dynamic horizon if target date provided
    effective_horizon = calculate_dynamic_horizon(TARGET_END_DATE)
    
    logger.info(
        "Starting training run: days_back=%s, horizon=%s, force_retrain=%s",
        DAYS_BACK,
        effective_horizon,
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
    feature_target_df = add_forward_target(features_df, horizon_hours=effective_horizon)
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
        "horizon_hours": effective_horizon,
        "data_source": fetch_meta.source,
        "rows_used": len(feature_target_df),
        "target_end_date": TARGET_END_DATE,
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
