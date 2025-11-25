"""Utility helpers for the Python-only BTC/USD forecasting pipeline.

This module centralizes fetching, retry/backoff, caching, and logging helpers
used by both training and submission entrypoints. It also records debugging
artifacts for Tiingo/Coingecko fetches under ``tiingo_debug/``.
"""
from __future__ import annotations

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

LOG_DIR = Path("logs")
ARTIFACTS_DIR = Path("artifacts")
DEBUG_DIR = Path("tiingo_debug")
CACHE_PATH = DEBUG_DIR / "btcusd_hourly.parquet"
RAW_JSON_CACHE = DEBUG_DIR / "btcusd_hourly.json"

DEFAULT_TOPIC_ID = int(os.getenv("TOPIC_ID", os.getenv("ALLORA_TOPIC_ID", "67")))


@dataclass
class FetchResult:
    source: str
    rows: int
    path: Optional[Path]
    reason: str = ""


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
    url: str,
    params: dict,
    *,
    attempts: int = 3,
    timeout: int = 30,
    backoff: int = 2,
    logger: Optional[logging.Logger] = None,
) -> Optional[dict]:
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            if logger:
                logger.warning("Request failed (attempt %s/%s): %s", attempt, attempts, exc)
            if attempt == attempts:
                return None
            time.sleep(backoff * attempt)
    return None


def _format_price_frame(rows: Iterable[Tuple[datetime, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "close"])
    df = df.dropna().drop_duplicates("timestamp").sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _write_debug_payload(name: str, payload: object) -> None:
    """Persist raw payloads for debugging fetch flows."""
    ensure_directories()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    debug_path = DEBUG_DIR / f"{name}_{timestamp}.json"
    try:
        with debug_path.open("w") as f:
            json.dump(payload, f, indent=2, default=str)
    except Exception:
        pass


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
        data = _request_with_retry(url, params, attempts=4, backoff=3, logger=logger)
        if data is None:
            logger.warning("Tiingo chunk %s-%s failed; skipping chunk.", params["startDate"], params["endDate"])
            start = chunk_end
            continue

        _write_debug_payload(f"tiingo_chunk_{params['startDate']}_{params['endDate']}", data)

        if isinstance(data, dict) and "detail" in data:
            detail_msg = str(data.get("detail"))
            if "over your hourly request allocation" in detail_msg:
                logger.warning("Tiingo rate limit hit for %s-%s; skipping to next chunk.", params["startDate"], params["endDate"])
                start = chunk_end
                continue

        if not isinstance(data, list) or not data:
            logger.info("No Tiingo data returned for %s-%s; skipping chunk.", params["startDate"], params["endDate"])
            start = chunk_end
            continue

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
    merged_df = _format_price_frame(rows)
    _write_debug_payload("tiingo_merged", merged_df.to_dict(orient="records"))
    return merged_df


def fetch_from_coingecko(days_back: int, logger: logging.Logger) -> Optional[pd.DataFrame]:
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
    params = {"vs_currency": "usd", "days": days_back, "interval": "hourly"}
    data = _request_with_retry(url, params, attempts=3, backoff=2, logger=logger)
    if not data or "prices" not in data:
        logger.warning("CoinGecko fetch failed or malformed response.")
        return None

    _write_debug_payload("coingecko_payload", data)

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


def fetch_synthetic(days_back: int, logger: logging.Logger) -> pd.DataFrame:
    """Fallback synthetic generator to keep the pipeline running when offline."""
    logger.warning("Falling back to synthetic price series for %s days.", days_back)
    end = datetime.now(timezone.utc)
    timestamps = [end - timedelta(hours=h) for h in range(days_back * 24, -1, -1)]
    base = 30000.0
    rng = np.random.default_rng(seed=42)
    noise = rng.normal(scale=50.0, size=len(timestamps))
    trend = np.linspace(-100, 100, num=len(timestamps))
    prices = base + noise + trend
    rows = list(zip(timestamps, prices))
    synthetic_df = _format_price_frame(rows)
    _write_debug_payload("synthetic_prices", synthetic_df.to_dict(orient="records"))
    return synthetic_df


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

    synthetic_df = fetch_synthetic(days_back, logger)
    _persist_cache(synthetic_df)
    return synthetic_df, FetchResult(source="synthetic", rows=len(synthetic_df), path=CACHE_PATH, reason="fallback synthetic")
