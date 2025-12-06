"""Shared logging, data fetching, and validation helpers.

This module prioritizes Tiingo data (with a valid API key), supports caching with
backoff retries, and marks synthetic fallbacks so callers can block
submissions when real market data is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

LOG_DIR = Path("logs")
ARTIFACTS_DIR = Path("artifacts")
CACHE_DIR = ARTIFACTS_DIR / "cache"
RAW_JSON_CACHE = CACHE_DIR / "btcusd_hourly.json"
CACHE_PATH = CACHE_DIR / "btcusd_hourly.parquet"
TIINGO_RATE_LIMIT_TRACKER = CACHE_DIR / "tiingo_rate_limit_tracker.json"

DEFAULT_TOPIC_ID = int(os.getenv("TOPIC_ID", os.getenv("ALLORA_TOPIC_ID", "67")))
MIN_COVERAGE_RATIO = 0.5

@dataclass
class FetchResult:
    source: str
    rows: int
    path: Optional[Path]
    coverage: float = 0.0
    reason: str = ""
    fallback_used: bool = False
    stale: bool = False

def ensure_directories() -> None:
    for path in (LOG_DIR, ARTIFACTS_DIR, CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)

def update_rate_limit_tracker(success: bool, status_code: Optional[int] = None) -> None:
    """Update the rate limit tracker with request results."""
    try:
        tracker = {"requests": [], "daily_count": 0, "last_reset": None}
        if TIINGO_RATE_LIMIT_TRACKER.exists():
            with TIINGO_RATE_LIMIT_TRACKER.open("r") as f:
                tracker = json.load(f)
        
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        
        # Reset daily count if it's a new day
        if tracker.get("last_reset") != today:
            tracker["daily_count"] = 0
            tracker["last_reset"] = today
        
        # Add this request
        tracker["requests"].append({
            "timestamp": now.isoformat(),
            "success": success,
            "status_code": status_code
        })
        
        # Keep only last 100 requests
        tracker["requests"] = tracker["requests"][-100:]
        
        if success:
            tracker["daily_count"] += 1
        
        # Save tracker
        with TIINGO_RATE_LIMIT_TRACKER.open("w") as f:
            json.dump(tracker, f, indent=2)
            
    except Exception as e:
        # Don't fail if tracker update fails
        pass

def cleanup_old_cache_files() -> None:
    """Clean up old Tiingo chunk cache files."""
    try:
        if not CACHE_DIR.exists():
            return
            
        for cache_file in CACHE_DIR.glob("tiingo_chunk_*.json"):
            try:
                # Remove files older than 7 days
                if time.time() - cache_file.stat().st_mtime > 7 * 24 * 3600:
                    cache_file.unlink()
            except Exception:
                pass
    except Exception:
        pass

def should_skip_tiingo_request() -> bool:
    """Check if we should skip Tiingo requests based on rate limiting."""
    try:
        if not TIINGO_RATE_LIMIT_TRACKER.exists():
            return False
            
        with TIINGO_RATE_LIMIT_TRACKER.open("r") as f:
            tracker = json.load(f)
        
        # Check recent failures
        recent_requests = tracker.get("requests", [])
        recent_failures = [r for r in recent_requests[-10:] if not r.get("success", True)]
        
        if len(recent_failures) >= 3:
            return True
            
        # Check daily limit (conservative estimate)
        daily_count = tracker.get("daily_count", 0)
        if daily_count >= 400:  # Conservative limit
            return True
            
        return False
        
    except Exception:
        return False

def setup_logging(name: str, log_file: Path) -> logging.Logger:
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
    if df is None or df.empty or "timestamp" not in df.columns:
        return False

    df_sorted = df.sort_values("timestamp")
    start_ts = pd.to_datetime(df_sorted["timestamp"].iloc[0])
    end_ts = pd.to_datetime(df_sorted["timestamp"].iloc[-1])

    coverage_hours = (end_ts - start_ts).total_seconds() / 3600
    required_hours = min_days * 24
    if coverage_hours < required_hours * 0.9:
        return False

    now_utc = datetime.now(timezone.utc)
    if end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=timezone.utc)

    if now_utc - end_ts > timedelta(hours=freshness_hours):
        return False

    if not df_sorted["timestamp"].is_monotonic_increasing:
        return False

    return True

def coverage_ratio(df: pd.DataFrame, days_back: int) -> float:
    if df is None or df.empty:
        return 0.0
    df_sorted = df.sort_values("timestamp")
    start_ts = pd.to_datetime(df_sorted["timestamp"].iloc[0])
    end_ts = pd.to_datetime(df_sorted["timestamp"].iloc[-1])
    coverage_hours = (end_ts - start_ts).total_seconds() / 3600
    required_hours = max(days_back * 24, 1)
    return max(0.0, min(coverage_hours / required_hours, 1.0))

def _format_price_frame(rows: List[Tuple[datetime, float]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "close"])
    df = df.dropna().drop_duplicates("timestamp").sort_values("timestamp")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df

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

def load_cached_prices() -> Optional[pd.DataFrame]:
    if CACHE_PATH.exists():
        try:
            return pd.read_parquet(CACHE_PATH)
        except Exception:
            return None
    return None

def _write_debug_payload(name: str, payload: object) -> None:
    ensure_directories()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    debug_path = CACHE_DIR / f"{name}_{timestamp}.json"
    try:
        with debug_path.open("w") as f:
            json.dump(payload, f, indent=2, default=str)
    except Exception:
        pass

class DataFetcher:
    def __init__(self, logger: logging.Logger, session: Optional[requests.Session] = None):
        self.logger = logger
        self.session = session or requests.Session()

    def _request_with_backoff(self, url: str, params: dict, attempts: int = 4, timeout: int = 20, backoff: int = 2) -> Tuple[Optional[object], Optional[int]]:
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                status = response.status_code
                
                # Update rate limit tracker
                success = status not in (418, 429) and 200 <= status < 300
                update_rate_limit_tracker(success, status)
                
                # Log response headers for rate limit debugging
                if status == 429:
                    self.logger.debug("Tiingo headers: %s", dict(response.headers))
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        self.logger.warning("Tiingo retry-after: %s seconds", retry_after)
                        try:
                            time.sleep(min(int(retry_after), 60))  # Cap at 60 seconds
                            continue
                        except ValueError:
                            pass
                
                if status in (418, 429):
                    self.logger.warning("Rate-limit or ban from %s (status=%s). attempt=%s/%s", url, status, attempt, attempts)
                    # Adaptive backoff: start at 5s, increase exponentially
                    sleep_time = 5 * attempt
                    self.logger.info("Sleeping %s seconds before retry...", sleep_time)
                    time.sleep(sleep_time)
                    continue
                response.raise_for_status()
                return response.json(), status
            except Exception as exc:
                self.logger.warning("Request failure %s attempt %s/%s: %s", url, attempt, attempts, exc)
                update_rate_limit_tracker(False, None)
                if attempt == attempts:
                    return None, None
                time.sleep(backoff * attempt)
        return None, None

    def _fetch_from_tiingo(self, days_back: int) -> Optional[pd.DataFrame]:
        token = os.getenv("TIINGO_API_KEY", "").strip()
        if not token:
            return None

        # Check if we should skip Tiingo requests due to rate limiting
        if should_skip_tiingo_request():
            self.logger.warning("Skipping Tiingo requests due to recent rate limit issues")
            return None

        url = "https://api.tiingo.com/tiingo/crypto/prices"
        rows: List[Tuple[datetime, float]] = []
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_back)
        chunk_days = 7

        # Limit chunks per call to avoid bulk rate limiting
        max_chunks = int(os.getenv("TIINGO_MAX_CHUNKS", "5"))
        chunks_processed = 0

        rate_limit_hits = 0

        while start < end and chunks_processed < max_chunks:
            chunk_end = min(start + timedelta(days=chunk_days), end)
            chunk_key = f"{start.strftime('%Y-%m-%d')}_{chunk_end.strftime('%Y-%m-%d')}"
            chunk_cache_path = CACHE_DIR / f"tiingo_chunk_{chunk_key}.json"
            
            # Try to load from chunk cache first
            chunk_data = None
            if chunk_cache_path.exists():
                try:
                    with chunk_cache_path.open("r") as f:
                        cached = json.load(f)
                    # Check if cache is fresh (less than 24 hours old)
                    cache_time = datetime.fromisoformat(cached["timestamp"])
                    if datetime.now(timezone.utc) - cache_time < timedelta(hours=24):
                        chunk_data = cached["data"]
                        self.logger.debug("Loaded chunk %s from cache", chunk_key)
                    else:
                        chunk_cache_path.unlink()  # Remove stale cache
                except Exception:
                    pass
            
            if chunk_data is None:
                params = {
                    "tickers": "btcusd",
                    "resampleFreq": "1hour",
                    "startDate": start.strftime("%Y-%m-%d"),
                    "endDate": chunk_end.strftime("%Y-%m-%d"),
                    "token": token,
                }
                data, status = self._request_with_backoff(url, params, attempts=3, backoff=3)
                if status == 429:
                    rate_limit_hits += 1
                    self.logger.warning("Tiingo rate limit encountered for %s-%s (hit %s); skipping chunk.", params["startDate"], params["endDate"], rate_limit_hits)
                    if rate_limit_hits >= 2:
                        break
                    start = chunk_end
                    continue
                if data is None:
                    self.logger.warning("Tiingo chunk %s-%s failed; skipping chunk.", params["startDate"], params["endDate"])
                    start = chunk_end
                    continue
                
                chunk_data = data
                # Cache the chunk
                try:
                    cache_entry = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "data": chunk_data
                    }
                    with chunk_cache_path.open("w") as f:
                        json.dump(cache_entry, f)
                except Exception:
                    pass
            
            chunks_processed += 1
            price_data = chunk_data[0].get("priceData", []) if isinstance(chunk_data[0], dict) else []
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

    def _fetch_synthetic(self, days_back: int) -> pd.DataFrame:
        self.logger.warning("Falling back to synthetic price series for %s days.", days_back)
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

    def fetch_price_history(self, days_back: int, force_refresh: bool = False, allow_fallback: bool = False, freshness_hours: int = 2) -> Tuple[pd.DataFrame, FetchResult]:
        ensure_directories()
        cleanup_old_cache_files()

        if not force_refresh:
            cached = load_cached_prices()
            if cached is not None and price_coverage_ok(cached, days_back, freshness_hours=freshness_hours):
                self.logger.info("Using cached market data (%s rows).", len(cached))
                return cached, FetchResult(
                    source="cache",
                    rows=len(cached),
                    path=CACHE_PATH,
                    coverage=coverage_ratio(cached, days_back),
                    stale=False,
                )

        # Check if Tiingo is rate limited before attempting
        if should_skip_tiingo_request():
            self.logger.warning("Tiingo rate limiting detected, skipping API calls")
            if allow_fallback:
                synthetic_df = self._fetch_synthetic(days_back)
                return synthetic_df, FetchResult(
                    source="synthetic",
                    rows=len(synthetic_df),
                    path=None,
                    coverage=coverage_ratio(synthetic_df, days_back),
                    fallback_used=True,
                    reason="tiingo_rate_limited"
                )
            else:
                return pd.DataFrame(), FetchResult(
                    source="none",
                    rows=0,
                    path=None,
                    coverage=0.0,
                    reason="tiingo_rate_limited"
                )

        self.logger.info("Fetching market data from Tiingo...")
        tiingo_df = self._fetch_from_tiingo(days_back)
        if tiingo_df is not None and price_coverage_ok(tiingo_df, days_back, freshness_hours=freshness_hours):
            _persist_cache(tiingo_df)
            return tiingo_df, FetchResult(
                source="tiingo",
                rows=len(tiingo_df),
                path=CACHE_PATH,
                coverage=coverage_ratio(tiingo_df, days_back),
                stale=False,
            )

        if allow_fallback:
            synthetic_df = self._fetch_synthetic(days_back)
            return synthetic_df, FetchResult(
                source="synthetic",
                rows=len(synthetic_df),
                path=None,
                coverage=coverage_ratio(synthetic_df, days_back),
                reason="tiingo unavailable",
                fallback_used=True,
                stale=True,
            )

        self.logger.error("❌ Tiingo data unavailable and fallback not allowed.")
        return pd.DataFrame(), FetchResult(
            source="unavailable",
            rows=0,
            path=None,
            coverage=0.0,
            reason="tiingo failed and fallback disabled",
            fallback_used=False,
            stale=True,
        )

__all__ = [
    "ARTIFACTS_DIR",
    "CACHE_PATH",
    "DEFAULT_TOPIC_ID",
    "DataFetcher",
    "FetchResult",
    "coverage_ratio",
    "ensure_directories",
    "load_cached_prices",
    "price_coverage_ok",
    "setup_logging",
]
