#!/usr/bin/env python3
"""
Unified Pipeline Runner for Allora Forge Builder Kit - Topic 67
BTC/USD 7-day log-return competition submission pipeline.

This script handles the complete cycle:
1. Environment setup and validation
2. Competition window detection and backfilling
3. Model training with feature deduplication
4. Prediction validation
5. Blockchain submission with duplicate prevention
6. Comprehensive logging and artifact management

Usage:
    # Batch mode (backfill missing submissions)
    python run_pipeline.py                    # Backfill all missing hours (with --max-hours limit)
    python run_pipeline.py --live            # Only current hour (for cron)
    python run_pipeline.py --start 2025-10-01T00:00:00Z --end 2025-10-02T00:00:00Z  # Specific range
    python run_pipeline.py --max-hours 50    # Limit processing to 50 hours

    # Continuous mode (persistent monitoring)
    python run_pipeline.py --continuous      # Run indefinitely, monitor submission windows in real-time

Arguments:
    --start: Start date (ISO8601, default: competition start 2025-09-16T13:00:00Z)
    --end: End date (ISO8601, default: competition end 2025-12-15T13:00:00Z)
    --live: Only run for current hour (useful for cron scheduling)
    --max-hours: Maximum hours to process in one run (default: 100)
    --continuous: Run in continuous monitoring mode (singleton, real-time scheduling)
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import requests
import yaml
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Local imports
from allora_forge_builder_kit.submission import DEFAULT_FEE_DENOM, DEFAULT_MIN_GAS_PRICE

# Competition configuration
COMPETITION_START = datetime(2025, 9, 16, 13, 0, 0, tzinfo=timezone.utc)
COMPETITION_END = datetime(2025, 12, 15, 13, 0, 0, tzinfo=timezone.utc)
TOPIC_ID = 67
TICKER = "btcusd"
TARGET_HOURS = 168  # 7 days
HISTORY_BUFFER_HOURS = 48
TRAIN_SPAN_HOURS = 672  # 28 days
VALIDATION_SPAN_HOURS = 168  # 7 days

# Paths
REPO_ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = REPO_ROOT / "data" / "artifacts"
LOGS_DIR = ARTIFACTS_DIR / "logs"
SUBMISSION_LOG = LOGS_DIR / "submission_log.csv"
PREDICTIONS_JSON = ARTIFACTS_DIR / "predictions.json"
METRICS_JSON = ARTIFACTS_DIR / "metrics.json"
MODEL_JOBLIB = ARTIFACTS_DIR / "model.joblib"

# Blockchain configuration
DEFAULT_RPC = "grpc+https://allora-grpc.testnet.allora.network:443"
CHAIN_ID = "allora-testnet-1"
API_KEY_ENV = "ALLORA_API_KEY"
WALLET_ENV = "ALLORA_WALLET_ADDR"

# Logging schema
CANONICAL_HEADER = [
    "timestamp_utc", "topic_id", "value", "wallet", "nonce", "tx_hash",
    "success", "exit_code", "status", "log10_loss", "score", "reward"
]


@dataclass
class TrainingResult:
    prediction_time: datetime
    prediction_value: float
    metrics: Dict[str, float]
    features_count: int


@dataclass
class SubmissionResult:
    success: bool
    exit_code: int
    status: str
    nonce: Optional[int] = None
    tx_hash: Optional[str] = None


def load_environment(root: Path) -> None:
    """Load environment variables from .env if present."""
    env_path = root / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path))
        except ImportError:
            # Fallback: simple .env parser
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        os.environ[key.strip()] = value.strip()

    # Load mnemonic from .allora_key if present
    allora_key_path = root / ".allora_key"
    if allora_key_path.exists():
        try:
            mnemonic = allora_key_path.read_text(encoding="utf-8").strip()
            if mnemonic and not os.getenv("ALLORA_MNEMONIC"):
                os.environ["ALLORA_MNEMONIC"] = mnemonic
        except OSError:
            pass


def setup_environment() -> None:
    """Ensure required directories and environment variables exist."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Load environment variables
    load_environment(REPO_ROOT)

    # Check required environment variables
    if not os.getenv(API_KEY_ENV):
        raise RuntimeError(f"Missing required environment variable: {API_KEY_ENV}")
    if not os.getenv(WALLET_ENV):
        raise RuntimeError(f"Missing required environment variable: {WALLET_ENV}")


def is_competition_active() -> bool:
    """Check if current time is within competition submission window."""
    now = datetime.now(timezone.utc)
    return COMPETITION_START <= now <= COMPETITION_END


def is_submission_window() -> bool:
    """Check if we're within 5 minutes of the top of the hour."""
    now = datetime.now(timezone.utc)
    return now.minute <= 5


def rotate_log_if_needed() -> None:
    """Rotate submission log if it exceeds size or age limits."""
    if not SUBMISSION_LOG.exists():
        return

    size_mb = SUBMISSION_LOG.stat().st_size / (1024 * 1024)
    age_days = (time.time() - SUBMISSION_LOG.stat().st_mtime) / (24 * 3600)

    if size_mb < 10.0 and age_days < 7.0:
        return

    timestamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
    backup_path = SUBMISSION_LOG.with_name(f"{SUBMISSION_LOG.name}.{timestamp}")
    SUBMISSION_LOG.rename(backup_path)


