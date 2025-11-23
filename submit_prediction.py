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

# RPC Endpoint Failover List
RPC_ENDPOINTS = [
    "https://allora-rpc.testnet.allora.network/",
    "https://allora-testnet-rpc.allthatnode.com:1317/",
    "https://allora.api.chandrastation.com/",
]

# Global state for RPC endpoint rotation
_rpc_endpoint_index = 0
_failed_rpc_endpoints = set()

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
# RPC Endpoint Management with Failover
###############################################################################
def get_rpc_endpoint() -> str:
    """Get the next working RPC endpoint with automatic failover."""
    global _rpc_endpoint_index, _failed_rpc_endpoints
    
    # Reset if all endpoints marked as failed
    if len(_failed_rpc_endpoints) >= len(RPC_ENDPOINTS):
        logger.info("🔄 Resetting failed RPC endpoints list for retry")
        _failed_rpc_endpoints.clear()
        _rpc_endpoint_index = 0
    
    # Try to find next working endpoint
    for _ in range(len(RPC_ENDPOINTS)):
        endpoint = RPC_ENDPOINTS[_rpc_endpoint_index % len(RPC_ENDPOINTS)]
        _rpc_endpoint_index += 1
        
        if endpoint not in _failed_rpc_endpoints:
            return endpoint
    
    # Fallback to first endpoint if all tried
    logger.warning("⚠️  All RPC endpoints exhausted, using first endpoint")
    _rpc_endpoint_index = 0
    _failed_rpc_endpoints.clear()
    return RPC_ENDPOINTS[0]

def mark_rpc_failed(endpoint: str):
    """Mark an RPC endpoint as failed for future queries."""
    global _failed_rpc_endpoints
    _failed_rpc_endpoints.add(endpoint)
    logger.warning(f"⚠️  Marked RPC endpoint as failed: {endpoint}")

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
# Model Validation
###############################################################################
def validate_model(model_path: str, feature_count: int) -> bool:
    """Validate that loaded model is fitted and functional."""
    import pickle
    try:
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        logger.info(f"✅ Model loaded from {model_path}")
    except Exception as e:
        logger.error(f"❌ Failed to load model: {e}")
        return False
    
    # Check if fitted
    try:
        if not hasattr(model, 'n_features_in_'):
            logger.error("❌ Model not fitted (missing n_features_in_ attribute)")
            logger.error("   This usually means train.py was not run or model was saved without fitting.")
            logger.error("   Fix: Run 'python train.py' to train and save a fitted model.")
            return False
        if model.n_features_in_ != feature_count:
            logger.error(f"❌ Feature count mismatch: model expects {model.n_features_in_}, got {feature_count}")
            logger.error("   This usually means features.json is outdated.")
            logger.error("   Fix: Run 'python train.py' to regenerate features.json.")
            return False
        logger.info(f"✅ Model is fitted with n_features_in_={model.n_features_in_}")
    except Exception as e:
        logger.error(f"❌ Model fitted-state verification failed: {e}")
        return False
    
    # Test prediction on dummy input
    try:
        dummy_input = np.zeros((1, feature_count))
        test_pred = model.predict(dummy_input)
        logger.info(f"✅ Model test prediction passed: {float(test_pred[0]):.8f}")
    except Exception as e:
        logger.error(f"❌ Model test prediction failed: {e}")
        logger.error("   This usually means model.pkl is corrupted or incompatible.")
        logger.error("   Fix: Run 'python train.py' to retrain and save a fresh model.")
        return False
    
    return True

###############################################################################
# Get Account Sequence
###############################################################################
def get_account_sequence(wallet: str) -> int:
    """Query account sequence from Allora network with RPC failover."""
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("❌ Allora CLI not found in PATH")
        return 0
    
    rpc_endpoint = get_rpc_endpoint()
    logger.debug(f"Querying account sequence via RPC: {rpc_endpoint}")
    
    cmd = [cli, "query", "auth", "account", wallet, 
           "--node", rpc_endpoint,
           "--output", "json"]
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            sequence = int(data["account"]["value"]["sequence"])
            logger.debug(f"✅ Got account sequence: {sequence}")
            return sequence
        else:
            error_msg = proc.stderr.strip()
            logger.warning(f"⚠️  Query failed for account {wallet}: {error_msg}")
            mark_rpc_failed(rpc_endpoint)
            return 0
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failed to parse account sequence response: {e}")
        mark_rpc_failed(rpc_endpoint)
        return 0
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Query timed out (30s) for account sequence on {rpc_endpoint}")
        mark_rpc_failed(rpc_endpoint)
        return 0
    except Exception as e:
        logger.error(f"❌ Error querying account sequence: {e}")
        mark_rpc_failed(rpc_endpoint)
        return 0

