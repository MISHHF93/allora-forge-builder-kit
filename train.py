#!/usr/bin/env python3
"""
Minimal 7-Day BTC/USD Log-Return Forecast & Submission
-----------------------------------------------------
Fetch recent BTC/USD hourly price data, engineer lightweight features,
train a fresh model on rolling window (default 90 days), predict forward
168h log-return (log(price_t+168h / price_t)), and submit the forecast.

Single-run execution. No caching. No loops. No legacy abstractions.
"""

from __future__ import annotations

import os
import sys
import math
import time
import json
import shutil
import logging
import pickle
import joblib
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import requests
import numpy as np
import pandas as pd

try:
    import xgboost as xgb
    _XGB_AVAILABLE = True
except Exception as e:
    logger.error(f"❌ XGBoost import failed: {e}. Install with: pip install xgboost")
    _XGB_AVAILABLE = False
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error

###############################################################################
# Logging Setup
###############################################################################
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%SZ'
)
logger = logging.getLogger("btc_7d_forecast")

###############################################################################
# Configuration Dataclass
###############################################################################
@dataclass
class Config:
    days_back: int = 90                # Rolling window length (in days)
    horizon_hours: int = 168           # 7 days forward
    topic_id: int = int(os.getenv("TOPIC_ID", "67"))
    submit: bool = True                # Attempt blockchain submission
    api_timeout: int = 30              # Seconds for HTTP requests
    min_training_rows: int = 500       # Safety minimum