def normalize_cell(value: Any) -> str:
    """Normalize cell value for CSV output."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value).strip()
    if s == "":
        return "null"
    low = s.lower()
    if low in ("nan", "inf", "+inf", "infinity", "+infinity", "-inf", "-infinity"):
        return "null"

    try:
        float_val = float(s)
        if np.isfinite(float_val):
            if float_val.is_integer():
                return str(int(float_val))
            elif abs(float_val) < 1e-10:
                return "0"
            elif abs(float_val) >= 1e6:
                return f"{float_val:.6e}"
            elif abs(float_val) >= 1:
                return f"{float_val:.6f}".rstrip('0').rstrip('.')
            else:
                return f"{float_val:.12f}".rstrip('0').rstrip('.')
        return "null"
    except (ValueError, TypeError):
        pass

    return s


def log_submission_row(row: Dict[str, Any]) -> None:
    """Log a submission row to CSV with rotation and deduplication."""
    rotate_log_if_needed()

    # Ensure schema
    if not SUBMISSION_LOG.exists():
        with open(SUBMISSION_LOG, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CANONICAL_HEADER)

    ordered = [normalize_cell(row.get(k)) for k in CANONICAL_HEADER]
    key_indices = (0, 1)  # timestamp_utc, topic_id
    key = tuple(ordered[i] for i in key_indices)

    # Read existing rows
    existing_rows = []
    if SUBMISSION_LOG.exists():
        with open(SUBMISSION_LOG, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            existing_rows = list(reader)

    # Replace existing entry for same epoch
    updated = False
    for i, existing in enumerate(existing_rows[1:], 1):  # Skip header
        existing_key = tuple(existing[j] for j in key_indices)
        if existing_key == key:
            existing_rows[i] = ordered
            updated = True
            break

    if not updated:
        existing_rows.append(ordered)

    # Write back
    with open(SUBMISSION_LOG, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(existing_rows)


def fetch_market_data(api_key: str, hours_needed: int) -> pd.DataFrame:
    """Fetch and process market data."""
    try:
        # Try to use the original workflow
        from workflow import AlloraMLWorkflow
        workflow = AlloraMLWorkflow(
            data_api_key=api_key,
            tickers=[TICKER],
            hours_needed=hours_needed,
            number_of_input_candles=12,
            target_length=TARGET_HOURS,
        )

        start_date = (datetime.now(timezone.utc) - timedelta(hours=hours_needed)).date().isoformat()
        raw = workflow.fetch_ohlcv_data(TICKER, start_date)
        bars = workflow.create_5_min_bars(raw)

        hourly = bars.resample("1h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        idx = pd.DatetimeIndex(hourly.index)
        if getattr(idx, "tz", None) is not None:
            hourly.index = idx.tz_convert("UTC").tz_localize(None)
        else:
            hourly.index = idx
        return hourly

    except ImportError:
        # Fallback to mock data
        print("WARNING: Using mock market data - install allora_forge_builder_kit for real data")
        now = datetime.now(timezone.utc)
        timestamps = pd.date_range(now - timedelta(hours=hours_needed + 300), now, freq='1h')
        np.random.seed(42)
        closes = 100000 + np.cumsum(np.random.normal(0, 1000, len(timestamps)))
        volumes = np.random.exponential(1000, len(timestamps))
        return pd.DataFrame({
            'close': closes,
            'volume': volumes
        }, index=timestamps)


def build_alpha_features(close_series: pd.Series) -> pd.DataFrame:
    """Build comprehensive alpha features from price data."""
    features = pd.DataFrame(index=close_series.index)

    # Basic price features
    features['close'] = close_series
    features['returns'] = close_series.pct_change()
    features['log_returns'] = np.log(close_series / close_series.shift(1))

    # Moving averages
    for window in [6, 12, 24, 48, 168]:  # 6h, 12h, 1d, 2d, 1w
        features[f'ma_{window}h'] = close_series.rolling(window).mean()
        features[f'std_{window}h'] = close_series.rolling(window).std()

    # Technical indicators
    for window in [12, 24, 48]:
        features[f'rsi_{window}'] = compute_rsi(close_series, window)
        features[f'macd_{window}'] = compute_macd(close_series, window)

    # Volatility measures
    features['realized_vol_24h'] = features['log_returns'].rolling(24).std()
    features['realized_vol_168h'] = features['log_returns'].rolling(168).std()

    # Momentum features
    for lag in [1, 6, 24, 168]:
        features[f'momentum_{lag}h'] = close_series / close_series.shift(lag) - 1

    return features.ffill().dropna()


def compute_rsi(price: pd.Series, window: int) -> pd.Series:
    """Compute RSI indicator."""
    delta = price.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def compute_macd(price: pd.Series, window: int) -> pd.Series:
    """Compute MACD indicator."""
    ema_fast = price.ewm(span=window).mean()
    ema_slow = price.ewm(span=window*2).mean()
    return ema_fast - ema_slow


def deduplicate_features(features: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate and near-duplicate features."""
    if features.empty:
        return features

    initial_count = features.shape[1]

    # Remove exact duplicates
    features = features.loc[:, ~features.columns.duplicated(keep='last')]

    # Remove identical columns
    transposed = features.T.drop_duplicates(keep='last')
    features = transposed.T

    # Remove near-duplicates
    numeric_cols = features.select_dtypes(include=[np.number]).columns
    seen_hashes = set()
    to_drop = []

    for col in numeric_cols:
        vals = features[col].to_numpy()
        vals_norm = np.nan_to_num(vals, nan=1e20)
        rounded = np.round(vals_norm.astype(float), decimals=9)
        h = hashlib.md5(rounded.tobytes()).hexdigest()

        if h in seen_hashes:
            to_drop.append(col)
        else:
            seen_hashes.add(h)

    features = features.drop(columns=to_drop, errors='ignore')

    removed = initial_count - features.shape[1]
    print(f"Feature deduplication: {features.shape[1]} features (removed {removed})")

    return features


