"""Shared utilities for the Python-only BTC/USD forecasting pipeline.

The module centralizes data fetching, caching, feature engineering,
model training, artifact persistence, and submission logging for the
Allora Labs 7-day BTC/USD log-return competition.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import Ridge

LOG_DIR = Path("logs")
ARTIFACTS_DIR = Path("artifacts")
DEBUG_DIR = Path("tiingo_debug")
CACHE_PATH = DEBUG_DIR / "btcusd_hourly.parquet"
RAW_JSON_CACHE = DEBUG_DIR / "btcusd_hourly.json"

DEFAULT_TOPIC_ID = int(os.getenv("TOPIC_ID", os.getenv("ALLORA_TOPIC_ID", "67")))


def ensure_directories() -> None:
    """Create standard pipeline directories if they do not exist."""
    for path in (LOG_DIR, ARTIFACTS_DIR, DEBUG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def setup_logging(name: str, log_file: Path) -> logging.Logger:
    """Configure and return a logger that writes to console and a file."""
    ensure_directories()
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%SZ"
        )

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(logging.INFO)

        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger


@dataclass
class FetchResult:
    source: str
    rows: int
    path: Optional[Path]
    reason: str = ""


def price_coverage_ok(df: pd.DataFrame, min_days: int, freshness_hours: int = 2) -> bool:
    """Validate that the cached price data covers the requested window and is fresh."""
    if df is None or df.empty:
        return False

    ts_col = "timestamp"
    if ts_col not in df.columns:
        return False

    df_sorted = df.sort_values(ts_col)
    start_ts = df_sorted[ts_col].iloc[0]
    end_ts = df_sorted[ts_col].iloc[-1]

    if isinstance(start_ts, str):
        start_ts = pd.to_datetime(start_ts)
    if isinstance(end_ts, str):
        end_ts = pd.to_datetime(end_ts)

    coverage_hours = (end_ts - start_ts).total_seconds() / 3600
    required_hours = min_days * 24
    if coverage_hours < required_hours * 0.9:  # allow small gaps
        return False

    now_utc = datetime.now(timezone.utc)
    if isinstance(end_ts, pd.Timestamp):
        end_ts = end_ts.to_pydatetime()
    if end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=timezone.utc)

    if now_utc - end_ts > timedelta(hours=freshness_hours):
        return False

    if not df_sorted[ts_col].is_monotonic_increasing:
        return False

    return True


def _request_with_retry(
    url: str, params: dict, *, attempts: int = 3, timeout: int = 30, backoff: int = 2
) -> Optional[dict]:
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception:
            if attempt == attempts:
                return None
            time.sleep(backoff * attempt)
    return None


def _format_price_frame(rows: Iterable[Tuple[datetime, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "close"])
    df = df.dropna().drop_duplicates("timestamp").sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def fetch_from_tiingo(days_back: int, logger: logging.Logger) -> Optional[pd.DataFrame]:
    token = os.getenv("TIINGO_API_KEY", "").strip()
    if not token:
        logger.warning("TIINGO_API_KEY not set; skipping Tiingo fetch.")
        return None

    url = "https://api.tiingo.com/tiingo/crypto/prices"
    rows: List[Tuple[datetime, float]] = []
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    chunk_days = 7

    while start < end:
        chunk_end = min(start + timedelta(days=chunk_days), end)
        params = {
            "tickers": "btcusd",
            "resampleFreq": "1hour",
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": chunk_end.strftime("%Y-%m-%d"),
            "token": token,
        }
        data = _request_with_retry(url, params, attempts=4, backoff=3)
        if not data or not isinstance(data, list):
            logger.warning("Tiingo chunk %s-%s failed; breaking.", params["startDate"], params["endDate"])
            break
        price_data = data[0].get("priceData", []) if isinstance(data[0], dict) else []
        for item in price_data:
            ts_raw = item.get("date")
            close = item.get("close")
            if ts_raw is None or close is None:
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                rows.append((ts, float(close)))
            except Exception:
                continue
        start = chunk_end

    if not rows:
        return None
    return _format_price_frame(rows)


def fetch_from_coingecko(days_back: int, logger: logging.Logger) -> Optional[pd.DataFrame]:
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": days_back, "interval": "hourly"}
    data = _request_with_retry(url, params, attempts=3, backoff=2)
    if not data or "prices" not in data:
        logger.warning("CoinGecko fetch failed or malformed response.")
        return None

    rows: List[Tuple[datetime, float]] = []
    for ts_ms, price in data.get("prices", []):
        try:
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            rows.append((ts, float(price)))
        except Exception:
            continue
    if not rows:
        return None
    return _format_price_frame(rows)


def load_cached_prices() -> Optional[pd.DataFrame]:
    if CACHE_PATH.exists():
        try:
            return pd.read_parquet(CACHE_PATH)
        except Exception:
            return None
    return None


def _persist_cache(df: pd.DataFrame) -> None:
    ensure_directories()
    try:
        df.to_parquet(CACHE_PATH, index=False)
        CACHE_PATH.touch()
    except Exception:
        pass
    try:
        df.to_json(RAW_JSON_CACHE, orient="records", indent=2, date_format="iso")
    except Exception:
        pass


def fetch_price_history(days_back: int, logger: logging.Logger, force_refresh: bool = False) -> Tuple[pd.DataFrame, FetchResult]:
    """Return price history either from cache or live sources with fallback."""
    ensure_directories()
    if not force_refresh:
        cached = load_cached_prices()
        if cached is not None and price_coverage_ok(cached, days_back):
            return cached, FetchResult(source="cache", rows=len(cached), path=CACHE_PATH)

    tiingo_df = fetch_from_tiingo(days_back, logger)
    if tiingo_df is not None and price_coverage_ok(tiingo_df, days_back, freshness_hours=6):
        _persist_cache(tiingo_df)
        return tiingo_df, FetchResult(source="tiingo", rows=len(tiingo_df), path=CACHE_PATH)

    coingecko_df = fetch_from_coingecko(days_back, logger)
    if coingecko_df is not None and price_coverage_ok(coingecko_df, days_back, freshness_hours=6):
        _persist_cache(coingecko_df)
        return coingecko_df, FetchResult(source="coingecko", rows=len(coingecko_df), path=CACHE_PATH)

    return pd.DataFrame(), FetchResult(source="none", rows=0, path=None, reason="no data")


def generate_features(df: pd.DataFrame) -> pd.DataFrame:
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
    return df


def add_forward_target(df: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    df = df.copy()
    future_price = df["close"].shift(-horizon_hours)
    df["target"] = np.log(future_price / df["close"])
    return df.iloc[:-horizon_hours]


def train_model(train_df: pd.DataFrame, feature_cols: List[str]) -> Ridge:
    model = Ridge(alpha=1.0)
    model.fit(train_df[feature_cols], train_df["target"])
    return model


def save_artifacts(model: object, feature_cols: List[str]) -> None:
    ensure_directories()
    model_path = ARTIFACTS_DIR / "model.pkl"
    features_path = ARTIFACTS_DIR / "features.json"
    import joblib

    joblib.dump(model, model_path)
    with features_path.open("w") as f:
        json.dump(feature_cols, f, indent=2)


def artifacts_available() -> bool:
    return (ARTIFACTS_DIR / "model.pkl").exists() and (ARTIFACTS_DIR / "features.json").exists()


def load_artifacts() -> Tuple[object, List[str]]:
    import joblib

    model_path = ARTIFACTS_DIR / "model.pkl"
    features_path = ARTIFACTS_DIR / "features.json"

    model = joblib.load(model_path)
    with features_path.open() as f:
        features = json.load(f)
    return model, features


def latest_feature_row(df: pd.DataFrame, feature_cols: List[str]) -> np.ndarray:
    return df[feature_cols].iloc[-1:].values


def validate_prediction(prediction: float, max_abs: float = 1.5) -> bool:
    if prediction is None or not math.isfinite(prediction):
        return False
    return abs(prediction) <= max_abs


def log_submission_record(
    timestamp: datetime,
    topic_id: int,
    prediction: float,
    worker: str,
    status: str,
    extra: Optional[dict] = None,
) -> Path:
    ensure_directories()
    csv_path = LOG_DIR / "submission_log.csv"
    header_needed = not csv_path.exists()
    with csv_path.open("a", newline="") as f:
        fieldnames = ["timestamp", "topic_id", "prediction", "worker", "status", "details"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if header_needed:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp.isoformat(),
                "topic_id": topic_id,
                "prediction": prediction,
                "worker": worker,
                "status": status,
                "details": json.dumps(extra or {}),
            }
        )
    return csv_path
