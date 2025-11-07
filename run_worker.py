#!/usr/bin/env python3
"""
Production Allora Worker for Topic 67 - BTC/USD 7-day Log-Return

This script runs a continuous worker that responds to network submission windows.
Unlike the batch pipeline, this worker doesn't try to force submissions - it waits
for the Allora network to open submission windows and provides predictions when requested.

The worker:
- Runs indefinitely (daemon mode)
- Responds to network submission window events
- Uses trained model artifacts or trains on-demand
- Maintains comprehensive logging
- Enforces singleton operation (one worker per topic)
- Handles errors gracefully with automatic recovery

Usage:
    python run_worker.py                    # Start worker in continuous mode
    python run_worker.py --debug           # Enable debug logging
    python run_worker.py --polling 60      # Custom polling interval (seconds)

Environment Variables Required:
    MNEMONIC: Wallet mnemonic for signing transactions
    ALLORA_API_KEY: API key for market data (optional, for backfill)
    TIINGO_API_KEY: Tiingo API key for market data
"""

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import psutil
import requests

# Allora SDK
from allora_sdk.rpc_client import AlloraRPCClient
from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig
from allora_sdk.worker.worker import AlloraWorker

# Configuration
TOPIC_ID = 67
TICKER = "btcusd"
TARGET_HOURS = 168  # 7 days
TRAIN_SPAN_HOURS = 336  # 14 days (reduced from 28 to work with available data)
VALIDATION_SPAN_HOURS = 168  # 7 days
HISTORY_BUFFER_HOURS = 48

# Paths
REPO_ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = REPO_ROOT / "data" / "artifacts"
LOGS_DIR = ARTIFACTS_DIR / "logs"
MODEL_PATH = ARTIFACTS_DIR / "model.joblib"
PREDICTIONS_PATH = ARTIFACTS_DIR / "predictions.json"
WORKER_LOG = LOGS_DIR / "worker_continuous.log"

# Competition window
COMPETITION_START = datetime(2025, 9, 16, 13, 0, 0, tzinfo=timezone.utc)
COMPETITION_END = datetime(2025, 12, 15, 13, 0, 0, tzinfo=timezone.utc)

# Network configuration - Lavender Five Testnet
DEFAULT_RPC = "grpc+https://testnet-allora.lavenderfive.com:443"
DEFAULT_WS = "wss://testnet-rpc.lavenderfive.com:443/allora/websocket"
DEFAULT_REST = "https://testnet-rest.lavenderfive.com:443/allora/"
CHAIN_ID = "allora-testnet-1"

# Logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def log_worker_event(event_type: str, message: str, data: Optional[dict] = None):
    """Log worker events to dedicated log file."""
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    log_entry = {
        'timestamp': timestamp,
        'event': event_type,
        'message': message
    }
    if data:
        log_entry['data'] = data
    
    with open(WORKER_LOG, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')
    
    # Also print to console
    icon = {
        'startup': '🚀',
        'shutdown': '🛑',
        'window_open': '🔔',
        'prediction': '🎯',
        'submission': '📤',
        'success': '✅',
        'error': '❌',
        'warning': '⚠️',
        'info': 'ℹ️'
    }.get(event_type, '•')
    
    print(f"{icon} [{timestamp}] {message}")
    if data:
        for key, value in data.items():
            print(f"   {key}: {value}")


def check_singleton_guard() -> bool:
    """Ensure only one worker instance is running."""
    current_pid = os.getpid()
    current_script = str(Path(__file__).resolve())
    
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.info['pid'] == current_pid:
                continue
                
            cmdline = proc.info.get('cmdline')
            if not cmdline:
                continue
            
            # Check if this process is running the same script  
            # Must have python and the exact script path
            has_python = any('python' in str(arg).lower() for arg in cmdline)
            has_script = any(current_script in str(arg) for arg in cmdline)
            
            if has_python and has_script:
                log_worker_event('info', f'Found existing worker process: PID {proc.info["pid"]}')
                return False
                
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    return True


def load_environment():
    """Load environment variables from .env file."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        log_worker_event('error', 'No .env file found', {'path': str(env_file)})
        return False
    
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    
    # Verify required variables
    required = ['MNEMONIC', 'TIINGO_API_KEY']
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        log_worker_event('error', 'Missing required environment variables', 
                        {'missing': missing})
        return False
    
    return True


def fetch_market_data(hours_needed: int) -> pd.DataFrame:
    """Fetch historical market data for training."""
    # Try Allora API first (more complete data)
    allora_api_key = os.getenv('ALLORA_API_KEY')
    if allora_api_key:
        try:
            from allora_forge_builder_kit.workflow import AlloraMLWorkflow
            workflow = AlloraMLWorkflow(
                data_api_key=allora_api_key,
                tickers=[TICKER],
                hours_needed=hours_needed,
                number_of_input_candles=12,
                target_length=TARGET_HOURS,
            )
            
            # Fetch data from sufficient time ago
            start_date = (datetime.now(timezone.utc) - pd.Timedelta(hours=hours_needed + 48)).date().isoformat()
            raw = workflow.fetch_ohlcv_data(TICKER, start_date)
            bars = workflow.create_5_min_bars(raw)
            
            # Resample to hourly
            hourly = bars.resample("1h").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna()
            
            # Ensure timezone-naive index for consistency
            if hasattr(hourly.index, 'tz') and hourly.index.tz is not None:
                hourly.index = hourly.index.tz_convert("UTC").tz_localize(None)
            
            # Rename to match expected schema
            hourly = hourly.rename(columns={'close': 'close'})
            hourly['timestamp'] = hourly.index
            
            log_worker_event('info', f'Fetched {len(hourly)} hours from Allora API')
            return hourly
            
        except Exception as e:
            log_worker_event('warning', f'Allora API fetch failed, falling back to Tiingo: {e}')
    
    # Fallback to Tiingo
    api_key = os.getenv('TIINGO_API_KEY')
    if not api_key:
        raise ValueError("Neither ALLORA_API_KEY nor TIINGO_API_KEY is set")
    
    end_time = datetime.now(timezone.utc)
    start_time = end_time - pd.Timedelta(hours=hours_needed + 24)  # Extra buffer
    
    url = f"https://api.tiingo.com/tiingo/crypto/prices"
    params = {
        'tickers': TICKER,
        'startDate': start_time.strftime('%Y-%m-%d'),
        'endDate': end_time.strftime('%Y-%m-%d'),
        'resampleFreq': '1hour',
        'token': api_key
    }
    
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    if not data or not data[0].get('priceData'):
        raise ValueError("No market data returned from API")
    
    df = pd.DataFrame(data[0]['priceData'])
    df['timestamp'] = pd.to_datetime(df['date']).dt.tz_convert('UTC')
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['close'] = df['close'].astype(float)
    
    log_worker_event('info', f'Fetched {len(df)} hours from Tiingo API')
    return df


def train_model(market_data: pd.DataFrame) -> float:
    """Train XGBoost model and return latest prediction."""
    try:
        from xgboost import XGBRegressor
    except ImportError:
        raise RuntimeError("XGBoost is required. Install with: pip install xgboost")
    from sklearn.metrics import mean_absolute_error
    
    # Calculate log returns
    df = market_data.copy()
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna()
    
    # Feature engineering - using smaller windows to work with available data
    for lag in [1, 2, 3, 6, 12, 24, 48, 72]:
        df[f'lr_lag_{lag}h'] = df['log_return'].shift(lag)
    
    for window in [6, 12, 24, 48, 72]:
        df[f'lr_ma_{window}h'] = df['log_return'].rolling(window).mean()
        df[f'lr_std_{window}h'] = df['log_return'].rolling(window).std()
    
    df = df.dropna()
    
    # Target: 7-day (168h) forward cumulative log return
    df['target_7d'] = df['log_return'].shift(-TARGET_HOURS).rolling(TARGET_HOURS).sum()
    df = df.dropna()
    
    # Adaptive training based on available data
    # With smaller feature windows (max 72h), we need less data
    min_required = 150  # Reduced from 360 to work with available API data
    if len(df) < min_required:
        raise ValueError(f"Insufficient data: {len(df)} < {min_required} (minimum required)")
    
    # Use available data efficiently
    if len(df) >= TRAIN_SPAN_HOURS + VALIDATION_SPAN_HOURS:
        # Full training set available
        train_df = df.iloc[:-VALIDATION_SPAN_HOURS]
        val_df = df.iloc[-VALIDATION_SPAN_HOURS:]
    else:
        # Limited data - use 70/30 split
        split_idx = int(len(df) * 0.7)
        train_df = df.iloc[:split_idx]
        val_df = df.iloc[split_idx:]
        log_worker_event('warning', f'Limited data: using {len(train_df)} train, {len(val_df)} val samples')
    
    feature_cols = [col for col in df.columns 
                   if col.startswith(('lr_lag_', 'lr_ma_', 'lr_std_'))]
    
    X_train = train_df[feature_cols]
    y_train = train_df['target_7d']
    X_val = val_df[feature_cols]
    y_val = val_df['target_7d']
    
    # Train XGBoost model
    model = XGBRegressor(
        random_state=42,
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        objective='reg:squarederror',
        tree_method='hist'
    )
    model.fit(X_train, y_train)
    
    # Validation metrics
    val_pred = model.predict(X_val)
    val_mae = mean_absolute_error(y_val, val_pred)
    
    # Save model
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    
    # Make latest prediction
    latest_features = df[feature_cols].iloc[-1:].values.reshape(1, -1)
    prediction = float(model.predict(latest_features)[0])
    
    # Save prediction artifact
    prediction_data = {
        'prediction_time': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'prediction_value': prediction,
        'topic_id': TOPIC_ID,
        'validation_mae': float(val_mae),
        'features_used': len(feature_cols),
        'training_samples': len(train_df),
        'validation_samples': len(val_df)
    }
    
    with open(PREDICTIONS_PATH, 'w') as f:
        json.dump(prediction_data, f, indent=2)
    
    log_worker_event('prediction', 'Model trained and prediction generated',
                    {'prediction': prediction, 'val_mae': val_mae,
                     'features': len(feature_cols), 'train_samples': len(train_df)})
    
    return prediction


def get_prediction(nonce: int) -> float:
    """
    Prediction function called by AlloraWorker when submission window opens.
    
    Args:
        nonce: Network nonce for this inference request
        
    Returns:
        float: Prediction value for 7-day BTC/USD log-return
    """
    try:
        log_worker_event('window_open', f'Submission window opened (nonce={nonce})')
        
        # Try to load existing model first
        if MODEL_PATH.exists():
            try:
                model = joblib.load(MODEL_PATH)
                
                # Check if we have recent prediction
                if PREDICTIONS_PATH.exists():
                    with open(PREDICTIONS_PATH) as f:
                        pred_data = json.load(f)
                    
                    pred_time = datetime.fromisoformat(
                        pred_data['prediction_time'].replace('Z', '+00:00')
                    )
                    age_hours = (datetime.now(timezone.utc) - pred_time).total_seconds() / 3600
                    
                    # Use cached prediction if less than 1 hour old
                    if age_hours < 1.0:
                        prediction = pred_data['prediction_value']
                        log_worker_event('prediction', 'Using cached prediction',
                                       {'value': prediction, 'age_hours': age_hours})
                        return prediction
            except Exception as e:
                log_worker_event('warning', f'Could not load existing model: {e}')
        
        # Need to train fresh model
        log_worker_event('info', 'Training fresh model for prediction')
        hours_needed = TRAIN_SPAN_HOURS + VALIDATION_SPAN_HOURS + TARGET_HOURS + HISTORY_BUFFER_HOURS
        market_data = fetch_market_data(hours_needed)
        prediction = train_model(market_data)
        
        return prediction
        
    except Exception as e:
        log_worker_event('error', f'Prediction function failed: {e}',
                        {'traceback': traceback.format_exc()})
        # Return a safe fallback value (0.0 = no expected change)
        return 0.0


async def run_worker(polling_interval: int = 120, debug: bool = False):
    """Run the continuous worker."""
    
    # Startup checks
    log_worker_event('startup', 'Starting Allora Worker', {
        'topic_id': TOPIC_ID,
        'ticker': TICKER,
        'target_hours': TARGET_HOURS,
        'competition_start': COMPETITION_START.isoformat(),
        'competition_end': COMPETITION_END.isoformat()
    })
    
    # Environment check
    if not load_environment():
        log_worker_event('error', 'Environment check failed')
        return 1
    
    log_worker_event('success', 'Environment loaded successfully')
    
    # Singleton check
    if not check_singleton_guard():
        log_worker_event('error', 'Another worker instance is already running')
        return 1
    
    log_worker_event('success', 'Singleton guard passed')
    
    # Competition status check
    now = datetime.now(timezone.utc)
    if now < COMPETITION_START:
        wait_seconds = (COMPETITION_START - now).total_seconds()
        log_worker_event('info', f'Competition starts in {wait_seconds/3600:.1f} hours')
        log_worker_event('info', 'Worker will start when competition begins')
        return 0
    
    if now > COMPETITION_END:
        log_worker_event('info', 'Competition has ended')
        return 0
    
    log_worker_event('success', 'Competition is active')
    
    # Configure wallet
    mnemonic = os.getenv('MNEMONIC')
    wallet_config = AlloraWalletConfig(mnemonic=mnemonic)
    
    log_worker_event('success', 'Wallet configured from mnemonic')
    
    # Configure network
    network_config = AlloraNetworkConfig(
        chain_id=CHAIN_ID,
        url=DEFAULT_RPC,
        websocket_url=DEFAULT_WS,
        fee_denom='uallo',
        fee_minimum_gas_price=10.0
    )
    
    # Create worker
    worker = AlloraWorker(
        run=get_prediction,
        wallet=wallet_config,
        network=network_config,
        topic_id=TOPIC_ID,
        polling_interval=polling_interval,
        debug=debug
    )
    
    log_worker_event('success', 'Worker initialized', {
        'topic_id': TOPIC_ID,
        'polling_interval': polling_interval,
        'debug': debug
    })
    
    # Run worker indefinitely
    log_worker_event('info', 'Starting worker polling loop...')
    log_worker_event('info', 'Worker will respond to network submission windows')
    
    try:
        async for result in worker.run():
            if isinstance(result, Exception):
                log_worker_event('error', f'Worker error: {result}',
                               {'traceback': traceback.format_exc()})
            else:
                log_worker_event('submission', 'Prediction submitted',
                               {'result': str(result)})
                
                # Check if competition ended
                if datetime.now(timezone.utc) > COMPETITION_END:
                    log_worker_event('info', 'Competition ended - shutting down')
                    break
    
    except KeyboardInterrupt:
        log_worker_event('shutdown', 'Received shutdown signal')
    except Exception as e:
        log_worker_event('error', f'Worker crashed: {e}',
                        {'traceback': traceback.format_exc()})
        return 1
    
    log_worker_event('shutdown', 'Worker stopped gracefully')
    return 0


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run Allora Worker for Topic 67')
    parser.add_argument('--polling', type=int, default=120,
                       help='Polling interval in seconds (default: 120)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug logging')
    
    args = parser.parse_args()
    
    return asyncio.run(run_worker(
        polling_interval=args.polling,
        debug=args.debug
    ))


if __name__ == '__main__':
    sys.exit(main())