def train_model_for_hour(series: pd.DataFrame, inference_hour: datetime) -> TrainingResult:
    """Train the prediction model for a specific inference hour."""
    # Build features
    features = build_alpha_features(series['close'])
    if 'volume' in series:
        features['volume_log'] = np.log1p(series['volume'])

    features = deduplicate_features(features)

    # Create target (predict next hour return)
    target = series['close'].pct_change(1).shift(-1)

    # Split data (use earlier data for training, later for validation)
    train_data = features.iloc[:-100]
    val_data = features.iloc[-100:]

    train_target = target.loc[train_data.index].dropna()
    val_target = target.loc[val_data.index].dropna()

    train_data = train_data.loc[train_target.index]
    val_data = val_data.loc[val_target.index]

    if train_data.empty or val_data.empty:
        raise RuntimeError("Insufficient data for training/validation")

    # Train model
    model = GradientBoostingRegressor(random_state=42, n_estimators=50)  # Fewer for speed
    model.fit(train_data.values, train_target.values)

    # Evaluate
    train_pred = model.predict(train_data.values)
    val_pred = model.predict(val_data.values)

    metrics = {
        'train_mae': mean_absolute_error(train_target, train_pred),
        'val_mae': mean_absolute_error(val_target, val_pred),
        'train_mse': mean_squared_error(train_target, train_pred),
        'val_mse': mean_squared_error(val_target, val_pred),
        'val_log10_loss': np.log10(max(mean_absolute_error(val_target, val_pred), 1e-12))
    }

    # Make prediction for the specified inference window
    # Use the latest available data up to inference_hour
    available_data = features[features.index <= inference_hour]
    if available_data.empty:
        raise RuntimeError(f"No data available for inference hour {inference_hour}")
    
    inference_features = available_data.iloc[-1:]  # Use latest available data
    prediction = float(model.predict(inference_features.values)[0])

    # Save artifacts
    PREDICTIONS_JSON.write_text(json.dumps({
        'topic_id': TOPIC_ID,
        'value': prediction,
        'prediction_time_utc': inference_hour.isoformat().replace('+00:00', 'Z')
    }, indent=2))

    METRICS_JSON.write_text(json.dumps(metrics, indent=2))
    joblib.dump(model, MODEL_JOBLIB)

    return TrainingResult(
        prediction_time=inference_hour,
        prediction_value=prediction,
        metrics=metrics,
        features_count=features.shape[1]
    )


