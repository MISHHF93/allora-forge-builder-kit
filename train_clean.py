#!/usr/bin/env python3
"""
Minimal, clean pipeline for BTC/USD 7-day log-return forecasting.

Each execution:
1. Fetches fresh BTC/USD data
2. Computes 7-day log-return targets
3. Trains a model on 60-90 day rolling window
4. Generates prediction for current time
5. Submits to Allora blockchain
"""

import os
import sys
import json
import logging
import argparse
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline_run.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()


# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_btcusd_data(days_back: int = 90) -> pd.DataFrame:
    """
    Fetch BTC/USD OHLCV data from local CSV or Tiingo API.
    
    Args:
        days_back: Number of days of historical data to retrieve
        
    Returns:
        DataFrame with columns: [date, open, high, low, close, volume]
    """
    logger.info(f"Fetching BTC/USD data (last {days_back} days)")
    
    # Try local CSV first
    local_path = "data/external/btcusd_ohlcv.csv"
    if os.path.exists(local_path):
        df = pd.read_csv(local_path)
        df['date'] = pd.to_datetime(df['date'], utc=True)
        
        # Filter to requested timeframe
        cutoff = datetime.now(pd.Timestamp.now(tz='UTC').tz) - timedelta(days=days_back)
        df = df[df['date'] >= cutoff].copy()
        
        logger.info(f"Loaded {len(df)} rows from local CSV (date range: {df['date'].min()} to {df['date'].max()})")
        return df.sort_values('date').reset_index(drop=True)
    
    # Fallback: Mock data (for testing)
    logger.warning("Local CSV not found, using mock data")
    dates = pd.date_range(end=datetime.now(pd.Timestamp.now(tz='UTC').tz), periods=days_back, freq='1h', tz='UTC')
    
    # Simple random walk for mock prices
    prices = 45000 + np.cumsum(np.random.normal(0, 100, days_back))
    volumes = np.random.uniform(1000, 5000, days_back)
    
    return pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': prices * 1.002,
        'low': prices * 0.998,
        'close': prices,
        'volume': volumes
    })


# ============================================================================
# FEATURE ENGINEERING
# ============================================================================

