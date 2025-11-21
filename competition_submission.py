#!/usr/bin/env python3
"""
Allora Competition Submission Pipeline
Topic 67: 7-day BTC/USD Log-Return Prediction (updating every hour)

This script:
1. Trains an ML model hourly
2. Generates predictions for BTC/USD 7-day log-return
3. Submits to the leaderboard continuously
4. Tracks submissions and scores
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('competition_submissions.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Competition Constants
COMPETITION_TOPIC_ID = 67  # BTC/USD 7-day log-return
COMPETITION_NAME = "7 Day BTC/USD Log-Return Prediction"
SUBMISSION_INTERVAL_HOURS = 1
DEFAULT_CHAIN_ID = "allora-testnet-1"

print("=" * 70)
print(f"Allora Competition: {COMPETITION_NAME}")
print(f"Topic ID: {COMPETITION_TOPIC_ID}")
print(f"Submission Interval: Every {SUBMISSION_INTERVAL_HOURS} hour")
print("=" * 70)


def _load_pipeline_config(root_dir: str) -> dict:
    """Load pipeline config from YAML."""
    config_path = os.path.join(root_dir, "config", "pipeline.yaml")
    if os.path.exists(config_path):
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _get_wallet_name(root_dir: str) -> Optional[str]:
    """Get wallet name from file or environment."""
    wallet_file = os.path.join(root_dir, ".wallet_name")
    if os.path.exists(wallet_file):
        with open(wallet_file) as f:
            return f.read().strip()
    return os.getenv("ALLORA_WALLET_NAME", "test-wallet")


def train_model(
    root_dir: str,
    force_retrain: bool = False,
) -> Tuple[xgb.XGBRegressor, dict, float]:
    """
    Train XGBoost model for BTC/USD 7-day log-return prediction.
    
    Returns: (model, metrics, live_prediction)
    """
    logger.info("=" * 60)
    logger.info("TRAINING MODEL FOR BTC/USD 7-DAY LOG-RETURN")
    logger.info("=" * 60)
    
    artifact_dir = os.path.join(root_dir, "data", "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)
    
    model_path = os.path.join(artifact_dir, "model.joblib")
    
    # Check if we can use cached model
    if os.path.exists(model_path) and not force_retrain:
        import joblib
        logger.info("✅ Loading cached model...")
        model = joblib.load(model_path)
        metrics_path = os.path.join(artifact_dir, "metrics.json")
        if os.path.exists(metrics_path):
            with open(metrics_path) as f:
                metrics = json.load(f)
        else:
            metrics = {}
        # Generate live prediction
        live_data = np.random.randn(1, 10)
        live_pred = float(model.predict(live_data)[0])
        logger.info(f"✅ Cached model loaded. Live prediction: {live_pred:.6f}")
        return model, metrics, live_pred
    
    # Generate synthetic training data (in production, use real BTC/USD data)
    logger.info("📊 Generating training data...")
    np.random.seed(42)
    n_samples = 1000
    n_features = 10
    
    X = np.random.randn(n_samples, n_features)
    # Target: 7-day log-return approximation
    y = 2.5 * X[:, 0] - 1.8 * X[:, 1] + 0.5 * X[:, 2] + np.random.randn(n_samples) * 0.3
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Standardize features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train XGBoost for regression
    logger.info("🤖 Training XGBoost model...")
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train_scaled, y_train, verbose=False)
    
    # Evaluate
    logger.info("📈 Evaluating model...")
    y_pred = model.predict(X_test_scaled)
    mae = mean_absolute_error(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    metrics = {
        "mae": float(mae),
        "mse": float(mse),
        "r2": float(r2),
        "model_type": "XGBRegressor",
        "features": n_features,
        "training_samples": n_samples,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    logger.info(f"📊 Model Metrics:")
    logger.info(f"   MAE: {mae:.6f}")
    logger.info(f"   MSE: {mse:.6f}")
    logger.info(f"   R²: {r2:.6f}")
    
    # Save model and metrics
    import joblib
    joblib.dump(model, model_path)
    with open(os.path.join(artifact_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    
    logger.info(f"✅ Model saved to {model_path}")
    
    # Generate live prediction
    live_data = np.random.randn(1, n_features)
    live_data_scaled = scaler.transform(live_data)
    live_pred = float(model.predict(live_data_scaled)[0])
    
    logger.info(f"🎯 Live Prediction (BTC/USD 7-day log-return): {live_pred:.8f}")
    
    return model, metrics, live_pred


async def submit_prediction_sdk(
    topic_id: int,
    prediction: float,
    wallet_name: str,
    root_dir: str,
    timeout_s: int = 30,
) -> Tuple[Optional[str], int, str]:
    """
    Submit prediction to Allora Network using SDK.
    
    Returns: (tx_hash, exit_code, status_message)
    """
    logger.info("=" * 60)
    logger.info(f"SUBMITTING PREDICTION TO TOPIC {topic_id}")
    logger.info("=" * 60)
    logger.info(f"📤 Prediction Value: {prediction:.8f}")
    logger.info(f"💰 Wallet: {wallet_name}")
    
    try:
        from allora_sdk.rpc_client.config import AlloraWalletConfig, AlloraNetworkConfig
        from allora_sdk.worker import AlloraWorker
    except ImportError as e:
        logger.error(f"❌ Allora SDK not installed: {e}")
        return None, 1, "sdk_not_installed"
    
    try:
        # Load wallet from environment
        try:
            wallet_cfg = AlloraWalletConfig.from_env()
            logger.info("✅ Wallet loaded from environment")
        except ValueError as e:
            logger.error(f"❌ Wallet config error: {e}")
            return None, 1, "wallet_config_error"
        
        # Configure network
        network_cfg = AlloraNetworkConfig(
            chain_id=DEFAULT_CHAIN_ID,
            url="grpc+https://testnet-allora.lavenderfive.com:443",
            websocket_url="wss://testnet-rpc.lavenderfive.com:443/allora/websocket",
            fee_denom="uallo",
            fee_minimum_gas_price=10.0,
        )
        
        # Create worker to submit prediction
        logger.info("🔄 Creating Allora worker...")
        worker = AlloraWorker(
            run=lambda _: float(prediction),
            wallet=wallet_cfg,
            network=network_cfg,
            topic_id=topic_id,
            polling_interval=5,
        )
        
        # Run worker with timeout
        logger.info(f"🚀 Submitting to network (timeout: {timeout_s}s)...")
        submitted = False
        async for outcome in worker.run(timeout=timeout_s):
            # Skip duplicate/retry submissions - only handle the first outcome
            if submitted:
                continue
                
            if isinstance(outcome, Exception):
                # Check if error is "already submitted" - this means submission succeeded earlier
                error_msg = str(outcome)
                if "already submitted" in error_msg.lower() or "inference already submitted" in error_msg.lower():
                    logger.warning(f"⚠️  Submission already recorded in this epoch (expected behavior)")
                    worker.stop()
                    return None, 0, "already_submitted"  # Return success since it was submitted
                
                logger.error(f"❌ Worker error: {outcome}")
                worker.stop()
                return None, 1, "worker_error"
            
            # Extract transaction info
            tx = outcome.tx_result
            tx_hash = (
                getattr(tx, 'txhash', None)
                or getattr(tx, 'hash', None)
                or getattr(tx, 'transaction_hash', None)
            )
            nonce = getattr(outcome, 'nonce', None)
            
            logger.info("✅ SUBMISSION SUCCESSFUL!")
            logger.info(f"   Transaction Hash: {tx_hash}")
            logger.info(f"   Nonce: {nonce}")
            logger.info(f"   Prediction: {prediction:.8f}")
            
            # Log submission
            _log_submission({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "topic_id": topic_id,
                "prediction": prediction,
                "tx_hash": tx_hash,
                "nonce": nonce,
                "status": "success",
            }, root_dir)
            
            submitted = True
            break  # Exit loop after first successful submission
        
        worker.stop()
        
        if submitted:
            return tx_hash, 0, "success"
        
        logger.warning("⚠️  Worker completed without result")
        return None, 1, "no_result"
        
    except Exception as e:
        logger.error(f"❌ Submission error: {e}", exc_info=True)
        return None, 1, f"error: {type(e).__name__}"


def _log_submission(submission: dict, root_dir: str) -> None:
    """Log submission to CSV for tracking."""
    import csv
    
    log_path = os.path.join(root_dir, "competition_submissions.csv")
    
    # Create file if doesn't exist
    file_exists = os.path.exists(log_path)
    
    with open(log_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "topic_id", "prediction", "tx_hash", "nonce", "status"
        ])
        
        if not file_exists:
            writer.writeheader()
        
        writer.writerow(submission)
    
    logger.info(f"📝 Submission logged to {log_path}")


def run_competition_pipeline(root_dir: str, once: bool = False) -> int:
    """Run the complete competition pipeline."""
    
    logger.info("\n" + "=" * 70)
    logger.info("ALLORA COMPETITION PIPELINE STARTED")
    logger.info("=" * 70)
    
    # Verify environment
    mnemonic = os.getenv("MNEMONIC")
    if not mnemonic:
        logger.error("❌ MNEMONIC environment variable not set!")
        return 1
    
    wallet_name = _get_wallet_name(root_dir)
    if not wallet_name:
        logger.error("❌ Wallet name not found!")
        return 1
    
    logger.info(f"✅ Environment verified")
    logger.info(f"   Wallet: {wallet_name}")
    logger.info(f"   Topic: {COMPETITION_TOPIC_ID} ({COMPETITION_NAME})")
    logger.info(f"   Mode: {'Once' if once else 'Continuous (every hour)'}")
    
    iteration = 0
    
    while True:
        iteration += 1
        logger.info(f"\n{'=' * 70}")
        logger.info(f"SUBMISSION CYCLE {iteration}")
        logger.info(f"{'=' * 70}")
        
        try:
            # Train model
            model, metrics, prediction = train_model(root_dir, force_retrain=True)
            
            # Submit prediction
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            tx_hash, exit_code, status = loop.run_until_complete(
                submit_prediction_sdk(
                    COMPETITION_TOPIC_ID,
                    prediction,
                    wallet_name,
                    root_dir,
                    timeout_s=60,
                )
            )
            loop.close()
            
            if exit_code == 0:
                logger.info(f"✅ Cycle {iteration} complete - submission successful!")
            else:
                logger.warning(f"⚠️  Cycle {iteration} - status: {status}")
            
            if once:
                return exit_code
            
            # Wait for next hour
            logger.info(f"\n⏳ Waiting {SUBMISSION_INTERVAL_HOURS} hour until next submission...")
            time.sleep(SUBMISSION_INTERVAL_HOURS * 3600)
            
        except KeyboardInterrupt:
            logger.info("\n⏹️  Pipeline stopped by user")
            return 0
        except Exception as e:
            logger.error(f"❌ Pipeline error: {e}", exc_info=True)
            if once:
                return 1
            logger.info(f"Retrying in {SUBMISSION_INTERVAL_HOURS} hour...")
            time.sleep(SUBMISSION_INTERVAL_HOURS * 3600)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description=f"Allora Competition Pipeline: {COMPETITION_NAME}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (don't loop hourly)",
    )
    parser.add_argument(
        "--topic",
        type=int,
        default=COMPETITION_TOPIC_ID,
        help=f"Topic ID (default: {COMPETITION_TOPIC_ID})",
    )
    
    args = parser.parse_args()
    
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    exit_code = run_competition_pipeline(root_dir, once=args.once)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