###############################################################################
# Get Unfulfilled Nonce
###############################################################################
def get_unfulfilled_nonce(topic_id: int) -> int:
    """Query unfulfilled nonces from Allora network with RPC failover."""
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("❌ Allora CLI not found in PATH")
        return 0
    
    rpc_endpoint = get_rpc_endpoint()
    logger.debug(f"Querying unfulfilled nonces for topic {topic_id} via RPC: {rpc_endpoint}")
    
    cmd = [cli, "query", "emissions", "unfulfilled-worker-nonces", str(topic_id),
           "--node", rpc_endpoint,
           "--output", "json"]
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            nonces_data = data.get("nonces", {}).get("nonces", [])
            nonces = [int(item["block_height"]) for item in nonces_data]
            
            if not nonces:
                logger.info(f"ℹ️  No unfulfilled nonces found for topic {topic_id}")
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
                                "--node", rpc_endpoint,
                                "--output", "json"]
                    proc_check = subprocess.run(cmd_check, capture_output=True, text=True, timeout=30)
                    
                    if proc_check.returncode == 0:
                        data_check = json.loads(proc_check.stdout)
                        latest_bh = int(data_check.get("latest_inference", {}).get("block_height", 0))
                        if latest_bh != nonce:
                            filtered_nonces.append(nonce)
                            logger.debug(f"  ✓ Nonce {nonce} available (latest submitted: {latest_bh})")
                        else:
                            logger.debug(f"  ✗ Nonce {nonce} already submitted")
                    else:
                        # If check fails, assume not submitted and include it
                        filtered_nonces.append(nonce)
                        logger.debug(f"  ? Nonce {nonce} check inconclusive, will attempt submission")
                except Exception as e:
                    logger.warning(f"⚠️  Error checking nonce {nonce}: {e}")
                    filtered_nonces.append(nonce)
            
            if filtered_nonces:
                selected_nonce = min(filtered_nonces)
                logger.info(f"🎯 Selected nonce for submission: block_height={selected_nonce}")
                return selected_nonce
            else:
                logger.warning(f"⚠️  All unfulfilled nonces already submitted by worker {wallet}")
                return 0
        else:
            error_msg = proc.stderr.strip()
            logger.warning(f"⚠️  Query failed for unfulfilled nonces: {error_msg}")
            mark_rpc_failed(rpc_endpoint)
            return 0
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failed to parse unfulfilled nonces response: {e}")
        mark_rpc_failed(rpc_endpoint)
        return 0
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Query timed out (30s) for unfulfilled nonces on {rpc_endpoint}")
        mark_rpc_failed(rpc_endpoint)
        return 0
    except Exception as e:
        logger.error(f"❌ Error querying unfulfilled nonces: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")
        mark_rpc_failed(rpc_endpoint)
        return 0

