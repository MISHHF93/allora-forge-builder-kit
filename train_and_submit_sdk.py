#!/usr/bin/env python3
"""
Train and submit ML predictions to Allora Network using Allora SDK
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DEFAULT_TOPIC_ID = 67
DEFAULT_CHAIN_ID = "allora-testnet-1"

print("=== Allora Pipeline Starting (SDK Version) ===")
print("Importing core libraries...")

def _load_pipeline_config(root_dir: str) -> Dict[str, Any]:
    """Load pipeline config from YAML or return defaults."""
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
    model_config: Dict[str, Any],
    root_dir: str,
    force_retrain: bool = False,
) -> Tuple[xgb.XGBRegressor, Dict[str, float], float]:
    """Train XGBoost model and return model, metrics, and live prediction."""
    logger.info("=== Training Model ===")
    
    artifact_dir = os.path.join(root_dir, "data", "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)
    
    model_path = os.path.join(artifact_dir, "model.joblib")
    
    # Check if we can use cached model
    if os.path.exists(model_path) and not force_retrain:
        import joblib
        logger.info("Loading cached model...")
        model = joblib.load(model_path)
        metrics_path = os.path.join(artifact_dir, "metrics.json")
        if os.path.exists(metrics_path):
            with open(metrics_path) as f:
                metrics = json.load(f)
        else:
            metrics = {}
        # Generate live prediction with cached model
        live_data = np.random.randn(1, 10)
        live_pred = float(model.predict(live_data)[0])
        logger.info(f"Live prediction: {live_pred}")
        return model, metrics, live_pred
    
    # Generate synthetic training data
    logger.info("Generating training data...")
    np.random.seed(42)
    n_samples = 1000
    n_features = 10
    
    X = np.random.randn(n_samples, n_features)
    # Create a realistic target: some features have predictive power
    y = 2.5 * X[:, 0] - 1.8 * X[:, 1] + 0.5 * X[:, 2] + np.random.randn(n_samples) * 0.3
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    
    # Standardize features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train XGBoost
    logger.info("Training XGBoost model...")
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train_scaled, y_train, verbose=False)
    
    # Evaluate
    logger.info("Evaluating model...")
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    
    y_pred = model.predict(X_test_scaled)
    mae = mean_absolute_error(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    metrics = {
        "mae": mae,
        "mse": mse,
        "r2": r2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Save model and metrics
    import joblib
    joblib.dump(model, model_path)
    with open(os.path.join(artifact_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    
    logger.info(f"Model trained and saved. Metrics: {metrics}")
    
    # Generate live prediction
    live_data = np.random.randn(1, n_features)
    live_data_scaled = scaler.transform(live_data)
    live_pred = float(model.predict(live_data_scaled)[0])
    
    return model, metrics, live_pred

def submit_forecast_sdk(
    topic_id: int,
    forecast_value: float,
    wallet_name: str,
    root_dir: str,
) -> Tuple[Optional[str], int, str]:
    """Submit forecast using Allora SDK."""
    logger.info("=== Submitting Forecast (SDK) ===")
    logger.info(f"Topic: {topic_id}, Value: {forecast_value}, Wallet: {wallet_name}")
    
    try:
        from allora_sdk.rpc_client import AlloraRPCClient
        from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig
        from allora_sdk.worker import AlloraWorker
    except ImportError as e:
        logger.error(f"Allora SDK not installed: {e}")
        logger.error("Install with: pip install allora-sdk")
        return None, 1, "sdk_not_installed"
    
    import asyncio
    
    async def submit():
        try:
            # Configure wallet from environment or use default
            try:
                wallet_cfg = AlloraWalletConfig.from_env()
                logger.info(f"Wallet loaded from environment")
            except ValueError as e:
                logger.warning(f"Could not load wallet from environment: {e}")
                logger.warning("Attempting submission anyway...")
                wallet_cfg = None
            
            # Configure network
            network_cfg = AlloraNetworkConfig(
                chain_id=DEFAULT_CHAIN_ID,
                url="grpc+https://allora-rpc.testnet.allora.network/",
                websocket_url="wss://allora-rpc.testnet.allora.network/websocket",
                fee_denom="uallo",
                fee_minimum_gas_price=10.0,
            )
            
            if wallet_cfg is None:
                logger.warning("Skipping submission - no wallet configured")
                return None, 1, "wallet_config_error"
            
            # Create worker
            logger.info("Creating Allora worker...")
            worker = AlloraWorker(
                run=lambda _: float(forecast_value),
                wallet=wallet_cfg,
                network=network_cfg,
                topic_id=topic_id,
                polling_interval=10,
            )
            
            # Run worker and collect results
            logger.info("Running worker to submit inference...")
            async for outcome in worker.run(timeout=30):
                if isinstance(outcome, Exception):
                    logger.error(f"Worker error: {outcome}")
                    worker.stop()
                    return None, 1, "worker_error"
                
                # Extract transaction hash
                tx = outcome.tx_result
                tx_hash = (
                    getattr(tx, 'txhash', None) 
                    or getattr(tx, 'hash', None) 
                    or getattr(tx, 'transaction_hash', None)
                )
                nonce = getattr(outcome, 'nonce', None)
                
                logger.info(f"✅ Submission successful!")
                logger.info(f"   TxHash: {tx_hash}")
                logger.info(f"   Nonce: {nonce}")
                logger.info(f"   Prediction: {forecast_value}")
                
                worker.stop()
                return tx_hash, 0, "success"
            
            worker.stop()
            logger.warning("Worker completed without submitting")
            return None, 1, "no_result"
            
        except Exception as e:
            logger.error(f"SDK submission error: {e}", exc_info=True)
            return None, 1, str(type(e).__name__)
    
    try:
        # Run the async submission
        result = asyncio.run(submit())
        return result if result else (None, 1, "async_error")
    except Exception as e:
        logger.error(f"Failed to run async submission: {e}", exc_info=True)
        return None, 1, "async_exec_error"

def main():
    """Main pipeline."""
    parser = argparse.ArgumentParser(description="Train and submit forecasts using SDK")
    parser.add_argument("--submit", action="store_true", help="Submit to chain")
    parser.add_argument("--topic", type=int, default=DEFAULT_TOPIC_ID, help="Topic ID")
    parser.add_argument("--retrain", action="store_true", help="Force retraining")
    
    args = parser.parse_args()
    
    root_dir = os.path.dirname(os.path.abspath(__file__))
    logger.info(f"Root dir: {root_dir}")
    
    # Load config
    config = _load_pipeline_config(root_dir)
    logger.info(f"Config loaded: {list(config.keys())}")
    
    # Train model
    try:
        model, metrics, live_pred = train_model(config.get("model", {}), root_dir, args.retrain)
        logger.info(f"Live prediction: {live_pred}")
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        sys.exit(1)
    
    # Submit if requested
    if args.submit:
        wallet_name = _get_wallet_name(root_dir)
        if not wallet_name:
            logger.error("Wallet name not found. Set ALLORA_WALLET_NAME or create .wallet_name")
            sys.exit(1)
        
        tx_hash, exit_code, status = submit_forecast_sdk(
            args.topic,
            live_pred,
            wallet_name,
            root_dir,
        )
        logger.info(f"Submission status: {status} (exit_code={exit_code})")
        sys.exit(exit_code)

if __name__ == "__main__":
    main()
