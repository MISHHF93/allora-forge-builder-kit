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
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timezone

import requests
import numpy as np
import pandas as pd

try:
    from xgboost import XGBoostError  # type: ignore
    import xgboost as xgb
    _XGB_AVAILABLE = True
except Exception:  # pragma: no cover - fallback
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
    topic_id: int = int(os.getenv("ALLORA_TOPIC_ID", "67"))
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
    logger.info(f"Fetching {days_back}d hourly BTC/USD data from CoinGecko...")
    url = (
        "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
        f"?vs_currency=usd&days={days_back}&interval=hourly"
    )
    try:
        resp = requests.get(url, timeout=Config.api_timeout)
        resp.raise_for_status()
        data = resp.json()
        prices = data.get("prices", [])
        if not prices:
            raise ValueError("Empty price list from API")
        rows = []
        for ts_ms, price in prices:
            # Align to hour (CoinGecko returns ms timestamps)
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            dt_floor = dt.replace(minute=0, second=0, microsecond=0)
            rows.append((dt_floor, float(price)))
        df = pd.DataFrame(rows, columns=["timestamp", "close"]).drop_duplicates("timestamp").sort_values("timestamp")
        logger.info(f"Fetched {len(df)} hourly rows")
        return df
    except Exception as e:
        logger.warning(f"API fetch failed ({e}); generating synthetic random walk.")
        hours = days_back * 24
        base = 40000.0
        rng = np.random.default_rng(42)
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
    """Train XGBoost (if available) else Ridge regression."""
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
    """Submit prediction via Allora CLI if available; always persist a local record.
    Expects environment variables for wallet context if required.
    """
    timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
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
        logger.info("Submission disabled (cfg.submit=False). Skipping CLI call.")
        return False
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.warning("Allora CLI not found in PATH; skipping on-chain submission.")
        return False
    cmd = [cli, "submit", "--topic-id", str(cfg.topic_id), "--value", f"{value:.10f}"]
    logger.info("Submitting via CLI: %s", " ".join(cmd))
    try:
        proc = shutil.which("bash") and __import__("subprocess").run(cmd, capture_output=True, text=True, timeout=60)
        if proc and proc.returncode == 0:
            logger.info("✅ Submission CLI success")
            return True
        else:
            if proc:
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
    rc = run(cfg)
    logger.info("Exit code: %d", rc)
    return rc

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