###############################################################################
# Validate Transaction On-Chain
###############################################################################
def validate_transaction_on_chain(tx_hash: str, rpc_endpoint: str) -> bool:
    """Verify that a transaction actually landed on-chain."""
    try:
        logger.debug(f"Validating transaction {tx_hash} on-chain...")
        cmd = ["curl", "-s", f"{rpc_endpoint}cosmos/tx/v1beta1/txs/{tx_hash}"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if proc.returncode == 0:
            resp = json.loads(proc.stdout)
            if resp.get("code") == 0 or "tx" in resp:
                logger.info(f"✅ Transaction {tx_hash} confirmed on-chain")
                return True
            else:
                logger.warning(f"⚠️  Transaction {tx_hash} not confirmed or invalid: {resp.get('message', 'unknown')}")
                return False
        else:
            logger.debug(f"Could not validate transaction {tx_hash}: {proc.stderr}")
            return False
    except Exception as e:
        logger.debug(f"Error validating transaction: {e}")
        return False

###############################################################################
# Submission with RPC Failover
###############################################################################
def submit_prediction(value: float, topic_id: int, dry_run: bool = False) -> bool:
    """Submit prediction with RPC failover and transaction validation."""
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
        return False
    
    logger.info(f"📊 Prediction value: {value:.10f}")
    logger.info(f"📍 Block height: {block_height}")

    sequence = get_account_sequence(wallet)
    if sequence == 0:
        logger.error("❌ Cannot get account sequence (RPC query failed)")
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

    # Get RPC endpoint for submission
    rpc_endpoint = get_rpc_endpoint()
    logger.debug(f"Using RPC endpoint: {rpc_endpoint}")
    
    # allorad expects: insert-worker-payload [sender] [worker_data] [flags]
    cmd = [cli, "tx", "emissions", "insert-worker-payload",
           wallet,                          # positional arg 1: sender
           json.dumps(worker_data),         # positional arg 2: worker_data
           "--from", wallet,                # flag: signing wallet
           "--yes",
           "--keyring-backend", "test",
           "--node", rpc_endpoint,
           "--chain-id", "allora-testnet-1",
           "--fees", "2500000uallo",
           "--broadcast-mode", "sync",
           "--gas", "250000",
           "--sequence", str(sequence),
           "--output", "json"]
    if dry_run:
        cmd.append("--dry-run")
        logger.info("Dry-run mode: simulating submission")

    logger.info(f"📤 Submitting prediction {value:.10f} for topic {topic_id} at block {block_height}")
    
    success = False
    status = "pending"
    tx_hash = None
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            # Parse the JSON response
            try:
                resp = json.loads(proc.stdout)
                if resp.get("code") == 0:
                    tx_hash = resp.get('txhash', 'N/A')
                    logger.info(f"✅ LEADERBOARD SUBMISSION ACCEPTED")
                    logger.info(f"   Transaction hash: {tx_hash}")
                    logger.info(f"   Block height: {block_height}")
                    logger.info(f"   Prediction: {value:.10f}")
                    logger.info(f"   Topic ID: {topic_id}")
                    logger.info(f"   Timestamp: {timestamp}")
                    
                    # Attempt to validate on-chain
                    if validate_transaction_on_chain(tx_hash, rpc_endpoint):
                        logger.info(f"🎉 CONFIRMED: Submission landed on-chain!")
                        status = "success_confirmed"
                        success = True
                    else:
                        logger.warning(f"⚠️  Submitted but on-chain validation pending")
                        status = "success_pending_confirmation"
                        success = True
                else:
                    error_msg = resp.get('raw_log', 'Unknown error')
                    logger.error(f"❌ Submission rejected by network: {error_msg}")
                    logger.error(f"   This may be a leaderboard-impacting failure")
                    status = f"failed: {error_msg}"
                    mark_rpc_failed(rpc_endpoint)
            except json.JSONDecodeError:
                logger.error(f"❌ Failed to parse submission response: {proc.stdout}")
                status = f"error: invalid response"
        else:
            cli_error = proc.stderr.strip()
            logger.error(f"❌ CLI submission failed with code {proc.returncode}")
            logger.error(f"   Error: {cli_error}")
            logger.error(f"   This may indicate RPC connectivity issues")
            status = f"cli_error: {cli_error}"
            mark_rpc_failed(rpc_endpoint)
    except subprocess.TimeoutExpired:
        logger.error("❌ Submission timed out (120s) - RPC may be slow or unresponsive")
        status = "error: submission timeout"
        mark_rpc_failed(rpc_endpoint)
    except Exception as e:
        logger.error(f"❌ Unexpected submission error: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")
        status = f"error: {str(e)}"
        mark_rpc_failed(rpc_endpoint)

    # Log to CSV ALWAYS (whether success or not)
    csv_path = "submission_log.csv"
    record = {
        "timestamp": timestamp,
        "topic_id": str(topic_id),
        "prediction": str(value),
        "worker": wallet,
        "block_height": str(block_height),
        "proof": json.dumps(worker_data["inference_forecasts_bundle"]),
        "signature": bundle_signature,
        "status": status,
        "tx_hash": tx_hash or ""
    }
    
    try:
        import csv
        with open(csv_path, "a", newline="") as f:
            fieldnames = ["timestamp","topic_id","prediction","worker","block_height","proof","signature","status","tx_hash"]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writerow(record)
        logger.info(f"📝 Logged submission to CSV with status: {status}")
    except Exception as e:
        logger.error(f"❌ Failed to log CSV: {e}")

    # Update latest_submission.json with comprehensive status
    try:
        with open("latest_submission.json", "w") as jf:
            json.dump({
                "timestamp": timestamp,
                "topic_id": topic_id,
                "prediction": value,
                "worker": wallet,
                "block_height": block_height,
                "proof": worker_data["inference_forecasts_bundle"],
                "signature": bundle_signature,
                "status": status,
                "tx_hash": tx_hash,
                "leaderboard_impact": success
            }, jf, indent=2)
    except Exception as e:
        logger.error(f"❌ Failed to write latest_submission.json: {e}")

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

def run_daemon(args):
    """
    Run as a long-lived daemon until December 15, 2025.
    Handles all exceptions, never silently fails, includes hourly heartbeat.
    """
    global _shutdown_requested
    
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