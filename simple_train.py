#!/usr/bin/env python3
"""Simple training script with debug output."""

print("=== Simple Train Script Starting ===")

import os
import sys
import json
import argparse
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
import warnings

print("Importing pandas...")
import pandas as pd
import numpy as np

print("Importing sklearn...")
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

print("Setting up config...")
# Config
CHAIN_ID = os.getenv("ALLORA_CHAIN_ID", "allora-testnet-1")
DEFAULT_TOPIC_ID = 67

print("Importing custom modules...")

# Minimal config loader
def _load_pipeline_config(root_dir: str) -> Dict[str, Any]:
    """Load pipeline configuration once for reuse."""
    cfg_path = os.path.join(root_dir, "config", "pipeline.yaml")
    cfg: Dict[str, Any] = {}
    try:
        import yaml
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as fh:
                loaded: Any = yaml.safe_load(fh) or {}
            if isinstance(loaded, dict):
                cfg = loaded
    except Exception:
        pass
    return cfg

print("Loading configuration...")
root_dir = os.path.dirname(os.path.abspath(__file__))
config = _load_pipeline_config(root_dir)

print(f"Configuration loaded: {list(config.keys())}")

# Get API key
api_key = os.getenv("ALLORA_API_KEY", "").strip()
print(f"API Key: {'Set' if api_key else 'Not set'}")

# Get wallet name
wallet_name_file = os.path.join(root_dir, ".wallet_name")
wallet_name = None
if os.path.exists(wallet_name_file):
    with open(wallet_name_file, "r") as f:
        wallet_name = f.read().strip()

print(f"Wallet name: {wallet_name or 'Not found'}")

print("\n=== Starting training ===")

try:
    print("Importing xgboost...")
    from xgboost import XGBRegressor
    
    print("Creating synthetic training data...")
    # Generate synthetic training data
    np.random.seed(42)
    n_samples = 100
    n_features = 10
    
    X_train = np.random.randn(n_samples, n_features)
    y_train = X_train[:, 0] + 0.5 * X_train[:, 1] + 0.2 * np.random.randn(n_samples)
    
    X_test = np.random.randn(30, n_features)
    y_test = X_test[:, 0] + 0.5 * X_test[:, 1] + 0.2 * np.random.randn(30)
    
    print(f"Training data shape: X={X_train.shape}, y={y_train.shape}")
    print(f"Test data shape: X={X_test.shape}, y={y_test.shape}")
    
    print("Training XGBoost model...")
    model = XGBRegressor(
        n_estimators=50,
        learning_rate=0.1,
        max_depth=3,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    
    print("Making predictions...")
    predictions = model.predict(X_test)
    
    print("Computing metrics...")
    metrics = {
        "mae": float(mean_absolute_error(y_test, predictions)),
        "mse": float(mean_squared_error(y_test, predictions)),
        "r2": float(r2_score(y_test, predictions)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    print("\n=== Training Complete ===")
    print(f"Metrics: {json.dumps(metrics, indent=2)}")
    
    # Save artifacts
    artifacts_dir = os.path.join(root_dir, "data", "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    
    import pickle
    model_path = os.path.join(artifacts_dir, "model.joblib")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"Model saved to {model_path}")
    
    metrics_path = os.path.join(artifacts_dir, "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved to {metrics_path}")
    
    # Make a simple prediction
    live_sample = np.random.randn(1, n_features)
    live_pred = model.predict(live_sample)[0]
    print(f"\nLive prediction: {live_pred}")
    
    print("\n=== SUCCESS ===")
    sys.exit(0)
    
except Exception as e:
    print(f"\n=== ERROR ===")
    print(f"Exception: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
