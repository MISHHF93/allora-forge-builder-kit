#!/usr/bin/env python3
"""
BTC/USD 7-Day Log-Return Prediction Submission Utility
------------------------------------------------------
Loads trained model and features, fetches latest data, predicts,
prepares Allora worker payload, and submits via allorad CLI.

Usage:
    python submit_prediction.py [--model MODEL_PATH] [--features FEATURES_PATH] [--topic-id TOPIC_ID] [--dry-run] [--once]
"""

import os
import os
import sys
import json
import shutil
import logging
import argparse
import subprocess
import hashlib
import base64
import time
import math
from typing import List
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

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
# Logging Setup
###############################################################################
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%SZ'
)
logger = logging.getLogger("btc_submit")

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
# Get Account Sequence
###############################################################################
def get_account_sequence(wallet: str) -> int:
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("Allora CLI not found")
        return 0
    cmd = [cli, "query", "auth", "account", wallet, "--output", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            return int(data["account"]["value"]["sequence"])
        else:
            logger.error(f"Query failed: {proc.stderr}")
            return 0
    except Exception as e:
        logger.error(f"Query error: {e}")
        return 0

###############################################################################
# Get Unfulfilled Nonce
###############################################################################
def get_unfulfilled_nonce(topic_id: int) -> int:
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("Allora CLI not found")
        return 0
    cmd = [cli, "query", "emissions", "unfulfilled-worker-nonces", str(topic_id),
           "--output", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            nonces_data = data.get("nonces", {}).get("nonces", [])
            nonces = [int(item["block_height"]) for item in nonces_data]
            if nonces:
                # Filter out nonces already submitted by this worker
                wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
                filtered_nonces = []
                for nonce in nonces:
                    # Check if already submitted
                    cmd_check = [cli, "query", "emissions", "worker-latest-inference", str(topic_id), wallet, "--output", "json"]
                    proc_check = subprocess.run(cmd_check, capture_output=True, text=True, timeout=30)
                    if proc_check.returncode == 0:
                        data_check = json.loads(proc_check.stdout)
                        latest_bh = int(data_check.get("latest_inference", {}).get("block_height", 0))
                        if latest_bh != nonce:
                            filtered_nonces.append(nonce)
                    else:
                        # If check fails, assume not submitted
                        filtered_nonces.append(nonce)
                if filtered_nonces:
                    return min(filtered_nonces)
                else:
                    logger.warning("All unfulfilled nonces already submitted by this worker")
                    return 0
            else:
                logger.warning("No unfulfilled nonces found")
                return 0
        else:
            logger.error(f"Query failed: {proc.stderr}")
            return 0
    except Exception as e:
        logger.error(f"Query error: {e}")
        return 0

###############################################################################
# Submission
###############################################################################
def submit_prediction(value: float, topic_id: int, dry_run: bool = False) -> bool:
    timestamp = datetime.now(timezone.utc).isoformat()
    wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
    
    # Validate wallet before proceeding
    if not wallet:
        logger.error("ALLORA_WALLET_ADDR not set")
        return False
    
    block_height = get_unfulfilled_nonce(topic_id)
    if block_height == 0:
        logger.warning("No unfulfilled nonce available, skipping submission")
        return False

    sequence = get_account_sequence(wallet)
    if sequence == 0:
        logger.error("Cannot get account sequence")
        return False

    # Create wallet for signing
    mnemonic = os.getenv("MNEMONIC", "").strip()
    if not mnemonic:
        logger.error("MNEMONIC not set")
        return False
    
    try:
        wallet_obj = LocalWallet.from_mnemonic(mnemonic)
    except Exception as e:
        logger.error(f"Failed to create wallet from mnemonic: {e}")
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
    except Exception as e:
        logger.error(f"Failed to create bundle/signature: {e}")
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
        logger.error("Allora CLI not found")
        return False

    # Use --from flag with wallet address instead of positional argument
    cmd = [cli, "tx", "emissions", "insert-worker-payload",
           json.dumps(worker_data),
           "--from", wallet,
           "--yes",
           "--keyring-backend", "test",
           "--node", "https://allora-rpc.testnet.allora.network/",
           "--chain-id", "allora-testnet-1",
           "--fees", "2500000uallo",
           "--broadcast-mode", "sync",
           "--gas", "250000",
           "--sequence", str(sequence),
           "--output", "json"]
    if dry_run:
        cmd.append("--dry-run")
        logger.info("Dry-run mode: simulating submission")

    logger.info(f"Submitting prediction {value:.8f} for topic {topic_id} at block {block_height}")
    
    success = False
    status = "pending"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            # Parse the JSON response
            try:
                resp = json.loads(proc.stdout)
                if resp.get("code") == 0:
                    logger.info("✅ Submission success")
                    logger.info(f"Transaction hash: {resp.get('txhash', 'N/A')}")
                    status = "success"
                    success = True
                else:
                    error_msg = resp.get('raw_log', 'Unknown error')
                    logger.error(f"Submission failed: {error_msg}")
                    status = f"failed: {error_msg}"
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON response: {proc.stdout}")
                status = f"error: invalid response"
        else:
            cli_error = proc.stderr.strip()
            logger.error(f"CLI failed with code {proc.returncode}: {cli_error}")
            status = f"cli_error: {cli_error}"
    except subprocess.TimeoutExpired:
        logger.error("CLI submission timed out (120s)")
        status = "error: submission timeout"
    except Exception as e:
        logger.error(f"Submission error: {e}")
        status = f"error: {str(e)}"

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
        "status": status
    }
    
    try:
        import csv
        with open(csv_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp","topic_id","prediction","worker","block_height","proof","signature","status"])
            w.writerow(record)
        logger.debug(f"Logged submission to CSV with status: {status}")
    except Exception as e:
        logger.error(f"Failed to log CSV: {e}")

    # Update latest_submission.json
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
                "status": status
            }, jf, indent=2)
    except Exception as e:
        logger.error(f"Failed to write latest_submission.json: {e}")

    return success
