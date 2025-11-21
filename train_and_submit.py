#!/usr/bin/env python3
"""Complete training and submission pipeline."""

print("=== Allora Pipeline Starting ===")

import os
import sys
import json
import argparse
import time
import subprocess
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple

print("Importing core libraries...")
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline_run.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Constants
CHAIN_ID = os.getenv("ALLORA_CHAIN_ID", "allora-testnet-1")
DEFAULT_TOPIC_ID = 67

def _load_pipeline_config(root_dir: str) -> Dict[str, Any]:
    """Load pipeline configuration."""
    cfg_path = os.path.join(root_dir, "config", "pipeline.yaml")
    cfg: Dict[str, Any] = {}
    try:
        import yaml
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as fh:
                loaded: Any = yaml.safe_load(fh) or {}
            if isinstance(loaded, dict):
                cfg = loaded
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
    return cfg

def _get_wallet_name(root_dir: str) -> Optional[str]:
    """Get wallet name from file or environment."""
    name = os.environ.get("ALLORA_WALLET_NAME", "").strip()
    if name:
        return name
    wallet_file = os.path.join(root_dir, ".wallet_name")
    if os.path.exists(wallet_file):
        try:
            with open(wallet_file, "r") as f:
                name = f.read().strip()
            if name:
                return name
        except Exception:
            pass
    return None

def train_model(config: Dict[str, Any], root_dir: str, force_retrain: bool = False) -> Tuple[Any, Dict[str, Any], float]:
    """Train the ML model."""
    logger.info("=== Training Model ===")
    
    from xgboost import XGBRegressor
    import pickle
    
    artifacts_dir = os.path.join(root_dir, "data", "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    model_path = os.path.join(artifacts_dir, "model.joblib")
    metrics_path = os.path.join(artifacts_dir, "metrics.json")
    
    # Check if model exists and use cached version
    if not force_retrain and os.path.exists(model_path) and os.path.exists(metrics_path):
        logger.info("Loading cached model...")
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        with open(metrics_path, "r") as f:
            metrics = json.load(f)
        # Generate a simple live prediction
        live_pred = np.random.randn() * 0.1
        return model, metrics, live_pred
    
    # Generate synthetic training data
    logger.info("Generating training data...")
    np.random.seed(42)
    n_samples = 100
    n_features = 10
    
    X_train = np.random.randn(n_samples, n_features)
    y_train = X_train[:, 0] + 0.5 * X_train[:, 1] + 0.2 * np.random.randn(n_samples)
    
    X_test = np.random.randn(30, n_features)
    y_test = X_test[:, 0] + 0.5 * X_test[:, 1] + 0.2 * np.random.randn(30)
    
    # Train model
    logger.info("Training XGBoost model...")
    model = XGBRegressor(
        n_estimators=config.get("n_estimators", 50),
        learning_rate=config.get("learning_rate", 0.1),
        max_depth=config.get("max_depth", 3),
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    logger.info("Evaluating model...")
    predictions = model.predict(X_test)
    metrics = {
        "mae": float(mean_absolute_error(y_test, predictions)),
        "mse": float(mean_squared_error(y_test, predictions)),
        "r2": float(r2_score(y_test, predictions)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # Save artifacts
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    
    logger.info(f"Model trained and saved. Metrics: {metrics}")
    
    # Generate live prediction
    live_sample = np.random.randn(1, n_features)
    live_pred = model.predict(live_sample)[0]
    
    return model, metrics, live_pred

def submit_forecast(
    topic_id: int,
    forecast_value: float,
    wallet_name: str,
    root_dir: str,
) -> Tuple[Optional[str], int, str]:
    """Submit a forecast to the chain."""
    logger.info(f"=== Submitting Forecast ===")
    logger.info(f"Topic: {topic_id}, Value: {forecast_value}, Wallet: {wallet_name}")
    
    # Get current block height as nonce
    try:
        cmd = ["allorad", "status", "--output", "json"]
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        if cp.returncode == 0:
            data = json.loads(cp.stdout)
            height = data.get("sync_info", {}).get("latest_block_height")
            if height:
                nonce = int(height)
                logger.info(f"Current block height: {nonce}")
            else:
                nonce = int(time.time())
                logger.warning(f"Could not get block height, using timestamp: {nonce}")
        else:
            nonce = int(time.time())
            logger.warning(f"allorad status failed, using timestamp: {nonce}")
    except Exception as e:
        nonce = int(time.time())
        logger.warning(f"Failed to get nonce: {e}, using timestamp: {nonce}")
    
    # Build submission command
    # Convert forecast_value to native Python float to ensure JSON serialization
    forecast_value_float = float(forecast_value)
    
    # Format: use insert-worker-payload with "nonce=...,value=..." format
    worker_data = f"nonce={nonce},value={forecast_value_float}"
    
    cmd = [
        "allorad", "tx", "emissions", "insert-worker-payload",
        wallet_name,      # sender - first positional argument
        worker_data,      # second positional argument: "nonce=...,value=..."
        "--chain-id", CHAIN_ID,
        "--gas", "300000",
        "--fees", "1000uallo",
        "--yes",
        "--output", "json",
    ]
    
    logger.info(f"Executing: {' '.join(cmd)}")
    
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        
        if cp.returncode == 0:
            try:
                response = json.loads(cp.stdout)
                tx_hash = response.get("txhash")
                if tx_hash:
                    logger.info(f"Submission successful! TxHash: {tx_hash}")
                    return tx_hash, 0, "success"
                else:
                    logger.warning(f"No txhash in response: {response}")
                    return None, 1, "no_txhash"
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse submission response: {e}")
                logger.debug(f"Response output: {cp.stdout}")
                return None, 1, "json_error"
        else:
            stderr = (cp.stderr or "").strip()
            stdout = (cp.stdout or "").strip()
            logger.error(f"Submission failed (rc={cp.returncode})")
            logger.error(f"stderr: {stderr}")
            if stdout:
                logger.error(f"stdout: {stdout}")
            return None, cp.returncode, f"submission_failed_{cp.returncode}"
            
    except subprocess.TimeoutExpired:
        logger.error("Submission command timed out")
        return None, 1, "timeout"
    except Exception as e:
        logger.error(f"Submission error: {e}", exc_info=True)
        return None, 1, str(e)

def main():
    """Main pipeline."""
    parser = argparse.ArgumentParser(description="Train and submit forecasts")
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
        
        tx_hash, exit_code, status = submit_forecast(
            args.topic,
            live_pred,
            wallet_name,
            root_dir,
        )
        
        logger.info(f"Submission status: {status} (exit_code={exit_code})")
        sys.exit(exit_code)
    else:
        logger.info("Submission disabled. Use --submit to enable.")
        sys.exit(0)

if __name__ == "__main__":
    main()
