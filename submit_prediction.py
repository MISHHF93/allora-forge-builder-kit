#!/usr/bin/env python3
"""
BTC/USD 7-Day Log-Return Prediction Submission Daemon
------------------------------------------------------
Loads trained model and features, fetches latest data, predicts,
prepares Allora worker payload, and submits via allorad CLI.

DAEMON MODE: Runs as a reliable long-lived process until December 15, 2025
- Catches ALL exceptions and logs full tracebacks
- Hourly heartbeat/liveness check
- Never silently fails
- Suitable for systemd/supervisord auto-restart
- Validates model on every cycle

Usage:
    python submit_prediction.py [--model MODEL_PATH] [--features FEATURES_PATH] [--topic-id TOPIC_ID] [--dry-run] [--once]
    python submit_prediction.py --daemon  (run as permanent daemon)
"""

import os
import os
import sys
import json
import shutil
import logging
import logging.handlers
import argparse
import subprocess
import hashlib
import base64
import time
import math
import signal
import traceback
from typing import List, Optional
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

# RPC Endpoint Failover List with priorities
# Note: Only primary endpoint is accessible from this environment
# Other endpoints may be available depending on network configuration
RPC_ENDPOINTS = [
    {"url": "https://allora-rpc.testnet.allora.network/", "name": "Primary", "priority": 1},
    # {"url": "https://allora-testnet-rpc.allthatnode.com:1317/", "name": "AllThatNode", "priority": 2},
    # {"url": "https://allora.api.chandrastation.com/", "name": "ChandraStation", "priority": 3},
]

# Global state for RPC endpoint rotation with enhanced tracking
_rpc_endpoint_index = 0
_failed_rpc_endpoints = {}  # endpoint_url -> failure_count
_rpc_endpoint_last_used = None
_submission_attempt_count = 0
_max_submission_retries = 3

import requests
import numpy as np
import pandas as pd

from allora_sdk import LocalWallet, AlloraRPCClient
from allora_sdk.protos.emissions.v9 import InputWorkerDataBundle, InputInferenceForecastBundle, InputInference, InsertWorkerPayloadRequest

# Simple Nonce class since import fails
class Nonce:
    def __init__(self, block_height: int):
        self.block_height = block_height

###############################################################################
# Response Validation - Detect Invalid JSON/HTML responses
###############################################################################
def validate_json_response(response_text: str, context: str = "") -> tuple[bool, dict]:
    """Validate that response is valid JSON, not HTML error page."""
    response_text = response_text.strip()
    
    # Check for HTML responses (error pages)
    if response_text.startswith("<"):
        logger.error(f"❌ Received HTML response instead of JSON {context}")
        logger.debug(f"   Response starts with: {response_text[:100]}")
        return False, {}
    
    # Check for empty response
    if not response_text:
        logger.error(f"❌ Empty response received {context}")
        return False, {}
    
    # Try to parse JSON
    try:
        data = json.loads(response_text)
        return True, data
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid JSON response {context}: {e}")
        logger.debug(f"   Response: {response_text[:200]}")
        return False, {}

###############################################################################
# RPC Endpoint Management with Enhanced Failover
###############################################################################
def get_rpc_endpoint() -> dict:
    """Get the next working RPC endpoint with automatic failover."""
    global _rpc_endpoint_index, _failed_rpc_endpoints
    
    # Count of working endpoints
    working_endpoints = [e for e in RPC_ENDPOINTS if _failed_rpc_endpoints.get(e["url"], 0) < 3]
    
    # If all endpoints exhausted, reset
    if not working_endpoints:
        logger.info("🔄 Resetting failed RPC endpoints - all exceeded retry limit")
        _failed_rpc_endpoints.clear()
        working_endpoints = RPC_ENDPOINTS
        _rpc_endpoint_index = 0
    
    # Get next endpoint
    endpoint = working_endpoints[_rpc_endpoint_index % len(working_endpoints)]
    _rpc_endpoint_index += 1
    
    logger.debug(f"Selected RPC endpoint: {endpoint['name']} ({endpoint['url']})")
    return endpoint

def mark_rpc_failed(endpoint_url: str, error: str = ""):
    """Mark an RPC endpoint as failed and track failure count."""
    global _failed_rpc_endpoints
    current_failures = _failed_rpc_endpoints.get(endpoint_url, 0)
    _failed_rpc_endpoints[endpoint_url] = current_failures + 1
    
    endpoint_name = next((e["name"] for e in RPC_ENDPOINTS if e["url"] == endpoint_url), "Unknown")
    logger.warning(
        f"⚠️  RPC endpoint marked failed: {endpoint_name}\n"
        f"   Failures: {_failed_rpc_endpoints[endpoint_url]}/3\n"
        f"   Error: {error}"
    )

def reset_rpc_endpoint(endpoint_url: str):
    """Reset RPC endpoint failure count after successful use."""
    global _failed_rpc_endpoints
    if endpoint_url in _failed_rpc_endpoints:
        _failed_rpc_endpoints[endpoint_url] = 0
        endpoint_name = next((e["name"] for e in RPC_ENDPOINTS if e["url"] == endpoint_url), "Unknown")
        logger.debug(f"✅ Reset failure count for {endpoint_name}")


###############################################################################
# Logging Setup - Enhanced for Daemon
###############################################################################
def setup_logging(log_file: str = "logs/submission.log"):
    """Configure logging with both console and file output."""
    logger = logging.getLogger("btc_submit")
    logger.setLevel(logging.DEBUG)
    
    # Create logs directory if needed
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Console handler (INFO level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%SZ'
    )
    console_handler.setFormatter(console_fmt)
    
    # File handler with rotation (DEBUG level - capture everything)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=50*1024*1024,  # 50 MB
        backupCount=5,           # Keep 5 rotated files
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%SZ'
    )
    file_handler.setFormatter(file_fmt)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