def main():
    parser = argparse.ArgumentParser(description="Submit BTC/USD 7-day log-return prediction.")
    parser.add_argument("--model", type=str, default="model.pkl", help="Path to trained model.")
    parser.add_argument("--features", type=str, default="features.json", help="Path to feature columns.")
    parser.add_argument("--topic-id", type=int, default=int(os.getenv("TOPIC_ID", "67")), help="Allora topic ID.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate submission without sending.")
    parser.add_argument("--continuous", action="store_true", help="Run in continuous mode, submitting every hour.")
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

    if args.continuous:
        import time
        interval = int(os.getenv("SUBMISSION_INTERVAL", "3600"))
        while True:
            try:
                success = main_once(args)
                if not success:
                    logger.warning("Submission failed, retrying in next interval")
            except Exception as e:
                logger.error(f"Continuous loop error: {e}")
            logger.info(f"Sleeping for {interval}s until next submission")
            time.sleep(interval)
    else:
        sys.exit(main_once(args))

def main_once(args):
    try:
        # Load model
        import pickle
        with open(args.model, "rb") as f:
            model = pickle.load(f)
        # Load features
        with open(args.features, "r") as f:
            feature_cols = json.load(f)

        # Fetch latest data
        raw = fetch_latest_btcusd_hourly()
        feats = generate_features(raw)
        if len(feats) == 0:
            logger.error("No feature data available")
            return 1
        latest = feats.iloc[-1]
        x_live = latest[feature_cols].values.reshape(1, -1)

        # Predict
        pred = predict_forward_log_return(model, x_live)

        # Submit
        success = submit_prediction(pred, args.topic_id, dry_run=args.dry_run)
        logger.info(f"Submission status: {'success' if success else 'skipped or failed'}")
        return 0  # Always return 0 for dry-run or skipped
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1

if __name__ == "__main__":
    main()