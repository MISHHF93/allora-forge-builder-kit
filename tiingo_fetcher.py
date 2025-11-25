"""Utility to fetch BTC/USD data from Tiingo in iterative 3-day windows.

This module translates the legacy shell-based Tiingo fetcher into Python. It
handles rate limits gracefully, saves intermediate chunks for debugging, and
produces a merged JSON file compatible with the rest of the pipeline.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests


LOGGER = logging.getLogger("tiingo_fetcher")


def _parse_date(date_str: str) -> datetime:
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        # Allow simple YYYY-MM-DD inputs
        return datetime.strptime(date_str, "%Y-%m-%d")


def fetch_btc_data_to_file(
    end_date: str = "2025-12-15",
    output_path: str = "tiingo_debug/merged_btc_data.json",
    step_days: int = 3,
    max_days: int = 365,
    api_timeout: int = 30,
) -> Optional[Path]:
    """Fetch BTC/USD hourly data from Tiingo in backwards 3-day windows.

    Args:
        end_date: ISO date string marking the last date to include.
        output_path: Destination for the merged JSON output.
        step_days: Number of days per request window (default 3-day chunks).
        max_days: Safety cap on how far back to fetch.
        api_timeout: HTTP timeout for Tiingo requests.

    Returns:
        Path to the merged output file if data was collected, otherwise ``None``.
    """

    token = os.getenv("TIINGO_API_KEY", "").strip()
    if not token:
        LOGGER.warning("TIINGO_API_KEY not set; skipping Tiingo fetch.")
        return None

    try:
        current_end = _parse_date(end_date).date()
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.error(f"Invalid end_date '{end_date}': {exc}")
        return None

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    url = "https://api.tiingo.com/tiingo/crypto/prices"
    merged: List[Dict] = []
    seen_dates = set()
    days_processed = 0

    while days_processed < max_days:
        window_start = current_end - timedelta(days=step_days - 1)
        params = {
            "tickers": "btcusd",
            "resampleFreq": "1hour",
            "startDate": window_start.isoformat(),
            "endDate": current_end.isoformat(),
            "token": token,
        }

        LOGGER.info(
            "Fetching Tiingo BTCUSD chunk: %s to %s", window_start.isoformat(), current_end.isoformat()
        )

        try:
            resp = requests.get(url, params=params, timeout=api_timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # pragma: no cover - network
            LOGGER.warning("Tiingo request failed for %s-%s: %s", window_start, current_end, exc)
            break

        if isinstance(data, dict) and "detail" in data:
            detail_msg = str(data.get("detail"))
            if "over your hourly request allocation" in detail_msg:
                LOGGER.warning("Tiingo rate limit hit: %s", detail_msg)
                # Skip this window but continue stepping back to avoid hammering
                current_end = window_start - timedelta(days=1)
                days_processed += step_days
                continue

        if not isinstance(data, list) or not data:
            LOGGER.info("No Tiingo data returned for %s-%s; stopping fetch loop.", window_start, current_end)
            break

        price_data = data[0].get("priceData", []) if isinstance(data[0], dict) else []
        chunk_path = out_path.parent / f"chunk_{window_start}_{current_end}.json"
        try:
            with chunk_path.open("w") as chunk_file:
                json.dump(price_data, chunk_file, indent=2)
            LOGGER.debug("Saved Tiingo chunk to %s (%d rows)", chunk_path, len(price_data))
        except Exception as exc:  # pragma: no cover - filesystem
            LOGGER.warning("Failed to save chunk %s: %s", chunk_path, exc)

        added_rows = 0
        for item in price_data:
            ts = item.get("date")
            if not ts or ts in seen_dates:
                continue
            seen_dates.add(ts)
            merged.append(item)
            added_rows += 1

        LOGGER.info(
            "Chunk %s-%s: received %d rows, %d new unique timestamps (total=%d)",
            window_start,
            current_end,
            len(price_data),
            added_rows,
            len(merged),
        )

        days_processed += step_days
        current_end = window_start - timedelta(days=1)

    if not merged:
        LOGGER.warning("No Tiingo data collected; merged file will not be created.")
        return None

    merged_sorted = sorted(merged, key=lambda row: row.get("date", ""))
    try:
        with out_path.open("w") as out_file:
            json.dump(merged_sorted, out_file, indent=2)
        LOGGER.info("Merged %d Tiingo rows into %s", len(merged_sorted), out_path)
    except Exception as exc:  # pragma: no cover - filesystem
        LOGGER.error("Failed to write merged Tiingo data to %s: %s", out_path, exc)
        return None

    return out_path