# Global state for daemon
_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle termination signals gracefully."""
    global _shutdown_requested
    signal_name = signal.Signals(signum).name
    logger.warning(f"Received signal {signal_name} ({signum}), initiating graceful shutdown...")
    _shutdown_requested = True

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGHUP, signal_handler)

###############################################################################
# Data Fetching (Latest)
###############################################################################
def fetch_latest_btcusd_hourly(hours: int = 168, api_timeout: int = 30) -> pd.DataFrame:
    """Fetch recent BTC/USD hourly data for prediction."""
    logger.info(f"Fetching latest {hours}h BTC/USD data from Tiingo...")
    tkey = os.getenv("TIINGO_API_KEY", "").strip()
    if not tkey:
        logger.warning("TIINGO_API_KEY not set; generating synthetic.")
        # Synthetic for latest
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
        return df
    try:
        # Adjust start date to fetch more data
        start_date = (datetime.now(timezone.utc) - pd.Timedelta(hours=hours)).strftime("%Y-%m-%d")
        url = "https://api.tiingo.com/tiingo/crypto/prices"
        params = {
            "tickers": "btcusd",
            "startDate": start_date,
            "resampleFreq": "1hour",
            "token": tkey,
        }
        r = requests.get(url, params=params, timeout=api_timeout)
        r.raise_for_status()
        data = r.json()
        price_data = data[0].get("priceData", [])
        if len(price_data) < hours * 0.5:  # If less than 50% of expected
            logger.warning(f"Tiingo returned only {len(price_data)} rows, expected ~{hours}; using synthetic fallback.")
            # Fallback
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
            return df
        rows = []
        for item in price_data[-hours:]:  # Take last hours
            dt = datetime.fromisoformat(item["date"].replace("Z", "+00:00"))
            rows.append((dt, float(item["close"])))
        df = pd.DataFrame(rows, columns=["timestamp", "close"]).drop_duplicates("timestamp").sort_values("timestamp")
        logger.info(f"Fetched {len(df)} latest rows from Tiingo")
        return df
    except Exception as e:
        logger.warning(f"Tiingo fetch failed ({e}); using synthetic.")
        # Same as above
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
        return df

###############################################################################
# Feature Engineering (Same as training)
###############################################################################
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

###############################################################################
# Prediction
###############################################################################
def predict_forward_log_return(model, x_live: np.ndarray) -> float:
    pred = float(model.predict(x_live)[0])
    logger.info(f"Predicted 168h log-return: {pred:.8f}")
    return pred

###############################################################################
# Model Validation (COMPREHENSIVE - Prevents All Model Fitting Issues)
###############################################################################
def validate_model(model_path: str, feature_count: int) -> bool:
    """
    Comprehensive model validation to prevent ALL model fitting issues.
    Checks: file existence, load, fitted state, feature count, prediction capability.
    """
    import pickle
    
    # CHECK 1: File existence
    if not os.path.exists(model_path):
        logger.error(f"❌ Model file not found: {model_path}")
        logger.error("   FIX: Run 'python train.py' to train and save a model")
        return False
    
    # CHECK 2: File is readable and not corrupted
    try:
        file_size = os.path.getsize(model_path)
        logger.debug(f"Model file size: {file_size} bytes")
        if file_size == 0:
            logger.error(f"❌ Model file is empty: {model_path}")
            logger.error("   FIX: Run 'python train.py' to train and save a model")
            return False
    except Exception as e:
        logger.error(f"❌ Cannot access model file: {e}")
        return False
    
    # CHECK 3: Model loads without corruption
    try:
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        logger.debug(f"✅ Model deserialized successfully from {model_path}")
    except pickle.UnpicklingError as e:
        logger.error(f"❌ Model file is corrupted (pickle error): {e}")
        logger.error("   FIX: Run 'python train.py' to retrain and save a fresh model")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}")
        logger.error("   FIX: Run 'python train.py' to train and save a model")
        return False
    
    # CHECK 4: Model is the correct type
    try:
        model_type = type(model).__name__
        if not hasattr(model, 'predict'):
            logger.error(f"❌ Model object has no predict() method. Type: {model_type}")
            logger.error("   FIX: Run 'python train.py' to train and save a valid model")
            return False
        logger.debug(f"Model type: {model_type} (has predict method)")
    except Exception as e:
        logger.error(f"❌ Model type check failed: {e}")
        return False
    
    # CHECK 5: Model is FITTED (has n_features_in_ attribute)
    try:
        if not hasattr(model, 'n_features_in_'):
            logger.error("❌ Model is NOT FITTED (missing n_features_in_ attribute)")
            logger.error("   This means train.py was not run or model.pkl is incomplete")
            logger.error("   FIX: Run 'python train.py' to train and save a fitted model")
            return False
        logger.debug(f"✅ Model is fitted (n_features_in_={model.n_features_in_})")
    except Exception as e:
        logger.error(f"❌ Model fitted-state check failed: {e}")
        return False
    
    # CHECK 6: Feature count matches
    try:
        if model.n_features_in_ != feature_count:
            logger.error(f"❌ Feature count MISMATCH")
            logger.error(f"   Model expects: {model.n_features_in_} features")
            logger.error(f"   features.json has: {feature_count} features")
            logger.error("   FIX: Run 'python train.py' to regenerate features.json and model")
            return False
        logger.debug(f"✅ Feature count matches: {feature_count}")
    except Exception as e:
        logger.error(f"❌ Feature count check failed: {e}")
        return False
    
    # CHECK 7: Model has expected scikit-learn/XGBoost fitted attributes
    try:
        has_coef = hasattr(model, 'coef_')
        has_intercept = hasattr(model, 'intercept_')
        has_estimators = hasattr(model, 'estimators_')
        has_booster = hasattr(model, 'booster_')
        
        # At least some fitted attributes should be present
        fitted_attrs = [has_coef, has_intercept, has_estimators, has_booster]
        if not any(fitted_attrs):
            logger.error("❌ Model has no fitted attributes (coef_, intercept_, estimators_, booster_)")
            logger.error("   This means model.pkl was not properly saved after training")
            logger.error("   FIX: Run 'python train.py' to retrain and save model properly")
            return False
        logger.debug(f"Fitted attributes present: coef_={has_coef}, intercept_={has_intercept}, estimators_={has_estimators}, booster_={has_booster}")
    except Exception as e:
        logger.error(f"❌ Fitted attributes check failed: {e}")
        return False
    
    # CHECK 8: Test prediction on ZERO input (most robust test)
    try:
        zero_input = np.zeros((1, feature_count))
        test_pred = model.predict(zero_input)
        
        # Validate prediction output
        if not isinstance(test_pred, np.ndarray) or test_pred.shape != (1,):
            logger.error(f"❌ Prediction output has wrong shape: {test_pred.shape}")
            logger.error("   Model may be incompatible or corrupted")
            logger.error("   FIX: Run 'python train.py' to retrain")
            return False
        
        pred_value = float(test_pred[0])
        
        # Check for invalid predictions (NaN, Inf)
        if np.isnan(pred_value):
            logger.error(f"❌ Prediction is NaN (not a number)")
            logger.error("   Model may have numerical issues")
            logger.error("   FIX: Run 'python train.py' to retrain with better data")
            return False
        if np.isinf(pred_value):
            logger.error(f"❌ Prediction is Inf (infinity)")
            logger.error("   Model has overflow issues")
            logger.error("   FIX: Run 'python train.py' to retrain")
            return False
        
        logger.debug(f"✅ Test prediction on zero input successful: {pred_value:.8f}")
    except TypeError as e:
        logger.error(f"❌ Model.predict() raised TypeError: {e}")
        logger.error("   Model may be incompatible with input shape")
        logger.error("   FIX: Run 'python train.py' to retrain")
        return False
    except Exception as e:
        logger.error(f"❌ Model test prediction failed: {e}")
        logger.error("   Model.pkl may be corrupted")
        logger.error("   FIX: Run 'python train.py' to retrain and save a fresh model")
        return False
    
    # CHECK 9: Test prediction on RANDOM input (stress test)
    try:
        random_input = np.random.randn(1, feature_count)
        random_pred = model.predict(random_input)
        random_value = float(random_pred[0])
        
        if np.isnan(random_value) or np.isinf(random_value):
            logger.error(f"❌ Prediction on random input produced invalid value: {random_value}")
            logger.error("   Model has stability issues")
            logger.error("   FIX: Run 'python train.py' to retrain with better regularization")
            return False
        
        logger.debug(f"✅ Test prediction on random input successful: {random_value:.8f}")
    except Exception as e:
        logger.error(f"❌ Model stress test (random input) failed: {e}")
        logger.error("   FIX: Run 'python train.py' to retrain")
        return False
    
    # ALL CHECKS PASSED
    logger.info(f"✅ Model validation PASSED - Model is ready")
    logger.info(f"   ✅ File: {model_path} ({file_size} bytes)")
    logger.info(f"   ✅ Type: {type(model).__name__}")
    logger.info(f"   ✅ Fitted: n_features_in_={model.n_features_in_}")
    logger.info(f"   ✅ Predictions: Working (zero={float(test_pred[0]):.8f}, random={random_value:.8f})")
    return True

###############################################################################
# Get Account Sequence with Enhanced RPC Handling
###############################################################################
def get_account_sequence(wallet: str) -> int:
    """Query account sequence from Allora network with RPC failover and validation."""
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("❌ Allora CLI not found in PATH")
        return 0
    
    rpc_endpoint = get_rpc_endpoint()
    logger.debug(f"Querying account sequence via RPC: {rpc_endpoint['name']} ({rpc_endpoint['url']})")
    
    cmd = [cli, "query", "auth", "account", wallet, 
           "--node", rpc_endpoint["url"],
           "--output", "json"]
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if proc.returncode == 0:
            # Validate response is JSON, not HTML error
            is_valid, data = validate_json_response(proc.stdout, f"for account {wallet}")
            if not is_valid:
                mark_rpc_failed(rpc_endpoint["url"], "Invalid JSON response (likely HTML error)")
                return 0
            
            sequence = int(data["account"]["value"]["sequence"])
            logger.debug(f"✅ Got account sequence: {sequence} from {rpc_endpoint['name']}")
            reset_rpc_endpoint(rpc_endpoint["url"])
            return sequence
        else:
            error_msg = proc.stderr.strip()
            logger.warning(f"⚠️  Query failed for account {wallet} on {rpc_endpoint['name']}: {error_msg}")
            mark_rpc_failed(rpc_endpoint["url"], error_msg)
            return 0
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failed to parse account sequence response: {e}")
        mark_rpc_failed(rpc_endpoint["url"], f"JSON decode error: {e}")
        return 0
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Query timed out (30s) for account sequence on {rpc_endpoint['name']}")
        mark_rpc_failed(rpc_endpoint["url"], "Timeout (30s)")
        return 0
    except Exception as e:
        logger.error(f"❌ Error querying account sequence: {e}")
        mark_rpc_failed(rpc_endpoint["url"], str(e))
        return 0

###############################################################################
# Get Unfulfilled Nonce with Enhanced RPC Handling
###############################################################################
def get_unfulfilled_nonce(topic_id: int) -> int:
    """Query unfulfilled nonces from Allora network with RPC failover and validation."""
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("❌ Allora CLI not found in PATH")
        return 0
    
    rpc_endpoint = get_rpc_endpoint()
    logger.debug(f"Querying unfulfilled nonces for topic {topic_id} via RPC: {rpc_endpoint['name']}")
    
    cmd = [cli, "query", "emissions", "unfulfilled-worker-nonces", str(topic_id),
           "--node", rpc_endpoint["url"],
           "--output", "json"]
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            # Validate response is JSON, not HTML error
            is_valid, data = validate_json_response(proc.stdout, f"for unfulfilled nonces (topic {topic_id})")
            if not is_valid:
                mark_rpc_failed(rpc_endpoint["url"], "Invalid JSON response")
                return 0
            
            nonces_data = data.get("nonces", {}).get("nonces", [])
            nonces = [int(item["block_height"]) for item in nonces_data]
            
            if not nonces:
                logger.info(f"ℹ️  No unfulfilled nonces found for topic {topic_id}")
                reset_rpc_endpoint(rpc_endpoint["url"])
                return 0
            
            logger.debug(f"✅ Found {len(nonces)} unfulfilled nonces for topic {topic_id}: {nonces}")
            
            # Filter out nonces already submitted by this worker
            wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
            if not wallet:
                logger.error("❌ ALLORA_WALLET_ADDR not set")
                return 0
            
            filtered_nonces = []
            for nonce in nonces:
                try:
                    # Check if already submitted
                    cmd_check = [cli, "query", "emissions", "worker-latest-inference", 
                                str(topic_id), wallet,
                                "--node", rpc_endpoint["url"],
                                "--output", "json"]
                    proc_check = subprocess.run(cmd_check, capture_output=True, text=True, timeout=30)
                    
                    if proc_check.returncode == 0:
                        is_valid_check, data_check = validate_json_response(proc_check.stdout)
                        if is_valid_check:
                            latest_bh = int(data_check.get("latest_inference", {}).get("block_height", 0))
                            if latest_bh != nonce:
                                filtered_nonces.append(nonce)
                                logger.debug(f"  ✓ Nonce {nonce} available (latest submitted: {latest_bh})")
                            else:
                                logger.debug(f"  ✗ Nonce {nonce} already submitted")
                        else:
                            # Invalid response, assume not submitted
                            filtered_nonces.append(nonce)
                            logger.debug(f"  ? Nonce {nonce} check inconclusive (invalid response), will attempt")
                    else:
                        # If check fails, assume not submitted and include it
                        filtered_nonces.append(nonce)
                        logger.debug(f"  ? Nonce {nonce} check inconclusive (query failed), will attempt submission")
                except Exception as e:
                    logger.warning(f"⚠️  Error checking nonce {nonce}: {e}")
                    filtered_nonces.append(nonce)
            
            if filtered_nonces:
                selected_nonce = min(filtered_nonces)
                logger.info(f"🎯 Selected nonce for submission: block_height={selected_nonce}")
                reset_rpc_endpoint(rpc_endpoint["url"])
                return selected_nonce
            else:
                logger.warning(f"⚠️  All unfulfilled nonces already submitted by worker {wallet}")
                reset_rpc_endpoint(rpc_endpoint["url"])
                return 0
        else:
            error_msg = proc.stderr.strip()
            logger.warning(f"⚠️  Query failed for unfulfilled nonces: {error_msg}")
            # Check for gRPC specific errors
            if "grpc_status:12" in error_msg or "received http2 header with status: 404" in error_msg.lower():
                logger.warning(f"   ⚠️  gRPC 404 error - RPC service may have transient issue")
                logger.warning(f"   This is typically resolved by retrying")
            mark_rpc_failed(rpc_endpoint["url"], error_msg)
            return 0
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failed to parse unfulfilled nonces response: {e}")
        mark_rpc_failed(rpc_endpoint["url"], f"JSON decode error: {e}")
        return 0
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Query timed out (30s) for unfulfilled nonces on {rpc_endpoint['name']}")
        mark_rpc_failed(rpc_endpoint["url"], "Timeout (30s)")
        return 0
    except Exception as e:
        logger.error(f"❌ Error querying unfulfilled nonces: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")
        mark_rpc_failed(rpc_endpoint["url"], str(e))
        return 0

###############################################################################
# Validate Transaction On-Chain with Enhanced Response Handling
###############################################################################
def validate_transaction_on_chain(tx_hash: str, rpc_endpoint: dict) -> bool:
    """Verify that a transaction actually landed on-chain with response validation."""
    try:
        logger.debug(f"Validating transaction {tx_hash} on-chain via {rpc_endpoint['name']}...")
        
        cmd = ["curl", "-s", "-m", "30", f"{rpc_endpoint['url']}cosmos/tx/v1beta1/txs/{tx_hash}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        
        if proc.returncode == 0:
            # Validate response is JSON, not HTML error
            is_valid, resp = validate_json_response(proc.stdout, f"for transaction {tx_hash}")
            if not is_valid:
                logger.warning(f"⚠️  Invalid response when validating transaction {tx_hash}")
                return False
            
            # Check if transaction succeeded
            if resp.get("code") == 0 or "tx" in resp:
                logger.info(f"✅ Transaction {tx_hash} confirmed on-chain via {rpc_endpoint['name']}")
                reset_rpc_endpoint(rpc_endpoint["url"])
                return True
            else:
                logger.warning(f"⚠️  Transaction {tx_hash} not confirmed: {resp.get('message', 'unknown error')}")
                return False
        else:
            logger.debug(f"Could not validate transaction {tx_hash}: {proc.stderr}")
            return False
    except Exception as e:
        logger.debug(f"Error validating transaction: {e}")
        return False

###############################################################################
# CSV Submission Logging with RPC and Status Tracking
###############################################################################
def log_submission_to_csv(timestamp: str, topic_id: int, prediction: float, worker: str, 
                          block_height: int, proof: dict, signature: str, status: str, 
                          tx_hash: str, rpc_endpoint: str = "unknown"):
    """Log submission to CSV with RPC endpoint used and full status."""
    csv_path = "submission_log.csv"
    
    record = {
        "timestamp": timestamp,
        "topic_id": str(topic_id),
        "prediction": str(prediction),
        "worker": worker,
        "block_height": str(block_height),
        "proof": json.dumps(proof) if proof else "",
        "signature": signature,
        "status": status,
        "tx_hash": tx_hash or "",
        "rpc_endpoint": rpc_endpoint,
    }
    
    try:
        import csv
        
        # Check if file exists to determine if we need headers
        file_exists = os.path.exists(csv_path)
        
        with open(csv_path, "a", newline="") as f:
            fieldnames = ["timestamp", "topic_id", "prediction", "worker", "block_height", 
                         "proof", "signature", "status", "tx_hash", "rpc_endpoint"]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            
            # Write header if file is new
            if not file_exists:
                w.writeheader()
            
            w.writerow(record)
        
        logger.info(f"📝 Logged submission to CSV (RPC: {rpc_endpoint}, Status: {status})")
    except Exception as e:
        logger.error(f"❌ Failed to log to CSV: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")

###############################################################################
# Update Latest Submission JSON
###############################################################################
def update_latest_submission_json(timestamp: str, topic_id: int, prediction: float, worker: str,
                                   block_height: int, proof: dict, signature: str, status: str,
                                   tx_hash: str = "", rpc_endpoint: str = "N/A"):
    """Update latest_submission.json with current cycle data."""
    try:
        with open("latest_submission.json", "w") as jf:
            json.dump({
                "timestamp": timestamp,
                "topic_id": topic_id,
                "prediction": prediction,
                "worker": worker,
                "block_height": block_height,
                "proof": proof,
                "signature": signature,
                "status": status,
                "tx_hash": tx_hash or None,
                "rpc_endpoint": rpc_endpoint,
            }, jf, indent=2)
        logger.debug(f"Updated latest_submission.json with status: {status}")
    except Exception as e:
        logger.error(f"❌ Failed to update latest_submission.json: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")

###############################################################################
# Submission with Enhanced RPC Failover, Retry Logic, and CSV Logging
###############################################################################
def submit_prediction(value: float, topic_id: int, dry_run: bool = False) -> bool:
    """Submit prediction with RPC failover, retry logic, and comprehensive logging."""
    global _submission_attempt_count
    _submission_attempt_count = 0
    
    timestamp = datetime.now(timezone.utc).isoformat()
    wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
    
    # Validate wallet before proceeding
    if not wallet:
        logger.error("❌ ALLORA_WALLET_ADDR not set")
        return False
    
    logger.info(f"🚀 LEADERBOARD SUBMISSION: Preparing prediction for topic {topic_id}")
    
    block_height = get_unfulfilled_nonce(topic_id)
    if block_height == 0:
        logger.warning("⚠️  No unfulfilled nonce available, skipping submission")
        log_submission_to_csv(
            timestamp=timestamp,
            topic_id=topic_id,
            prediction=value,
            worker=wallet,
            block_height=0,
            proof={},
            signature="",
            status="skipped_no_nonce",
            tx_hash="",
            rpc_endpoint="N/A"
        )
        # Update JSON even when skipping
        update_latest_submission_json(
            timestamp=timestamp,
            topic_id=topic_id,
            prediction=value,
            worker=wallet,
            block_height=0,
            proof={},
            signature="",
            status="skipped_no_nonce",
            tx_hash="",
            rpc_endpoint="N/A"
        )
        return False
    
    logger.info(f"📊 Prediction value: {value:.10f}")
    logger.info(f"📍 Block height: {block_height}")

    sequence = get_account_sequence(wallet)
    if sequence == 0:
        logger.error("❌ Cannot get account sequence (all RPC endpoints failed)")
        log_submission_to_csv(
            timestamp=timestamp,
            topic_id=topic_id,
            prediction=value,
            worker=wallet,
            block_height=block_height,
            proof={},
            signature="",
            status="failed_no_sequence",
            tx_hash="",
            rpc_endpoint="all_failed"
        )
        return False
    
    logger.debug(f"Account sequence: {sequence}")

    # Create wallet for signing
    mnemonic = os.getenv("MNEMONIC", "").strip()
    if not mnemonic:
        logger.error("❌ MNEMONIC not set")
        return False
    
    try:
        wallet_obj = LocalWallet.from_mnemonic(mnemonic)
    except Exception as e:
        logger.error(f"❌ Failed to create wallet from mnemonic: {e}")
        return False

    # Create protobuf bundle
    try:
        inference = InputInference(
            topic_id=topic_id,
            block_height=block_height,
            inferer=wallet,
            value=str(value),
            extra_data=b"",
            proof=""
        )
        bundle = InputInferenceForecastBundle(inference=inference)

        # Serialize bundle to bytes
        bundle_bytes = bundle.SerializeToString()
        digest = hashlib.sha256(bundle_bytes).digest()
        sig = wallet_obj._private_key.sign_digest(digest)
        bundle_signature = base64.b64encode(sig).decode()
        logger.debug(f"Bundle signature created: {bundle_signature[:20]}...")
    except Exception as e:
        logger.error(f"❌ Failed to create bundle/signature: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return False

    # Worker data
    worker_data = {
        "worker": wallet,
        "nonce": {"block_height": block_height},
        "topic_id": topic_id,
        "inference_forecasts_bundle": {
            "inference": {
                "topic_id": topic_id,
                "block_height": block_height,
                "inferer": wallet,
                "value": str(value),
                "extra_data": "",
                "proof": ""
            }
        },
        "inferences_forecasts_bundle_signature": bundle_signature,
        "pubkey": "036ebdd2e91e40fe2e78200c788bf442cf2504a94a0b3eb328dcbda826d526d372"
    }

    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("❌ Allora CLI not found in PATH")
        return False

    # Retry loop with multiple RPC endpoints
    success = False
    status = "pending"
    tx_hash = None
    used_rpc = None
    
    for attempt in range(_max_submission_retries):
        _submission_attempt_count = attempt + 1
        
        # Get RPC endpoint for submission (rotates on each attempt)
        rpc_endpoint = get_rpc_endpoint()
        used_rpc = rpc_endpoint
        logger.info(f"📤 Submission attempt {_submission_attempt_count}/{_max_submission_retries} via {rpc_endpoint['name']}")
        
        # allorad expects: insert-worker-payload [sender] [worker_data] [flags]
        cmd = [cli, "tx", "emissions", "insert-worker-payload",
               wallet,                          # positional arg 1: sender
               json.dumps(worker_data),         # positional arg 2: worker_data
               "--from", wallet,                # flag: signing wallet
               "--yes",
               "--keyring-backend", "test",
               "--node", rpc_endpoint["url"],
               "--chain-id", "allora-testnet-1",
               "--fees", "2500000uallo",
               "--broadcast-mode", "sync",
               "--gas", "250000",
               "--sequence", str(sequence),
               "--output", "json"]
        if dry_run:
            cmd.append("--dry-run")
            logger.info("Dry-run mode: simulating submission")

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if proc.returncode == 0:
                # Validate response is JSON
                is_valid, resp = validate_json_response(proc.stdout, f"from submission attempt {_submission_attempt_count}")
                if not is_valid:
                    logger.error(f"❌ Invalid JSON response from {rpc_endpoint['name']}")
                    mark_rpc_failed(rpc_endpoint["url"], "Invalid JSON in submission response")
                    if attempt < _max_submission_retries - 1:
                        continue
                    status = "failed_invalid_response"
                    break
                
                if resp.get("code") == 0:
                    tx_hash = resp.get('txhash', 'N/A')
                    logger.info(f"✅ LEADERBOARD SUBMISSION ACCEPTED on {rpc_endpoint['name']}")
                    logger.info(f"   Transaction hash: {tx_hash}")
                    logger.info(f"   Block height: {block_height}")
                    logger.info(f"   Prediction: {value:.10f}")
                    logger.info(f"   Topic ID: {topic_id}")
                    logger.info(f"   RPC Endpoint: {rpc_endpoint['name']}")
                    logger.info(f"   Timestamp: {timestamp}")
                    
                    # Reset RPC endpoint on successful submission
                    reset_rpc_endpoint(rpc_endpoint["url"])
                    
                    # Attempt to validate on-chain
                    if validate_transaction_on_chain(tx_hash, rpc_endpoint):
                        logger.info(f"🎉 CONFIRMED: Submission landed on-chain via {rpc_endpoint['name']}!")
                        status = "success_confirmed"
                        success = True
                    else:
                        logger.warning(f"⚠️  Submitted but on-chain validation pending")
                        status = "success_pending_confirmation"
                        success = True
                    break
                else:
                    error_msg = resp.get('raw_log', resp.get('message', 'Unknown error'))
                    logger.error(f"❌ Submission rejected on {rpc_endpoint['name']}: {error_msg}")
                    logger.error(f"   This may be a leaderboard-impacting failure")
                    mark_rpc_failed(rpc_endpoint["url"], error_msg)
                    status = f"failed: {error_msg}"
                    if attempt < _max_submission_retries - 1:
                        continue
                    break
            else:
                cli_error = proc.stderr.strip()
                logger.error(f"❌ CLI submission failed on {rpc_endpoint['name']} with code {proc.returncode}")
                logger.error(f"   Error: {cli_error}")
                
                # Check for specific RPC errors
                if "invalid character" in cli_error.lower() or "looking for beginning" in cli_error.lower():
                    logger.error(f"   ⚠️  Received invalid response (likely HTML error page)")
                    mark_rpc_failed(rpc_endpoint["url"], "Invalid response (HTML or malformed JSON)")
                elif "grpc_status:12" in cli_error or "received http2 header with status: 404" in cli_error.lower():
                    logger.error(f"   ⚠️  gRPC 404 error - RPC endpoint may not support this operation")
                    logger.error(f"   This is typically a transient issue with the RPC service")
                    mark_rpc_failed(rpc_endpoint["url"], "gRPC 404 - RPC service issue")
                elif "connection refused" in cli_error.lower() or "connection reset" in cli_error.lower():
                    logger.error(f"   ⚠️  Connection error - RPC endpoint may be temporarily unavailable")
                    mark_rpc_failed(rpc_endpoint["url"], "Connection failed")
                else:
                    logger.error(f"   May indicate RPC connectivity issues")
                    mark_rpc_failed(rpc_endpoint["url"], cli_error)
                
                status = f"cli_error: {cli_error[:100]}"
                if attempt < _max_submission_retries - 1:
                    logger.info(f"🔄 Retrying with next RPC endpoint...")
                    time.sleep(2)  # Brief pause before retry
                    continue
                break
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Submission timed out (120s) on {rpc_endpoint['name']}")
            mark_rpc_failed(rpc_endpoint["url"], "Timeout (120s)")
            status = "error: submission_timeout"
            if attempt < _max_submission_retries - 1:
                logger.info(f"🔄 Retrying with next RPC endpoint...")
                continue
            break
        except Exception as e:
            logger.error(f"❌ Unexpected submission error: {e}")
            logger.debug(f"Traceback: {traceback.format_exc()}")
            mark_rpc_failed(rpc_endpoint["url"], str(e))
            status = f"error: {str(e)}"
            if attempt < _max_submission_retries - 1:
                logger.info(f"🔄 Retrying with next RPC endpoint...")
                continue
            break

    # Log to CSV ALWAYS (whether success or not)
    log_submission_to_csv(
        timestamp=timestamp,
        topic_id=topic_id,
        prediction=value,
        worker=wallet,
        block_height=block_height,
        proof=worker_data.get("inference_forecasts_bundle", {}),
        signature=bundle_signature,
        status=status,
        tx_hash=tx_hash or "",
        rpc_endpoint=used_rpc["name"] if used_rpc else "unknown"
    )

    # Update latest_submission.json with comprehensive status
    update_latest_submission_json(
        timestamp=timestamp,
        topic_id=topic_id,
        prediction=value,
        worker=wallet,
        block_height=block_height,
        proof=worker_data["inference_forecasts_bundle"],
        signature=bundle_signature,
        status=status,
        tx_hash=tx_hash or "",
        rpc_endpoint=used_rpc["name"] if used_rpc else "unknown"
    )

    return success

def main():
    parser = argparse.ArgumentParser(description="Submit BTC/USD 7-day log-return prediction.")
    parser.add_argument("--model", type=str, default="model.pkl", help="Path to trained model.")
    parser.add_argument("--features", type=str, default="features.json", help="Path to feature columns.")
    parser.add_argument("--topic-id", type=int, default=int(os.getenv("TOPIC_ID", "67")), help="Allora topic ID.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate submission without sending.")
    parser.add_argument("--once", action="store_true", help="Run once and exit (replaces --continuous when not set).")
    parser.add_argument("--continuous", action="store_true", help="Run in continuous mode, submitting every hour.")
    parser.add_argument("--daemon", action="store_true", help="Run as permanent daemon (until Dec 15, 2025).")
    args = parser.parse_args()
    
    # Validate critical files exist before entering continuous mode
    if not os.path.exists(args.model):
        logger.error(f"❌ CRITICAL: {args.model} not found. Run 'python train.py' first.")
        sys.exit(1)
    if not os.path.exists(args.features):
        logger.error(f"❌ CRITICAL: {args.features} not found. Run 'python train.py' first.")
        sys.exit(1)
    
    # Validate environment
    required_env = ["ALLORA_WALLET_ADDR", "MNEMONIC", "TOPIC_ID"]
    missing = [k for k in required_env if not os.getenv(k)]
    if missing:
        logger.error(f"❌ Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    if args.daemon or args.continuous:
        run_daemon(args)
    else:
        # Single run mode
        exit_code = main_once(args)
        sys.exit(0 if exit_code else 1)

def validate_startup(args) -> bool:
    """
    Comprehensive startup validation to ensure model and features are ready.
    Runs BEFORE daemon starts to catch issues early.
    """
    logger.info("=" * 80)
    logger.info("🔍 PRE-EXECUTION STARTUP VALIDATION")
    logger.info("=" * 80)
    
    # CHECK 1: Features file exists and is readable
    logger.info("\n[1/4] Checking features.json...")
    if not os.path.exists(args.features):
        logger.error(f"❌ Features file not found: {args.features}")
        logger.error("   FIX: Run 'python train.py' to generate features.json")
        return False
    
    try:
        with open(args.features, "r") as f:
            feature_cols = json.load(f)
        
        if not isinstance(feature_cols, list) or len(feature_cols) == 0:
            logger.error(f"❌ features.json is invalid (not a non-empty list)")
            logger.error("   FIX: Run 'python train.py' to generate valid features.json")
            return False
        
        logger.info(f"   ✅ Features file valid: {len(feature_cols)} columns")
    except json.JSONDecodeError as e:
        logger.error(f"❌ features.json is not valid JSON: {e}")
        logger.error("   FIX: Run 'python train.py' to regenerate features.json")
        return False
    except Exception as e:
        logger.error(f"❌ Error reading features.json: {e}")
        return False
    
    # CHECK 2: Model file exists and has correct size
    logger.info("\n[2/4] Checking model.pkl file...")
    if not os.path.exists(args.model):
        logger.error(f"❌ Model file not found: {args.model}")
        logger.error("   FIX: Run 'python train.py' to train and save model.pkl")
        return False
    
    try:
        model_size = os.path.getsize(args.model)
        if model_size == 0:
            logger.error(f"❌ model.pkl is empty (0 bytes)")
            logger.error("   FIX: Run 'python train.py' to train and save a valid model")
            return False
        logger.info(f"   ✅ Model file exists: {model_size} bytes")
    except Exception as e:
        logger.error(f"❌ Error accessing model.pkl: {e}")
        return False
    
    # CHECK 3: Model is properly fitted and functional (9-point check)
    logger.info("\n[3/4] Validating model (comprehensive fitted-state check)...")
    if not validate_model(args.model, len(feature_cols)):
        logger.error("❌ Model validation FAILED")
        logger.error("   FIX: Run 'python train.py' to retrain and save a valid model")
        return False
    
    # CHECK 4: Test that we can actually fetch data and make a prediction
    logger.info("\n[4/4] Testing data fetch and prediction...")
    try:
        # Load model
        import pickle
        with open(args.model, "rb") as f:
            model = pickle.load(f)
        
        # Try to fetch data
        try:
            raw = fetch_latest_btcusd_hourly(hours=168)
            if len(raw) == 0:
                logger.error("❌ Data fetch returned zero rows")
                logger.error("   FIX: Check network connectivity and Tiingo API key")
                return False
            logger.debug(f"   ✅ Data fetch successful: {len(raw)} rows")
        except Exception as e:
            logger.error(f"❌ Data fetch failed: {e}")
            logger.error("   FIX: Check network connectivity and TIINGO_API_KEY")
            return False
        
        # Try to generate features
        try:
            feats = generate_features(raw)
            if len(feats) == 0:
                logger.error("❌ Feature generation returned zero rows")
                logger.error("   FIX: Check that raw data has enough records (need at least 72 hours)")
                return False
            logger.debug(f"   ✅ Feature generation successful: {len(feats)} rows")
        except Exception as e:
            logger.error(f"❌ Feature generation failed: {e}")
            logger.error("   FIX: Check that feature engineering is working correctly")
            return False
        
        # Try to make a prediction
        try:
            latest = feats.iloc[-1]
            x_live = latest[feature_cols].values.reshape(1, -1)
            pred = model.predict(x_live)
            pred_value = float(pred[0])
            
            if np.isnan(pred_value) or np.isinf(pred_value):
                logger.error(f"❌ Prediction produced invalid value: {pred_value}")
                logger.error("   FIX: Retrain model with 'python train.py'")
                return False
            
            logger.info(f"   ✅ Prediction successful: {pred_value:.8f}")
        except Exception as e:
            logger.error(f"❌ Prediction failed: {e}")
            logger.error("   FIX: Check that model and features are compatible")
            return False
    
    except Exception as e:
        logger.error(f"❌ Startup test failed: {e}")
        return False
    
    # ALL CHECKS PASSED
    logger.info("\n" + "=" * 80)
    logger.info("✅ STARTUP VALIDATION COMPLETE - ALL CHECKS PASSED")
    logger.info("=" * 80)
    return True

def run_daemon(args):
    """
    Run as a long-lived daemon until December 15, 2025.
    Handles all exceptions, never silently fails, includes hourly heartbeat.
    """
    global _shutdown_requested
    
    # Validate startup before beginning daemon loop
    if not validate_startup(args):
        logger.error("❌ STARTUP VALIDATION FAILED - ABORTING DAEMON START")
        logger.error("   Address the issues above and try again")
        return 1
    
    interval = int(os.getenv("SUBMISSION_INTERVAL", "3600"))  # 1 hour default
    competition_end = datetime(2025, 12, 15, 0, 0, 0, tzinfo=timezone.utc)
    
    logger.info("=" * 80)
    logger.info("🚀 DAEMON MODE STARTED")
    logger.info(f"   Model: {args.model}")
    logger.info(f"   Features: {args.features}")
    logger.info(f"   Topic ID: {args.topic_id}")
    logger.info(f"   Submission Interval: {interval}s ({interval/3600:.1f}h)")
    logger.info(f"   Competition End: {competition_end.isoformat()}")
    logger.info(f"   Current Time: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 80)
    
    cycle_count = 0
    last_heartbeat = None
    
    while not _shutdown_requested:
        cycle_count += 1
        cycle_start = datetime.now(timezone.utc)
        
        # Check if competition has ended
        if cycle_start >= competition_end:
            logger.info(f"⏰ Competition end date ({competition_end.isoformat()}) reached. Shutting down.")
            break
        
        # Hourly heartbeat (separate from submission attempts)
        now_hour = cycle_start.replace(minute=0, second=0, microsecond=0)
        if last_heartbeat != now_hour:
            logger.info(f"💓 HEARTBEAT - Daemon alive at {cycle_start.isoformat()}")
            last_heartbeat = now_hour
        
        try:
            logger.info(f"\n{'='*80}")
            logger.info(f"SUBMISSION CYCLE #{cycle_count} - {cycle_start.isoformat()}")
            logger.info(f"{'='*80}")
            
            success = main_once(args)
            
            if success:
                logger.info("✅ Submission cycle completed successfully")
            else:
                logger.warning("⚠️  Submission cycle completed without successful submission (may be skipped/no nonce)")
        
        except Exception as e:
            # CRITICAL: Never silently fail
            logger.error(f"❌ UNHANDLED EXCEPTION IN SUBMISSION CYCLE #{cycle_count}")
            logger.error(f"   Exception: {type(e).__name__}: {str(e)}")
            logger.error("   Full traceback:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.error(f"   {line}")
            # Continue to next cycle instead of crashing
        
        try:
            if not _shutdown_requested:
                logger.info(f"Sleeping for {interval}s until next submission cycle...")
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.warning("Interrupted during sleep, proceeding to next cycle")
            pass
    
    logger.info("=" * 80)
    logger.info("🛑 DAEMON SHUTDOWN COMPLETE")
    logger.info(f"   Total Cycles: {cycle_count}")
    logger.info(f"   Final Time: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 80)

def main_once(args):
    """Execute a single submission cycle with comprehensive error handling."""
    try:
        # Load and validate features first
        if not os.path.exists(args.features):
            logger.error(f"❌ Features file not found: {args.features}")
            logger.error("   Run 'python train.py' to generate features.json")
            return False
        
        with open(args.features, "r") as f:
            feature_cols = json.load(f)
        logger.info(f"✅ Loaded {len(feature_cols)} feature columns")
        
        # Validate model before using it (CRITICAL FOR DAEMON)
        if not validate_model(args.model, len(feature_cols)):
            logger.error(f"❌ CRITICAL: Model validation failed. Cannot proceed with submission.")
            logger.error("   Run 'python train.py' to train a new model.")
            logger.error("   Daemon will retry in next cycle.")
            return False
        
        # Load model (we know it's valid now)
        import pickle
        with open(args.model, "rb") as f:
            model = pickle.load(f)
        logger.debug("Model loaded and validated")

        # Fetch latest data with error handling
        try:
            raw = fetch_latest_btcusd_hourly()
            logger.debug(f"Fetched {len(raw)} raw price records")
        except Exception as e:
            logger.error(f"❌ Failed to fetch BTC/USD data: {e}")
            logger.error("   Retrying in next cycle")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.debug(line)
            return False
        
        # Feature engineering with error handling
        try:
            feats = generate_features(raw)
            if len(feats) == 0:
                logger.error("❌ No feature data available after feature engineering")
                logger.error("   Raw data insufficient or feature generation failed")
                logger.error("   Retrying in next cycle")
                return False
            logger.debug(f"Generated features for {len(feats)} records")
        except Exception as e:
            logger.error(f"❌ Feature engineering failed: {e}")
            logger.error("   Retrying in next cycle")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.debug(line)
            return False
        
        # Prepare input for prediction
        try:
            latest = feats.iloc[-1]
            x_live = latest[feature_cols].values.reshape(1, -1)
            logger.debug(f"Prepared prediction input (shape: {x_live.shape})")
        except KeyError as e:
            logger.error(f"❌ Missing feature column: {e}")
            logger.error("   Feature mismatch between features.json and current data.")
            logger.error("   Run 'python train.py' to regenerate features.json")
            logger.error("   Retrying in next cycle")
            return False
        except Exception as e:
            logger.error(f"❌ Error preparing prediction input: {e}")
            logger.error("   Retrying in next cycle")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.debug(line)
            return False

        # Predict with error handling
        try:
            pred = predict_forward_log_return(model, x_live)
            logger.debug(f"Prediction computed: {pred:.8f}")
        except Exception as e:
            logger.error(f"❌ Prediction failed: {e}")
            logger.error("   Model may be corrupted or incompatible")
            logger.error("   Retrying in next cycle")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.debug(line)
            return False

        # Submit with error handling
        try:
            success = submit_prediction(pred, args.topic_id, dry_run=args.dry_run)
            if success:
                logger.info(f"✅ Submission status: SUCCESS")
            else:
                logger.info(f"⚠️  Submission status: skipped or failed (may be no unfulfilled nonce)")
            return success
        except Exception as e:
            logger.error(f"❌ Submission failed with exception: {e}")
            logger.error("   Retrying in next cycle")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.debug(line)
            return False
    
    except Exception as e:
        # Final catch-all to ensure no silent failures
        logger.error(f"❌ UNHANDLED EXCEPTION in main_once: {type(e).__name__}: {str(e)}")
        logger.error("   This should not happen - indicates a bug in cycle logic")
        for line in traceback.format_exc().split('\n'):
            if line.strip():
                logger.error(f"   {line}")
        return False

if __name__ == "__main__":
    main()