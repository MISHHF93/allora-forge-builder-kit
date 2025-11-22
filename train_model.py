#!/usr/bin/env python3
"""
BTC/USD 7-Day Log-Return Prediction Training Script
---------------------------------------------------
Fetches historical BTC/USD hourly data from Tiingo (with synthetic fallback),
engineers features, constructs forward log-return targets, trains XGBoost model,
and saves the model and feature columns for inference.

Usage:
    python train_model.py [--days-back DAYS] [--output-model MODEL_PATH] [--output-features FEATURES_PATH]
"""

import os
import sys
import math
import time
import json
import logging
import argparse
from typing import List
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import requests
import numpy as np
import pandas as pd

try:
    import xgboost as xgb
    _XGB_AVAILABLE = True
except Exception:
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
logger = logging.getLogger("btc_train")

###############################################################################
# Data Fetching
###############################################################################
def fetch_btcusd_hourly(days_back: int, api_timeout: int = 30) -> pd.DataFrame:
    """Fetch BTC/USD hourly close prices for given days via Tiingo.

    Fallback: generate synthetic random walk if API fails.
    Returns DataFrame with columns: ['timestamp', 'close'] (UTC, hourly).
    """
    logger.info(f"Fetching {days_back}d hourly BTC/USD data from Tiingo...")
    tkey = os.getenv("TIINGO_API_KEY", "").strip()
    if not tkey:
        logger.warning("TIINGO_API_KEY not set; generating synthetic random walk.")
    else:
        try:
            url = "https://api.tiingo.com/tiingo/crypto/prices"
            params = {
                "tickers": "btcusd",
                "startDate": (datetime.now(timezone.utc) - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d"),
                "resampleFreq": "1hour",
                "token": tkey,
            }
            r = requests.get(url, params=params, timeout=api_timeout)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                raise ValueError("Unexpected Tiingo response format")
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
            else:
                logger.info(f"Fetched {len(df)} hourly rows from Tiingo")
                return df
        except Exception as e:
            logger.warning(f"Tiingo API fetch failed ({e}); generating synthetic random walk.")
    # Synthetic fallback
    hours = days_back * 24
    base = 40000.0
    rng = np.random.default_rng(int(time.time()))
    returns = rng.normal(0, 0.002, size=hours)
    prices = []
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
    """Add lightweight technical features for modeling."""
    df = df.copy()
    df["log_price"] = np.log(df["close"])
    df["ret_1h"] = df["log_price"].diff(1)
    df["ret_24h"] = df["log_price"].diff(24)
    df["ma_24h"] = df["close"].rolling(24).mean()
    df["ma_72h"] = df["close"].rolling(72).mean()
    df["vol_24h"] = df["ret_1h"].rolling(24).std()
    df["price_pos_24h"] = df["close"] / df["ma_24h"] - 1.0
    df["price_pos_72h"] = df["close"] / df["ma_72h"] - 1.0
    df["ma_ratio_72_24"] = df["ma_72h"] / df["ma_24h"] - 1.0
    df["exp_vol_ratio"] = df["vol_24h"].rolling(24).mean() / (df["vol_24h"] + 1e-8) - 1.0
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
    valid = df[:-horizon_hours]
    logger.info(f"Target rows available: {len(valid)}")
    return valid

###############################################################################
# Model Training
###############################################################################
def train_model(df: pd.DataFrame, min_training_rows: int = 500) -> tuple[object, List[str]]:
    """Train XGBoost (if available) else Ridge regression."""
    feature_cols = [c for c in df.columns if c not in {"timestamp", "close", "target"}]
    X = df[feature_cols].values
    y = df["target"].values
    if len(df) < min_training_rows:
        raise ValueError(f"Insufficient training rows: {len(df)} < {min_training_rows}")
    logger.info(f"Training samples: {len(df)}, features: {len(feature_cols)}")
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
    rmse = float(np.sqrt(np.mean((y - preds_in_sample) ** 2)))
    logger.info(f"In-sample RMSE: {rmse:.6f}")
    return model, feature_cols

###############################################################################
# Main
###############################################################################
def main():
    parser = argparse.ArgumentParser(description="Train BTC/USD 7-day log-return prediction model.")
    parser.add_argument("--days-back", type=int, default=90, help="Days of historical data to fetch.")
    parser.add_argument("--horizon-hours", type=int, default=168, help="Prediction horizon in hours.")
    parser.add_argument("--output-model", type=str, default="model.pkl", help="Path to save trained model.")
    parser.add_argument("--output-features", type=str, default="features.json", help="Path to save feature columns.")
    parser.add_argument("--min-rows", type=int, default=500, help="Minimum training rows required.")
    args = parser.parse_args()

    start = time.time()
    try:
        raw = fetch_btcusd_hourly(args.days_back)
        feats = generate_features(raw)
        labeled = add_forward_log_return_target(feats, args.horizon_hours)
        model, cols = train_model(labeled, args.min_rows)

        # Save model
        import pickle
        with open(args.output_model, "wb") as f:
            pickle.dump(model, f)
        logger.info(f"Model saved to {args.output_model}")

        # Save features
        with open(args.output_features, "w") as f:
            json.dump(cols, f)
        logger.info(f"Features saved to {args.output_features}")

        elapsed = time.time() - start
        logger.info(f"Training complete in {elapsed:.2f}s")
        return 0
    except Exception as e:
        logger.error(f"Training error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())