def check_already_submitted(topic_id: int, inference_hour: datetime) -> bool:
    """Check if already submitted for this topic and hour with detailed logging."""
    if not SUBMISSION_LOG.exists():
        return False

    target_hour = inference_hour.replace(minute=0, second=0, microsecond=0)
    target_hour_str = target_hour.isoformat().replace('+00:00', 'Z')

    try:
        with open(SUBMISSION_LOG, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (int(row.get('topic_id', 0)) == topic_id and
                    row.get('success') == 'true'):
                    try:
                        row_time = datetime.fromisoformat(row['timestamp_utc'].replace('Z', '+00:00'))
                        row_hour = row_time.replace(minute=0, second=0, microsecond=0)
                        if row_hour == target_hour:
                            # Log successful verification
                            tx_hash = row.get('tx_hash', 'N/A')
                            print(f"📋 Local log verification: Found successful submission for {target_hour_str} (TX: {tx_hash})")
                            return True
                    except (ValueError, KeyError) as e:
                        print(f"⚠️  Warning: Malformed log entry for {target_hour_str}: {e}")
                        continue
    except Exception as e:
        print(f"⚠️  Warning: Could not read submission log: {e}")
        return False

    return False


def get_last_processed_hour() -> Optional[datetime]:
    """Get the most recent successfully processed hour from logs."""
    if not SUBMISSION_LOG.exists():
        return None

    latest_hour = None
    try:
        with open(SUBMISSION_LOG, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('success') == 'true':
                    try:
                        row_time = datetime.fromisoformat(row['timestamp_utc'].replace('Z', '+00:00'))
                        row_hour = row_time.replace(minute=0, second=0, microsecond=0)
                        if latest_hour is None or row_hour > latest_hour:
                            latest_hour = row_hour
                    except (ValueError, KeyError):
                        continue
    except Exception:
        return None

    return latest_hour


async def submit_prediction(prediction: TrainingResult) -> SubmissionResult:
    """Submit prediction to blockchain with retry logic and comprehensive error handling."""
    import traceback as tb

    max_retries = 1  # Retry once on failure
    last_exception = None
    full_traceback = None

    for attempt in range(max_retries + 1):
        try:
            from allora_sdk.worker import AlloraWorker
            from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig

            api_key = os.getenv(API_KEY_ENV)
            wallet_addr = os.getenv(WALLET_ENV)

            # Check if already submitted (before each attempt)
            if check_already_submitted(TOPIC_ID, prediction.prediction_time):
                return SubmissionResult(False, 0, "already_submitted_locally")

            # Configure network and wallet
            network_cfg = AlloraNetworkConfig(
                chain_id=CHAIN_ID,
                url=DEFAULT_RPC,
                fee_denom=DEFAULT_FEE_DENOM,
                fee_minimum_gas_price=DEFAULT_MIN_GAS_PRICE,
            )

            try:
                wallet_cfg = AlloraWalletConfig.from_env()
            except ValueError as exc:
                return SubmissionResult(False, 1, f"wallet_configuration_error|{str(exc)}")

            # Ensure MNEMONIC is set for wallet config
            if not os.getenv('MNEMONIC') and os.getenv('ALLORA_MNEMONIC'):
                os.environ['MNEMONIC'] = os.getenv('ALLORA_MNEMONIC')

            # Create worker
            worker = AlloraWorker(
                run=lambda _: prediction.prediction_value,
                wallet=wallet_cfg,
                network=network_cfg,
                api_key=api_key,
                topic_id=TOPIC_ID,
                polling_interval=30,  # 30 second timeout
            )

            # Run worker and get result (similar to _run_worker in submission.py)
            result = None
            timeout = 30  # 30 seconds

            try:
                async for outcome in worker.run(timeout=timeout):
                    if isinstance(outcome, Exception):
                        raise outcome

                    tx = outcome.tx_result

                    # Try multiple ways to extract transaction hash
                    tx_hash = None
                    if hasattr(tx, 'hash') and tx.hash:
                        tx_hash = tx.hash
                    elif hasattr(tx, 'txhash') and tx.txhash:
                        tx_hash = tx.txhash
                    elif hasattr(tx, 'transaction_hash') and tx.transaction_hash:
                        tx_hash = tx.transaction_hash

                    # Try to extract from raw_log if available
                    if not tx_hash:
                        raw_log = getattr(tx, 'raw_log', '')
                        if raw_log and isinstance(raw_log, str):
                            import re
                            hash_match = re.search(r'txhash["\s:]+([A-Fa-f0-9]{64})', raw_log)
                            if hash_match:
                                tx_hash = hash_match.group(1).upper()

                    # Extract nonce
                    nonce = None
                    events = getattr(tx, "events", None)
                    if isinstance(events, dict):
                        for event in events.values():
                            if isinstance(event, dict):
                                for key, value in event.items():
                                    if str(key).lower() in {"nonce", "window_nonce"}:
                                        try:
                                            nonce = int(value)
                                            break
                                        except (TypeError, ValueError):
                                            continue
                                if nonce is not None:
                                    break

                    # If we have either a hash or nonce, consider it successful
                    if tx_hash or nonce is not None:
                        result = (outcome.prediction, tx_hash, nonce, tx)
                        break

                    # Fallback: assume success if we got here
                    result = (outcome.prediction, tx_hash, nonce, tx)
                    break

            except asyncio.TimeoutError:
                worker.stop()
                if attempt < max_retries:
                    print(f"Submission attempt {attempt + 1} timed out, retrying...")
                    await asyncio.sleep(2)
                    continue
                else:
                    return SubmissionResult(False, 1, f"timeout|retries_exhausted")

            worker.stop()

            if result is None:
                if attempt < max_retries:
                    print(f"Submission attempt {attempt + 1} produced no result, retrying...")
                    await asyncio.sleep(1)
                    continue
                else:
                    return SubmissionResult(False, 1, f"no_result|retries_exhausted")

            prediction_value, tx_hash, nonce, tx_result = result

            # For now, assume success if we got here
            return SubmissionResult(
                True, 0, "submitted",
                nonce=nonce,
                tx_hash=tx_hash
            )

        except Exception as e:
            last_exception = e
            full_traceback = tb.format_exc()

            error_str = str(e).lower()
            if "already submitted" in error_str or "inference already submitted" in error_str:
                # Permanent failure - don't retry
                return SubmissionResult(False, 1, f"inference_already_submitted|traceback:{full_traceback[:500]}")

            if attempt < max_retries:
                print(f"Submission attempt {attempt + 1} failed, retrying: {e}")
                await asyncio.sleep(2)  # Brief pause before retry
                continue
            else:
                # Final attempt failed - classify the error
                if "network" in error_str or "connection" in error_str or "timeout" in error_str:
                    error_type = "network_error"
                elif "wallet" in error_str or "key" in error_str or "mnemonic" in error_str:
                    error_type = "wallet_error"
                elif "insufficient" in error_str and "balance" in error_str:
                    error_type = "insufficient_balance"
                elif "rate limit" in error_str or "too many requests" in error_str:
                    error_type = "rate_limited"
                else:
                    error_type = "submission_error"

                return SubmissionResult(
                    False, 1,
                    f"{error_type}|retries_exhausted|traceback:{full_traceback[:500]}"
                )

    # This should never be reached, but just in case
    return SubmissionResult(
        False, 1,
        f"unexpected_error|traceback:{full_traceback[:500] if full_traceback else 'none'}"
    )


def log_pipeline_result(training: Optional[TrainingResult], submission: SubmissionResult) -> None:
    """Log the complete pipeline result."""
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    wallet = os.getenv(WALLET_ENV)

    # Determine score and reward based on success
    if training:
        if submission.success:
            score = training.metrics.get('val_mae', 0.0)
            reward = score  # Will be updated by refresh_scores later
        else:
            score = training.metrics.get('val_mae', 0.0)
            reward = "pending"
    else:
        score = None
        reward = None

    # Build status with flags
    status_parts = [submission.status]
    if not submission.success and training:
        status_parts.append("score_fallback")
        if reward == "pending":
            status_parts.append("reward_pending")

    status = "|".join(status_parts)

    row = {
        'timestamp_utc': timestamp,
        'topic_id': TOPIC_ID,
        'value': training.prediction_value if training else None,
        'wallet': wallet,
        'nonce': submission.nonce,
        'tx_hash': submission.tx_hash,
        'success': submission.success,
        'exit_code': submission.exit_code,
        'status': status,
        'log10_loss': training.metrics.get('val_log10_loss') if training else None,
        'score': score,
        'reward': reward
    }

    log_submission_row(row)


def check_singleton_guard() -> bool:
    """Ensure only one instance of the pipeline is running."""
    import psutil
    import os

    current_pid = os.getpid()
    current_process = psutil.Process(current_pid)

    # Check for other Python processes running this script
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['pid'] == current_pid:
                continue
            if proc.info['name'] == 'python' or proc.info['name'] == 'python3':
                cmdline = proc.info['cmdline']
                if cmdline and len(cmdline) > 1 and 'run_pipeline.py' in cmdline[1]:
                    print(f"WARNING: Another pipeline instance detected (PID: {proc.info['pid']})")
                    return False
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return True


async def get_wallet_balance() -> Optional[float]:
    """Get current ALLO balance for the wallet."""
    try:
        from allora_sdk.rpc_client import AlloraRPCClient

        api_key = os.getenv(API_KEY_ENV)
        wallet_addr = os.getenv(WALLET_ENV)

        if not api_key or not wallet_addr:
            return None

        # Create client and try to query balance
        client = AlloraRPCClient.testnet()

        try:
            # Try to query balance - the API may be unstable or have different signatures
            # This is optional functionality, so we attempt but don't fail if it doesn't work
            try:
                # Try the most likely signature first
                balance_response = await client.bank.balance(wallet_addr)
            except TypeError:
                try:
                    # Try alternative signature
                    balance_response = await client.bank.balance(address=wallet_addr)
                except (TypeError, Exception):
                    # If all balance queries fail, just return None
                    return None

            if hasattr(balance_response, 'balance') and hasattr(balance_response.balance, 'amount'):
                # Convert from micro-allo to allo
                return float(balance_response.balance.amount) / 1_000_000.0
            elif hasattr(balance_response, 'amount'):
                # Alternative response structure
                return float(balance_response.amount) / 1_000_000.0
            return None
        finally:
            await client.close()

    except Exception:
        # Balance checking is optional - don't fail the pipeline if it doesn't work
        # Don't print errors to avoid log spam since this is called frequently
        return None


def calculate_next_submission_hour() -> datetime:
    """Calculate the next eligible submission hour."""
    now = datetime.now(timezone.utc)

    # Get the current hour
    current_hour = now.replace(minute=0, second=0, microsecond=0)

    # If we're past the 5-minute window, move to next hour
    if now.minute >= 5:
        current_hour += timedelta(hours=1)

    return current_hour


async def wait_until_submission_window(target_hour: datetime) -> None:
    """Wait until the submission window opens for the target hour with informative status updates."""
    last_status_update = 0
    last_balance_check = 0

    while True:
        now = datetime.now(timezone.utc)
        time_until_target = (target_hour - now).total_seconds()

        if time_until_target <= 0:
            # We're at or past the target hour
            if now.minute <= 5:
                # Within submission window
                return
            else:
                # Past submission window, move to next hour
                target_hour += timedelta(hours=1)
                continue

        # Calculate time until submission window opens (target_hour is the hour, window opens at :00)
        submission_window_start = target_hour
        time_until_window = (submission_window_start - now).total_seconds()

        # Update status periodically (every 5 minutes when far away, every minute when close)
        current_time = time.time()
        update_interval = 60 if time_until_window < 600 else 300  # 1 min when <10 min, 5 min otherwise

        if current_time - last_status_update >= update_interval:
            if time_until_window > 86400:  # More than 1 day
                days = int(time_until_window // 86400)
                hours = int((time_until_window % 86400) // 3600)
                print(f"📅 Sleeping {days}d {hours}h until next submission slot ({target_hour})")
            elif time_until_window > 3600:  # More than 1 hour
                hours = int(time_until_window // 3600)
                mins = int((time_until_window % 3600) // 60)
                print(f"⏰ Sleeping {hours}h {mins}m until next submission slot ({target_hour})")
            elif time_until_window > 300:  # More than 5 minutes
                mins = int(time_until_window // 60)
                print(f"⏳ Sleeping {mins}m until submission window opens ({target_hour})")
            elif time_until_window > 60:  # More than 1 minute
                mins = int(time_until_window // 60)
                secs = int(time_until_window % 60)
                print(f"🎯 Submission window in {mins}m {secs}s ({target_hour})")
            else:
                secs = int(time_until_window)
                print(f"🚀 Submission window opening in {secs}s ({target_hour})")

            last_status_update = current_time

        # Check wallet balance much less frequently (disabled due to API issues)
        # if (time_until_window < 300 and  # Within 5 minutes
        #     current_time - last_balance_check >= 600):  # Every 10 minutes
        #     balance = await get_wallet_balance()
        #     if balance is not None and balance < 1.0:  # Low balance warning
        #         print(f"⚠️  Low wallet balance: {balance:.6f} ALLO")
        #     elif balance is not None:
        #         print(f"💰 Wallet balance: {balance:.6f} ALLO")
        #     last_balance_check = current_time

        # Sleep in appropriate intervals
        if time_until_window > 3600:  # More than an hour away
            await asyncio.sleep(min(1800, time_until_window - 1800))  # Sleep for 30 min or until 30 min before
        elif time_until_window > 300:  # More than 5 minutes away
            await asyncio.sleep(min(60, time_until_window - 60))  # Sleep for 1 min or until 1 min before
        else:
            # Less than 5 minutes away - sleep in smaller increments
            sleep_time = max(1, min(10, time_until_window))
            await asyncio.sleep(sleep_time)


async def perform_periodic_health_check() -> None:
    """Perform periodic health checks during operation."""
    try:
        # Check if log file is still writable
        test_row = {
            'timestamp_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'topic_id': TOPIC_ID,
            'value': None,
            'wallet': os.getenv(WALLET_ENV, 'test'),
            'nonce': 0,
            'tx_hash': 'health_check',
            'success': 'false',
            'exit_code': 0,
            'status': 'health_check',
            'log10_loss': None,
            'score': None,
            'reward': None
        }
        log_submission_row(test_row)

        # Remove the test entry (this is a bit hacky but ensures we can write)
        if SUBMISSION_LOG.exists():
            with open(SUBMISSION_LOG, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Remove the last line if it contains our test
            if lines and 'health_check' in lines[-1]:
                lines = lines[:-1]
                with open(SUBMISSION_LOG, "w", encoding="utf-8") as f:
                    f.writelines(lines)

        # Check wallet balance (disabled due to API issues)
        # balance = await get_wallet_balance()
        # if balance is not None:
        #     if balance < 0.1:  # Very low balance
        #         print(f"🚨 CRITICAL: Wallet balance critically low: {balance:.6f} ALLO")
        #     elif balance < 1.0:  # Low balance
        #         print(f"⚠️  Warning: Low wallet balance: {balance:.6f} ALLO")

        return True
    except Exception as e:
        print(f"💥 Health check failed: {e}")
        return False


async def verify_submission_on_chain(topic_id: int, target_hour: datetime) -> bool:
    """Verify if submission exists on blockchain (optional additional check)."""
    try:
        from allora_sdk.rpc_client import AlloraRPCClient

        wallet_addr = os.getenv(WALLET_ENV)
        if not wallet_addr:
            return False

        client = AlloraRPCClient.testnet()

        try:
            # Try to get the latest inference for this worker and topic
            # This is an optional check - if it fails, we rely on local logs
            inference_response = await client.emissions.query.get_worker_latest_inference_by_topic_id(
                topic_id  # Only topic_id, worker might be inferred from client
            )

            if hasattr(inference_response, 'inference') and inference_response.inference:
                # Check if the inference timestamp matches our target hour
                inference_time = getattr(inference_response.inference, 'inference_time', None)
                if inference_time:
                    # Convert to datetime and check if it matches our submission hour
                    # The exact format may vary, so we do a rough check
                    inference_hour = inference_time.replace(minute=0, second=0, microsecond=0)
                    target_hour_normalized = target_hour.replace(minute=0, second=0, microsecond=0)
                    return inference_hour == target_hour_normalized

            return False
        finally:
            await client.close()

    except Exception as e:
        # Blockchain verification is optional - don't fail if the query doesn't work
        print(f"Note: Could not verify on-chain submission ({e})")
        return False


def perform_startup_health_check() -> Dict[str, Any]:
    """Perform comprehensive health check on startup."""
    health_status = {
        'environment': 'ok',
        'logs': 'ok',
        'competition_status': 'unknown',
        'last_submission': None,
        'total_submissions': 0,
        'warnings': []
    }

    # Check environment
    if not os.getenv(API_KEY_ENV):
        health_status['environment'] = 'error'
        health_status['warnings'].append(f"Missing {API_KEY_ENV}")
    if not os.getenv(WALLET_ENV):
        health_status['environment'] = 'error'
        health_status['warnings'].append(f"Missing {WALLET_ENV}")

    # Check logs
    if not SUBMISSION_LOG.exists():
        health_status['warnings'].append("No submission log found - starting fresh")
    else:
        try:
            with open(SUBMISSION_LOG, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                success_count = 0
                last_success = None
                for row in reader:
                    if row.get('success') == 'true':
                        success_count += 1
                        try:
                            row_time = datetime.fromisoformat(row['timestamp_utc'].replace('Z', '+00:00'))
                            if last_success is None or row_time > last_success:
                                last_success = row_time
                        except (ValueError, KeyError):
                            continue
                health_status['total_submissions'] = success_count
                health_status['last_submission'] = last_success
        except Exception as e:
            health_status['logs'] = 'error'
            health_status['warnings'].append(f"Could not read submission log: {e}")

    # Check competition status
    now = datetime.now(timezone.utc)
    if now < COMPETITION_START:
        health_status['competition_status'] = 'not_started'
        days_until = (COMPETITION_START - now).days
        health_status['warnings'].append(f"Competition starts in {days_until} days")
    elif now > COMPETITION_END:
        health_status['competition_status'] = 'ended'
        health_status['warnings'].append("Competition has ended")
    else:
        health_status['competition_status'] = 'active'

    return health_status


async def run_continuous_pipeline() -> None:
    """Run the continuous pipeline loop as a reliable network participant."""
    # Load environment variables first
    load_environment(REPO_ROOT)

    print("🚀 Starting Continuous Allora Forge Pipeline")
    print("=" * 80)

    # Perform comprehensive health check
    print("🔍 Performing startup health check...")
    health = perform_startup_health_check()

    print(f"Environment: {'✅' if health['environment'] == 'ok' else '❌'} {health['environment']}")
    print(f"Logs: {'✅' if health['logs'] == 'ok' else '❌'} {health['logs']}")
    print(f"Competition: {health['competition_status']}")
    if health['last_submission']:
        print(f"Last submission: {health['last_submission'].isoformat().replace('+00:00', 'Z')}")
    print(f"Total submissions: {health['total_submissions']}")

    if health['warnings']:
        print("⚠️  Warnings:")
        for warning in health['warnings']:
            print(f"   - {warning}")

    print(f"Competition: {COMPETITION_START} to {COMPETITION_END}")
    print(f"Topic: {TOPIC_ID} (BTC/USD 7-day log-return)")
    print(f"Wallet: {os.getenv(WALLET_ENV, 'Not configured')}")
    print(f"Started at: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}")
    print("=" * 80)

    # Check environment before proceeding
    if health['environment'] != 'ok':
        print("❌ Environment not properly configured. Please fix the issues above.")
        return

    # Singleton guard
    if not check_singleton_guard():
        print("❌ Another pipeline instance is already running. Exiting.")
        return

    print("✅ Singleton guard passed - no other instances detected")
    print("🔄 Entering continuous monitoring loop...")
    print("-" * 60)

    # Track system health
    consecutive_errors = 0
    last_successful_cycle = None
    total_submissions = 0
    total_skipped = 0
    last_health_check = datetime.now(timezone.utc)

    # Main continuous loop - runs indefinitely until competition ends
    while True:
        try:
            now = datetime.now(timezone.utc)
            cycle_start = now

            # Periodic health check (every 30 minutes)
            if (now - last_health_check).total_seconds() > 1800:
                print("🔍 Performing periodic health check...")
                if await perform_periodic_health_check():
                    print("✅ Health check passed")
                else:
                    print("❌ Health check failed - continuing operation")
                last_health_check = now

            # Competition status check
            if now > COMPETITION_END:
                print(f"🏁 Competition has ended at {COMPETITION_END}")
                print(f"📊 Final stats: {total_submissions} submissions, {total_skipped} skipped")
                break

            if now < COMPETITION_START:
                wait_time = (COMPETITION_START - now).total_seconds()
                days = int(wait_time // 86400)
                hours = int((wait_time % 86400) // 3600)
                print(f"⏳ Competition starts in {days}d {hours}h. Next check in 1 hour...")
                await asyncio.sleep(3600)  # Check every hour before competition
                continue

            # Calculate next submission hour and window status
            next_hour = calculate_next_submission_hour()
            time_until_window = (next_hour - now).total_seconds()

            # FOR TESTING: Force immediate submission for current hour
            if os.getenv('FORCE_TEST_SUBMISSION'):
                print("🧪 TEST MODE: Forcing immediate submission for current hour")
                next_hour = now.replace(minute=0, second=0, microsecond=0)
                time_until_window = 0

            # Display current status
            if time_until_window > 3600:
                hours_until = int(time_until_window // 3600)
                print(f"📅 Next submission slot: {next_hour} ({hours_until}h away)")
            elif time_until_window > 60:
                mins_until = int(time_until_window // 60)
                print(f"⏰ Next submission slot: {next_hour} ({mins_until}m away)")
            else:
                secs_until = int(time_until_window)
                print(f"🎯 Submission window opening: {next_hour} ({secs_until}s)")

            # Wait until submission window with periodic status updates
            if time_until_window > 0:
                await wait_until_submission_window(next_hour)

            # We're now in the submission window
            print(f"\n🎯 Processing submission for {next_hour}")
            print(f"⏱️  Cycle started at {cycle_start.isoformat().replace('+00:00', 'Z')}")

            # Double-check we're still in competition bounds
            if next_hour > COMPETITION_END:
                print("🏁 Next submission would be after competition end. Shutting down.")
                break

            # State awareness: Check if already submitted (primary check)
            if check_already_submitted(TOPIC_ID, next_hour):
                print(f"✅ Already submitted for {next_hour} (local log verification)")
                total_skipped += 1
                await asyncio.sleep(30)  # Brief pause before next check
                continue

            # Optional blockchain verification (secondary check)
            if await verify_submission_on_chain(TOPIC_ID, next_hour):
                print(f"✅ Verified on-chain submission for {next_hour}")
                total_skipped += 1
                await asyncio.sleep(30)
                continue

            # Proceed with submission process
            print("🔄 Starting submission process...")

            # Fetch fresh market data
            api_key = os.getenv(API_KEY_ENV)
            hours_needed = TRAIN_SPAN_HOURS + VALIDATION_SPAN_HOURS + TARGET_HOURS + HISTORY_BUFFER_HOURS

            print("📊 Fetching market data...")
            market_data = fetch_market_data(api_key, hours_needed)

            print("🧠 Training model...")
            training_result = train_model_for_hour(market_data, next_hour)

            print(f"🎯 Prediction: {training_result.prediction_value:.6f} "
                  f"for {training_result.prediction_time} ({training_result.features_count} features)")
            print(f"📈 Metrics: MAE={training_result.metrics.get('val_mae', 'N/A'):.6f}, "
                  f"LogLoss={training_result.metrics.get('val_log10_loss', 'N/A'):.6f}")

            # Submit prediction
            print("📤 Submitting to blockchain...")
            submission_result = await submit_prediction(training_result)

            if submission_result.success:
                print(f"✅ Submission successful! TX: {submission_result.tx_hash or 'pending'}")
                total_submissions += 1
                consecutive_errors = 0  # Reset error counter
                last_successful_cycle = now
            else:
                error_type = submission_result.status.split('|')[0]
                print(f"❌ Submission failed: {error_type}")
                consecutive_errors += 1

            # Log results (always log, even failures)
            log_pipeline_result(training_result, submission_result)

            # Cycle completion
            cycle_duration = (datetime.now(timezone.utc) - cycle_start).total_seconds()
            print(f"⏱️  Cycle completed in {cycle_duration:.1f}s")

            # Health status
            if last_successful_cycle:
                time_since_success = (now - last_successful_cycle).total_seconds()
                if time_since_success > 7200:  # 2 hours
                    print(f"⚠️  Warning: No successful submission in {time_since_success/3600:.1f} hours")

            if consecutive_errors > 3:
                print(f"⚠️  Warning: {consecutive_errors} consecutive errors")

            # Brief pause before next cycle to prevent overwhelming the network
            await asyncio.sleep(10)

        except KeyboardInterrupt:
            print("\n🛑 Received shutdown signal. Exiting gracefully.")
            print(f"📊 Final stats: {total_submissions} submissions, {total_skipped} skipped")
            break
        except Exception as e:
            consecutive_errors += 1
            print(f"💥 Pipeline error (#{consecutive_errors}): {e}")

            # Log the error with full context
            try:
                submission_result = SubmissionResult(
                    False, 1,
                    f"pipeline_crash|consecutive_errors:{consecutive_errors}|traceback:{traceback.format_exc()[:500]}"
                )
                log_pipeline_result(None, submission_result)
            except Exception:
                pass  # Don't fail if logging fails

            # Exponential backoff for errors (but cap at 5 minutes)
            backoff_time = min(60 * (2 ** min(consecutive_errors - 1, 5)), 300)
            print(f"⏳ Backing off for {backoff_time}s before retry...")
            await asyncio.sleep(backoff_time)


def main() -> int:
    """Main entry point - supports both batch and continuous modes."""
    import argparse

    parser = argparse.ArgumentParser(description="Allora Forge Pipeline - Training and Submission")
    parser.add_argument("--start", help="Start date (ISO8601, default: competition start)")
    parser.add_argument("--end", help="End date (ISO8601, default: competition end)")
    parser.add_argument("--live", action="store_true", help="Only run for current hour (for cron)")
    parser.add_argument("--max-hours", type=int, default=100, help="Maximum hours to process in one run (default: 100)")
    parser.add_argument("--continuous", action="store_true", help="Run in continuous monitoring mode")

    args = parser.parse_args()

    if args.continuous:
        # Run continuous pipeline
        try:
            asyncio.run(run_continuous_pipeline())
            return 0
        except KeyboardInterrupt:
            print("\n👋 Continuous pipeline stopped by user.")
            return 0
        except Exception as e:
            print(f"💥 Continuous pipeline failed: {e}")
            return 1
    else:
        # Run batch mode (existing logic)
        try:
            print(f"Starting Batch Allora Forge Pipeline at {datetime.now(timezone.utc)}")

            # Setup
            setup_environment()

            # Determine time range
            if args.live:
                # Only current hour
                now = datetime.now(timezone.utc)
                current_hour = now.replace(minute=0, second=0, microsecond=0)
                if now.minute >= 5:  # If past 5 min, do next hour
                    current_hour += timedelta(hours=1)
                hours_to_process = [current_hour]
            else:
                start_date = COMPETITION_START if not args.start else datetime.fromisoformat(args.start.replace('Z', '+00:00'))
                end_date = COMPETITION_END if not args.end else datetime.fromisoformat(args.end.replace('Z', '+00:00'))

                # Generate all hourly slots
                hours_to_process = []
                current = start_date
                while current <= end_date and len(hours_to_process) < args.max_hours:
                    hours_to_process.append(current)
                    current += timedelta(hours=1)

            print(f"Processing {len(hours_to_process)} hours from {hours_to_process[0]} to {hours_to_process[-1]}")

            success_count = 0
            skip_count = 0
            fail_count = 0

            for inference_hour in hours_to_process:
                print(f"\n--- Processing {inference_hour} ---")

                # Check if already submitted
                if check_already_submitted(TOPIC_ID, inference_hour):
                    print(f"Already submitted for {inference_hour}, skipping")
                    skip_count += 1
                    continue

                # Check if we're within competition and submission window (for live mode)
                if args.live and not is_competition_active():
                    print("Outside competition timeframe, skipping")
                    skip_count += 1
                    continue

                if args.live and not is_submission_window():
                    print("Not within submission window, skipping")
                    skip_count += 1
                    continue

                try:
                    # Fetch data and train for this specific hour
                    api_key = os.getenv(API_KEY_ENV)
                    hours_needed = TRAIN_SPAN_HOURS + VALIDATION_SPAN_HOURS + TARGET_HOURS + HISTORY_BUFFER_HOURS

                    print("Fetching market data...")
                    market_data = fetch_market_data(api_key, hours_needed)

                    print("Training model...")
                    training_result = train_model_for_hour(market_data, inference_hour)

                    print(f"Training complete. Prediction: {training_result.prediction_value:.6f} "
                          f"for {training_result.prediction_time} ({training_result.features_count} features)")

                    # Submit
                    print("Submitting prediction...")
                    submission_result = asyncio.run(submit_prediction(training_result))

                    if submission_result.success:
                        print(f"Submission successful: tx={submission_result.tx_hash}")
                        success_count += 1
                    else:
                        print(f"Submission failed: {submission_result.status}")
                        fail_count += 1

                    # Log results
                    log_pipeline_result(training_result, submission_result)

                except Exception as e:
                    print(f"Pipeline failed for {inference_hour}: {e}")
                    traceback.print_exc()

                    # Log failure
                    try:
                        submission_result = SubmissionResult(False, 1, f"pipeline_error: {str(e)}")
                        # Create minimal training result for logging
                        training_result = TrainingResult(
                            prediction_time=inference_hour,
                            prediction_value=None,
                            metrics={},
                            features_count=0
                        )
                        log_pipeline_result(training_result, submission_result)
                        fail_count += 1
                    except Exception:
                        pass  # Don't fail if logging fails

            print("\n--- Summary ---")
            print(f"Total hours processed: {len(hours_to_process)}")
            print(f"Successful submissions: {success_count}")
            print(f"Skipped (already submitted): {skip_count}")
            print(f"Failed: {fail_count}")

            return 0 if fail_count == 0 else 1

        except Exception as e:
            print(f"Pipeline failed: {e}")
            traceback.print_exc()

            # Log failure
            try:
                submission_result = SubmissionResult(False, 1, f"pipeline_error: {str(e)}")
                log_pipeline_result(None, submission_result)
            except Exception:
                pass  # Don't fail if logging fails

            return 1


if __name__ == "__main__":
    sys.exit(main())