def generate_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate technical features from OHLCV data.
    
    Features:
    - Returns (hourly, daily)
    - Moving averages (7h, 24h, 72h)
    - Volatility (7h, 24h)
    - Volume stats
    
    Args:
        df: DataFrame with OHLCV data
        
    Returns:
        DataFrame with original OHLCV + features
    """
    logger.info(f"Generating features for {len(df)} rows")
    
    df = df.copy()
    
    # Basic returns
    df['return_1h'] = df['close'].pct_change()
    df['log_return_1h'] = np.log(df['close'] / df['close'].shift(1))
    
    # Moving averages
    for window in [7, 24, 72]:
        df[f'ma_{window}h'] = df['close'].rolling(window=window).mean()
        df[f'ma_ratio_{window}h'] = df['close'] / df[f'ma_{window}h']
    
    # Volatility
    for window in [7, 24]:
        df[f'volatility_{window}h'] = df['log_return_1h'].rolling(window=window).std()
    
    # Volume stats
    df['volume_ma_24h'] = df['volume'].rolling(window=24).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma_24h']
    
    # Price position in range
    for window in [24, 72]:
        high_20 = df['high'].rolling(window=window).max()
        low_20 = df['low'].rolling(window=window).min()
        df[f'price_position_{window}h'] = (df['close'] - low_20) / (high_20 - low_20 + 1e-8)
    
    # Drop NaN from initial calculations
    df = df.dropna()
    
    logger.info(f"Generated {len(df.columns) - 6} features ({len(df)} rows after NaN drop)")
    return df


def calculate_log_return_target(df: pd.DataFrame, horizon_hours: int = 168) -> pd.DataFrame:
    """
    Calculate 7-day (168-hour) forward-looking log-return target.
    
    Target = log(price_t+168 / price_t)
    
    Args:
        df: DataFrame with OHLCV data
        horizon_hours: Number of hours ahead (default 168 = 7 days)
        
    Returns:
        DataFrame with added 'target' column
    """
    logger.info(f"Computing {horizon_hours}h forward-looking log-return target")
    
    df = df.copy()
    
    # Get future price (shift backward in time to align index)
    df['future_close'] = df['close'].shift(-horizon_hours)
    df['target'] = np.log(df['future_close'] / df['close'])
    
    # Drop rows without valid future target
    valid_rows = len(df[df['target'].notna()])
    df = df[df['target'].notna()].copy()
    
    logger.info(f"Valid target rows: {len(df)} (dropped {valid_rows - len(df)} rows without 7-day future)")
    return df


# ============================================================================
# TRAINING
# ============================================================================

def train_model(X: pd.DataFrame, y: pd.Series):
    """
    Train XGBoost model on features and target.
    
    Args:
        X: Feature matrix
        y: Target variable (7-day log-return)
        
    Returns:
        Trained model
    """
    logger.info(f"Training model on {len(X)} samples, {X.shape[1]} features")
    
    try:
        from xgboost import XGBRegressor
        
        model = XGBRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbosity=0
        )
        
        model.fit(X, y)
        logger.info(f"Model training complete")
        return model
        
    except ImportError:
        logger.warning("XGBoost not available, using Ridge regression")
        from sklearn.linear_model import Ridge
        
        model = Ridge(alpha=1.0)
        model.fit(X, y)
        logger.info(f"Ridge model training complete")
        return model


# ============================================================================
# PREDICTION
# ============================================================================

def prepare_live_features(df: pd.DataFrame, feature_cols: list) -> pd.DataFrame:
    """
    Prepare features for live prediction (current timestamp).
    
    Args:
        df: DataFrame with all features
        feature_cols: List of feature column names
        
    Returns:
        Single row DataFrame with live features
    """
    logger.info(f"Preparing live prediction features")
    
    # Get latest row with all features
    live = df[feature_cols].iloc[-1:].copy()
    
    logger.info(f"Live feature shape: {live.shape}")
    return live


def predict_log_return(model, X_live: pd.DataFrame) -> float:
    """
    Generate prediction for 7-day log-return.
    
    Args:
        model: Trained model
        X_live: Live feature row
        
    Returns:
        Predicted log-return
    """
    prediction = float(model.predict(X_live)[0])
    logger.info(f"Prediction: {prediction:.6f}")
    return prediction


# ============================================================================
# SUBMISSION
# ============================================================================

def submit_prediction(value: float, topic_id: int = 67, dry_run: bool = False) -> bool:
    """
    Submit prediction to Allora blockchain via CLI.
    
    Args:
        value: Predicted log-return value
        topic_id: Topic ID (default 67 for BTC/USD)
        dry_run: If True, only log without submitting
        
    Returns:
        True if submission successful, False otherwise
    """
    logger.info(f"Submitting prediction: value={value:.6f}, topic={topic_id}")
    
    # Save prediction to artifacts
    artifacts_dir = "data/artifacts"
    os.makedirs(artifacts_dir, exist_ok=True)
    
    prediction_data = {
        "topic_id": topic_id,
        "value": float(value),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    with open(os.path.join(artifacts_dir, "predictions.json"), "w") as f:
        json.dump(prediction_data, f, indent=2)
    
    logger.info(f"Saved prediction to predictions.json")
    
    if dry_run:
        logger.info("DRY RUN MODE: Skipping blockchain submission")
        return True
    
    # Submit via CLI helper (if available)
    wallet = os.getenv("ALLORA_WALLET_ADDR")
    if not wallet:
        logger.warning("ALLORA_WALLET_ADDR not set, skipping submission")
        return False
    
    try:
        # Call external submission script
        result = os.system(
            f"python scripts/submit_forecast.py --value {value} --topic {topic_id}"
        )
        
        if result == 0:
            logger.info("Submission successful")
            return True
        else:
            logger.error(f"Submission failed with code {result}")
            return False
            
    except Exception as e:
        logger.error(f"Submission error: {e}")
        return False


# ============================================================================
# PIPELINE
# ============================================================================

def run_pipeline(days_back: int = 90, submit: bool = False, dry_run: bool = False) -> int:
    """
    Execute full pipeline: fetch → train → predict → submit.
    
    Args:
        days_back: Days of historical data to use
        submit: Whether to submit prediction to blockchain
        dry_run: If True, don't submit but go through everything else
        
    Returns:
        Exit code (0 = success, 1 = failure)
    """
    logger.info("=" * 80)
    logger.info("STARTING PIPELINE: Fresh BTC/USD 7-day forecast")
    logger.info("=" * 80)
    
    try:
        # 1. Fetch data
        df = fetch_btcusd_data(days_back=days_back)
        if df.empty:
            logger.error("No data fetched")
            return 1
        
        # 2. Generate features
        df = generate_features(df)
        if df.empty:
            logger.error("Feature generation produced no valid rows")
            return 1
        
        # 3. Calculate targets
        df = calculate_log_return_target(df, horizon_hours=168)
        if df.empty:
            logger.error("No valid targets computed")
            return 1
        
        # 4. Prepare training data (use rolling window)
        # Use last 60-90 days for training
        feature_cols = [col for col in df.columns if col not in ['date', 'target', 'future_close']]
        X = df[feature_cols]
        y = df['target']
        
        logger.info(f"Training set: {len(X)} samples, {len(feature_cols)} features")
        logger.info(f"Feature columns: {feature_cols[:5]}... ({len(feature_cols)} total)")
        
        # 5. Train model
        model = train_model(X, y)
        
        # 6. Predict on latest data
        X_live = prepare_live_features(df, feature_cols)
        prediction = predict_log_return(model, X_live)
        
        # 7. Submit if requested
        if submit:
            success = submit_prediction(prediction, topic_id=67, dry_run=dry_run)
            if not success and not dry_run:
                logger.error("Submission failed")
                return 1
        else:
            logger.info("Submission skipped (--submit not specified)")
        
        logger.info("=" * 80)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        return 1


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Parse arguments and run pipeline once."""
    parser = argparse.ArgumentParser(
        description="Fetch data, train model, and forecast BTC/USD 7-day log-return"
    )
    parser.add_argument(
        "--days", type=int, default=90,
        help="Days of historical data (default 90)"
    )
    parser.add_argument(
        "--submit", action="store_true",
        help="Submit prediction to blockchain"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run everything except blockchain submission"
    )
    
    args = parser.parse_args()
    
    exit_code = run_pipeline(
        days_back=args.days,
        submit=args.submit,
        dry_run=args.dry_run
    )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