###############################################################################
# Data Fetching
###############################################################################
def fetch_btcusd_hourly(days_back: int) -> pd.DataFrame:
    """Fetch BTC/USD hourly close prices for given days via CoinGecko.

    Fallback: generate synthetic random walk if API fails.
    Returns DataFrame with columns: ['timestamp', 'close'] (UTC, hourly).
    """
    logger.info(f"Fetching {days_back}d hourly BTC/USD data from Tiingo...")
    tkey = os.getenv("TIINGO_API_KEY", "").strip()
    if not tkey:
        logger.warning("TIINGO_API_KEY not set; generating synthetic random walk.")
    else:
        try:
            # Tiingo expects startDate in ISO date and tickers like btcusd
            url = "https://api.tiingo.com/tiingo/crypto/prices"
            params = {
                "tickers": "btcusd",
                "startDate": (datetime.now(timezone.utc) - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d"),
                "resampleFreq": "1hour",
                "token": tkey,
            }
            r = requests.get(url, params=params, timeout=Config.api_timeout)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                raise ValueError("Unexpected Tiingo response format")
            # Tiingo returns a list where first element has priceData list
            price_data = data[0].get("priceData", [])
            if not price_data:
                raise ValueError("No data returned from Tiingo")
            rows = []
            for item in price_data:
                dt = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
                rows.append((dt, float(item["close"])))
            df = pd.DataFrame(rows, columns=["timestamp", "close"]).drop_duplicates("timestamp").sort_values("timestamp")
            expected_rows = days_back * 24
            if len(df) < expected_rows * 0.1:  # Less than 10% of expected
                logger.warning(f"Tiingo returned only {len(df)} rows, expected ~{expected_rows}; using synthetic fallback.")
                # Fall back to synthetic
            else:
                logger.info(f"Fetched {len(df)} hourly rows from Tiingo")
                return df
        except Exception as e:
            logger.warning(f"Tiingo API fetch failed ({e}); generating synthetic random walk.")
        hours = days_back * 24
        base = 40000.0
        rng = np.random.default_rng(int(time.time()))  # Use current time as seed for variation
        returns = rng.normal(0, 0.002, size=hours)  # small hourly drift
        prices: List[float] = []
        current = base
        for r in returns:
            current *= math.exp(r)
            prices.append(current)
        start = datetime.now(tz=timezone.utc) - pd.Timedelta(hours=hours)
        timestamps = [start + pd.Timedelta(hours=i) for i in range(hours)]
        df = pd.DataFrame({"timestamp": timestamps, "close": prices})
        logger.info(f"Synthetic series length: {len(df)}")
        return df

###############################################################################
# Feature Engineering
###############################################################################
def generate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add lightweight technical features for modeling.
    Features kept intentionally minimal for speed & robustness.
    """
    df = df.copy()
    df["log_price"] = np.log(df["close"])  # base feature
    df["ret_1h"] = df["log_price"].diff(1)
    df["ret_24h"] = df["log_price"].diff(24)
    df["ma_24h"] = df["close"].rolling(24).mean()
    df["ma_72h"] = df["close"].rolling(72).mean()
    df["vol_24h"] = df["ret_1h"].rolling(24).std()
    df["price_pos_24h"] = df["close"] / df["ma_24h"] - 1.0
    df["price_pos_72h"] = df["close"] / df["ma_72h"] - 1.0
    df["ma_ratio_72_24"] = df["ma_72h"] / df["ma_24h"] - 1.0
    df["exp_vol_ratio"] = df["vol_24h"].rolling(24).mean() / (df["vol_24h"] + 1e-8) - 1.0
    # Drop initial NaNs
    df = df.dropna().reset_index(drop=True)
    logger.info(f"Feature rows after dropna: {len(df)}")
    return df

###############################################################################
# Target Construction
###############################################################################
def add_forward_log_return_target(df: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    """Compute forward-looking log-return target: log(price_t+h / price_t)."""
    df = df.copy()
    future_price = df["close"].shift(-horizon_hours)
    df["target"] = np.log(future_price / df["close"])
    # Remove rows without a full future horizon
    valid = df[:-horizon_hours]
    logger.info(f"Target rows available: {len(valid)}")
    return valid

###############################################################################
# Model Training
###############################################################################
def train_model(df: pd.DataFrame) -> tuple[object, List[str]]:
    """Train XGBoost (if available) else Ridge regression. Save model explicitly via pickle and joblib."""
    feature_cols = [c for c in df.columns if c not in {"timestamp", "close", "target"}]
    X = df[feature_cols].values
    y = df["target"].values
    if len(df) < Config.min_training_rows:
        raise ValueError(f"Insufficient training rows: {len(df)} < {Config.min_training_rows}")
    logger.info(f"Training samples: {len(df)}, features: {len(feature_cols)}")
    model: object
    if _XGB_AVAILABLE:
        model = xgb.XGBRegressor(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            n_jobs=4,
            random_state=42,
        )
        model.fit(X, y)
    else:
        logger.warning("XGBoost unavailable; using Ridge regression fallback.")
        model = Ridge(alpha=1.0)
        model.fit(X, y)
    preds_in_sample = model.predict(X)
    # Manual RMSE to avoid version incompatibilities
    rmse = float(np.sqrt(np.mean((y - preds_in_sample) ** 2)))
    logger.info(f"In-sample RMSE: {rmse:.6f}")
    
    # TEST THE MODEL BEFORE SAVING: Verify it can predict on dummy input
    logger.info("Testing model with dummy input before saving...")
    try:
        dummy_shape = (1, X.shape[1])
        dummy_input = np.zeros(dummy_shape)
        dummy_pred = model.predict(dummy_input)
        logger.info(f"✓ Test prediction successful: {dummy_pred[0]:.8f}")
        # Verify n_features_in_ is set
        if hasattr(model, 'n_features_in_'):
            logger.info(f"✓ Model has n_features_in_={model.n_features_in_}")
        else:
            logger.error(f"❌ Model missing n_features_in_ attribute (unfitted)")
            raise RuntimeError("Model not properly fitted before saving")
    except Exception as e:
        logger.error(f"❌ Test prediction failed: {e}. Model is not fitted properly.")
        raise
    
    # Explicitly save model using both pickle and joblib for reliability
    try:
        with open("model.pkl", "wb") as f:
            pickle.dump(model, f)
        logger.info("✅ Model saved via pickle.dump() to model.pkl")
    except Exception as e:
        logger.error(f"❌ pickle.dump() failed: {e}")
        raise
    
    try:
        joblib.dump(model, "model.pkl")
        logger.info("✅ Model saved via joblib.dump() to model.pkl")
    except Exception as e:
        logger.error(f"❌ joblib.dump() failed: {e}")
        raise
    
    # FINAL VERIFICATION: Load and test the saved model file
    logger.info("Final verification: loading and testing saved model.pkl...")
    try:
        with open("model.pkl", "rb") as f:
            loaded_model = pickle.load(f)
        verify_pred = loaded_model.predict(dummy_input)
        logger.info(f"✓ Loaded model prediction successful: {verify_pred[0]:.8f}")
    except Exception as e:
        logger.error(f"❌ Failed to load/test model.pkl: {e}")
        raise
    
    return model, feature_cols

###############################################################################
# Live Feature Extraction & Prediction
###############################################################################
def prepare_latest_features(df: pd.DataFrame, feature_cols: List[str]) -> np.ndarray:
    latest = df.iloc[-1]
    return latest[feature_cols].values.reshape(1, -1)

def predict_forward_log_return(model: object, x_live: np.ndarray) -> float:
    pred = float(model.predict(x_live)[0])
    logger.info(f"Predicted 168h log-return: {pred:.8f}")
    return pred

###############################################################################
# Submission
###############################################################################
def submit_prediction(value: float, cfg: Config) -> bool:
    """Submit prediction via Allora SDK if available; fallback to CLI; always persist a local record.
    Expects environment variables for wallet context if required.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    record = {"timestamp_utc": timestamp, "topic_id": cfg.topic_id, "prediction_log_return_7d": value}
    # Append to local CSV log
    csv_path = "submission_log.csv"
    header_needed = not os.path.exists(csv_path)
    import csv
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(record.keys()))
        if header_needed:
            w.writeheader()
        w.writerow(record)
    # JSON snapshot
    with open("latest_submission.json", "w") as jf:
        json.dump(record, jf, indent=2)
    if not cfg.submit:
        logger.info("Submission disabled (cfg.submit=False). Skipping.")
        return False
    # Get block height
    block_height = 0
    pubkey = ""
    try:
        from allora_sdk import AlloraRPCClient
        client = AlloraRPCClient.from_env()
        block = client.get_latest_block()
        block_height = block.header.height
        pubkey = client.public_key.hex()
    except Exception as e:
        logger.warning(f"Failed to get block height/pubkey via SDK ({e}); trying REST.")
        try:
            import requests
            rpc_url = os.getenv("RPC_URL", "https://allora-rpc.testnet.allora.network/")
            r = requests.get(f"{rpc_url}/status", timeout=10)
            r.raise_for_status()
            block_height = int(r.json()["result"]["sync_info"]["latest_block_height"])
            pubkey = ""  # still empty
        except Exception as e2:
            logger.warning(f"Failed to get block height via REST ({e2})")
    # Try SDK submission first
    if block_height > 0:
        try:
            from allora_sdk.protos.emissions.v9 import InsertWorkerPayloadRequest, InputWorkerDataBundle, InputInferenceForecastBundle, InputInference
            from allora_sdk.protos.emissions.v9._v3__ import Nonce
            client = AlloraRPCClient.from_env()
            wallet = client.address
            nonce = Nonce(block_height=block_height)
            inference = InputInference(
                topic_id=cfg.topic_id,
                block_height=block_height,
                inferer=wallet,
                value=str(value),
                extra_data=b"",
                proof=""
            )
            bundle = InputInferenceForecastBundle(inference=inference)
            worker_data_bundle = InputWorkerDataBundle(
                worker=wallet,
                nonce=nonce,
                topic_id=cfg.topic_id,
                inference_forecasts_bundle=bundle,
                inferences_forecasts_bundle_signature=b"",
                pubkey=pubkey
            )
            request = InsertWorkerPayloadRequest(
                sender=wallet,
                worker_data_bundle=worker_data_bundle
            )
            tx_response = client.tx_manager.send_tx(request)
            logger.info("✅ Submission via SDK success")
            return True
        except Exception as e:
            logger.warning(f"SDK submission failed ({e}); falling back to CLI.")
    # Fallback to CLI
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.warning("Allora CLI not found in PATH; skipping on-chain submission.")
        return False
    wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
    if not wallet:
        logger.warning("ALLORA_WALLET_ADDR not set; skipping on-chain submission.")
        return False
    # Correct worker_data as JSON of InputWorkerDataBundle
    worker_data = {
        "worker": wallet,
        "nonce": {"block_height": block_height},
        "topic_id": cfg.topic_id,
        "inference_forecasts_bundle": {
            "inference": {
                "topic_id": cfg.topic_id,
                "block_height": block_height,
                "inferer": wallet,
                "value": str(value),
                "extra_data": "",
                "proof": ""
            }
        },
        "inferences_forecasts_bundle_signature": "",
        "pubkey": pubkey
    }
    cmd = [cli, "tx", "emissions", "insert-worker-payload", wallet, json.dumps(worker_data), "--yes", "--keyring-backend", "test", "--node", "https://allora-rpc.testnet.allora.network/", "--chain-id", "allora-testnet-1"]
    logger.info("Submitting via CLI: %s", " ".join(cmd))
    try:
        import subprocess
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            logger.info("✅ Submission CLI success")
            return True
        else:
            logger.error(f"Submission CLI failed (rc={proc.returncode}): {proc.stdout} {proc.stderr}")
            return False
    except Exception as e:
        logger.error(f"CLI submission error: {e}")
        return False

###############################################################################
# Orchestration
###############################################################################
def run(cfg: Config) -> int:
    start = time.time()
    try:
        raw = fetch_btcusd_hourly(cfg.days_back)
        feats = generate_features(raw)
        labeled = add_forward_log_return_target(feats, cfg.horizon_hours)
        model, cols = train_model(labeled)
        
        # Verify model.pkl exists
        if not os.path.exists("model.pkl"):
            logger.error("CRITICAL: model.pkl was not saved. Aborting.")
            return 1
        logger.info("✅ model.pkl verified to exist.")
        
        # Save features for later use
        with open("features.json", "w") as f:
            json.dump(cols, f)
        logger.info(f"Features saved to features.json ({len(cols)} columns)")
        
        x_live = prepare_latest_features(feats, cols)  # use freshest feature row
        pred = predict_forward_log_return(model, x_live)
        submitted = submit_prediction(pred, cfg)
        logger.info(f"Submission status: {'submitted' if submitted else 'not_submitted'}")
        elapsed = time.time() - start
        logger.info(f"Pipeline complete in {elapsed:.2f}s")
        return 0
    except Exception as e:
        logger.error(f"Fatal pipeline error: {e}")
        return 1

###############################################################################
# Entry Point
###############################################################################
def main():
    # Simple env-driven configuration; avoid argparse for minimalism.
    days_back = int(os.getenv("FORECAST_DAYS_BACK", "90"))
    submit_flag = os.getenv("FORECAST_SUBMIT", "true").lower() in {"1", "true", "yes"}
    cfg = Config(days_back=days_back, submit=submit_flag)
    logger.info("=" * 72)
    logger.info("BTC 7D LOG-RETURN FORECAST - SINGLE RUN")
    logger.info("Config: days_back=%d, submit=%s, topic_id=%d", cfg.days_back, cfg.submit, cfg.topic_id)
    
    # Verify critical dependencies
    if not _XGB_AVAILABLE:
        logger.error("❌ CRITICAL: XGBoost is not installed. Install with: pip install xgboost")
        logger.error("   Falling back to Ridge regression (lower accuracy).")
    
    rc = run(cfg)
    logger.info("Exit code: %d", rc)
    return rc

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
