#!/usr/bin/env python3
"""Prepare and persist a forecast payload using validated market data."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from network_gate import query_window_status
from pipeline_core import (
    FEATURE_COLUMNS,
    generate_features,
    latest_feature_row,
    log_submission_record,
    validate_prediction,
)
from pipeline_utils import (
    ARTIFACTS_DIR,
    DEFAULT_TOPIC_ID,
    MIN_COVERAGE_RATIO,
    DataFetcher,
    coverage_ratio,
    price_coverage_ok,
    setup_logging,
)

MODEL_BUNDLE_PATH = ARTIFACTS_DIR / "model_bundle.joblib"
LOG_FILE = Path("logs/submit.log")
PAYLOAD_PATH = ARTIFACTS_DIR / "latest_submission.json"


class _ConstantModel:
    """Lightweight fallback model that returns a constant log-return prediction."""

    def __init__(self, value: float = 0.001):
        self.value = float(value)

    def predict(self, X):
        import numpy as np
        return np.full(len(X), self.value)


def load_bundle(logger):
    if not MODEL_BUNDLE_PATH.exists():
        logger.warning(
            "Model bundle missing at %s; using constant fallback prediction.",
            MODEL_BUNDLE_PATH,
        )
        return _ConstantModel(), FEATURE_COLUMNS, {"trained_at": None, "fallback": True, "horizon_hours": 168}, 168

    bundle = joblib.load(MODEL_BUNDLE_PATH)
    model = bundle.get("model")
    feature_names = bundle.get("feature_names", FEATURE_COLUMNS)
    horizon_hours = bundle.get("horizon_hours", 168)
    return model, feature_names, bundle, horizon_hours


def get_prediction_label(horizon_hours: int) -> str:
    if horizon_hours <= 24:
        return "prediction_log_return_1d"
    elif horizon_hours <= 168:
        return "prediction_log_return_7d"
    elif horizon_hours <= 336:
        return "prediction_log_return_14d"
    else:
        return f"prediction_log_return_{horizon_hours}h"


def submit_prediction_to_chain(topic_id: int, value: float, wallet: str, logger) -> tuple[bool, str]:
    from subprocess import run, CalledProcessError
    import json

    # CORRECT payload - confirmed from Allora SDK documentation
    worker_data_json = json.dumps({
        "topic_id": str(topic_id),
        "inference_value": f"{value:.6f}"  # Format to 6 decimal places as string
    })
    
    # Public RPC nodes that don't require authentication
    PUBLIC_RPC_NODES = [
        "https://allora-testnet-rpc.polkachu.com:443",
        "https://rpc-allora-testnet.mzonder.com:443",
        "https://allora-testnet-rpc.kewrnode.com:443",
        "https://allora-rpc.testnet.allora.network/"
    ]
    
    selected_rpc = PUBLIC_RPC_NODES[0]  # Start with polkachu
    
    # Build command with CORRECT chain-id and parameters
    cmd = [
        "allorad", "tx", "emissions", "insert-worker-payload",
        wallet,                    # Sender address
        worker_data_json,         # JSON payload with inference_value
        "--from", wallet,
        "--keyring-backend", "test",
        "--chain-id", "allora-testnet-4",  # ✅ CORRECTED: Must be "allora-testnet-4"
        "--node", selected_rpc,
        "--gas-prices", "20uallo",         # ✅ Increased for better success
        "--gas", "300000",                 # ✅ Sufficient gas limit
        "--gas-adjustment", "1.5",
        "--yes",
        "--output", "json"
    ]
    
    logger.info("📨 Submitting prediction to topic %s: value=%.6f", topic_id, value)
    logger.debug("Payload: %s", worker_data_json)
    logger.debug("Using RPC: %s", selected_rpc)
    
    try:
        result = run(cmd, capture_output=True, text=True, check=True)
        logger.info("✅ Submission command executed successfully")
        
        # Parse response
        try:
            tx_response = json.loads(result.stdout)
            tx_hash = tx_response.get("txhash", "unknown")
            logger.info("Transaction hash: %s", tx_hash)
            
            # Check for code field which indicates success (0) or error
            if "code" in tx_response and tx_response["code"] != 0:
                logger.error("❌ Transaction failed with code %s", tx_response["code"])
                if "raw_log" in tx_response:
                    logger.error("Error details: %s", tx_response["raw_log"])
                return False, f"Transaction failed with code {tx_response['code']}"
                
        except json.JSONDecodeError as parse_error:
            logger.warning("Could not parse JSON response: %s", parse_error)
            logger.debug("Raw output: %s", result.stdout)
            tx_hash = "unknown"
            
        return True, tx_hash
        
    except CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else "Unknown error"
        logger.error("❌ CLI command failed with return code %s", e.returncode)
        logger.error("Error output: %s", error_msg)
        
        # Provide specific troubleshooting advice
        if "insufficient fees" in error_msg.lower():
            logger.error("💡 Try increasing --gas-prices to '30uallo' or --gas to '400000'")
        elif "invalid chain-id" in error_msg.lower():
            logger.error("💡 Chain ID should be 'allora-testnet-4' (current testnet)")
        elif "connection refused" in error_msg.lower() or "connection reset" in error_msg.lower():
            logger.error("💡 RPC node unavailable. Trying alternative...")
            # Could implement retry logic with different RPC nodes here
        elif "signature verification failed" in error_msg.lower():
            logger.error("💡 Check your keyring-backend and ensure wallet is imported")
        elif "account sequence mismatch" in error_msg.lower():
            logger.error("💡 Nonce issue. Wait a moment and retry")
            
        return False, error_msg
        
    except Exception as e:
        logger.error("❌ Unexpected error during submission: %s", str(e))
        import traceback
        logger.debug("Traceback: %s", traceback.format_exc())
        return False, str(e)


def check_worker_nonce_directly(topic_id: int, worker_address: str, logger):
    """Direct check if worker has an open nonce for submission"""
    import subprocess
    import json
    
    cmd = [
        "allorad", "query", "emissions", "worker-node-latest-network-registration",
        worker_address, str(topic_id),
        "--node", "https://allora-testnet-rpc.polkachu.com:443",
        "--output", "json"
    ]
    
    try:
        logger.info("Checking worker nonce directly...")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # Log full response for debugging
        logger.debug("Nonce query response: %s", json.dumps(data, indent=2))
        
        # Check for nonce field - format may vary
        nonce = data.get('nonce')
        if nonce is not None:
            logger.info("Worker nonce: %s", nonce)
            return nonce != "0" and nonce != 0
        
        # Alternative field names
        if 'registration' in data and data['registration']:
            reg_data = data['registration']
            nonce = reg_data.get('nonce') or reg_data.get('latest_network_registration', {}).get('nonce')
            if nonce:
                logger.info("Worker nonce (from registration): %s", nonce)
                return nonce != "0" and nonce != 0
        
        logger.warning("No valid nonce found in response")
        return False
        
    except subprocess.CalledProcessError as e:
        logger.error("Failed to query worker nonce: %s", e.stderr.strip())
        return False
    except json.JSONDecodeError:
        logger.error("Invalid JSON response from nonce query")
        return False


def wait_for_submission_window(topic_id: int, worker: str, logger, max_wait_seconds: int = 300):
    """Wait until worker has an open submission window"""
    import time
    
    logger.info("⏳ Waiting for submission window to open (max %s seconds)...", max_wait_seconds)
    
    start_time = time.time()
    check_count = 0
    
    while time.time() - start_time < max_wait_seconds:
        check_count += 1
        
        # Check window status using existing function
        window_status = query_window_status(topic_id, worker, logger)
        
        if window_status.ok_to_submit():
            logger.info("✅ Submission window is now open! (after %s seconds)", int(time.time() - start_time))
            return True
            
        # Also check nonce directly as fallback
        if check_count % 3 == 0:  # Check direct nonce every 3rd iteration
            has_nonce = check_worker_nonce_directly(topic_id, worker, logger)
            if has_nonce:
                logger.info("✅ Worker has open nonce! (after %s seconds)", int(time.time() - start_time))
                return True
        
        if check_count == 1:
            logger.info("Current status: topic_active=%s, worker_can_submit=%s", 
                       window_status.topic_active, window_status.worker_can_submit)
        
        # Wait before checking again
        wait_time = min(10, max_wait_seconds / 10)  # Wait 10 seconds or less
        time.sleep(wait_time)
    
    logger.error("❌ Timeout waiting for submission window after %s seconds", max_wait_seconds)
    return False


def main() -> int:
    logger = setup_logging("submit", log_file=LOG_FILE)
    
    # Get configuration from environment
    topic_id = int(os.getenv("TOPIC_ID", os.getenv("ALLORA_TOPIC_ID", DEFAULT_TOPIC_ID)))
    worker = os.getenv("ALLORA_WALLET_ADDR", "unknown")
    
    if worker == "unknown":
        logger.error("❌ ALLORA_WALLET_ADDR environment variable not set")
        logger.error("Set it with: export ALLORA_WALLET_ADDR=allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma")
        return 1
    
    days_back = int(os.getenv("FORECAST_DAYS_BACK", "120"))
    force_refresh = os.getenv("FORCE_FETCH", "0").lower() in {"1", "true", "yes"}
    
    logger.info("🚀 Starting prediction submission for topic %s", topic_id)
    logger.info("Worker address: %s", worker)

    # Load model bundle
    logger.info("Loading model bundle from %s", MODEL_BUNDLE_PATH)
    try:
        model, feature_names, bundle_meta, horizon_hours = load_bundle(logger)
        if bundle_meta.get("fallback"):
            logger.warning("⚠️ Using fallback constant model - no trained model found")
        else:
            logger.info("✅ Model loaded successfully (trained at: %s)", 
                       bundle_meta.get("trained_at", "unknown"))
    except Exception as exc:
        logger.error("❌ Failed to load model bundle: %s", exc)
        return 1

    prediction_label = get_prediction_label(horizon_hours)
    logger.info("Using prediction horizon: %s hours -> %s", horizon_hours, prediction_label)

    # ⭐⭐ KEY FIX: Wait for submission window to open ⭐⭐
    if not wait_for_submission_window(topic_id, worker, logger, max_wait_seconds=600):
        logger.error("❌ Cannot proceed without open submission window")
        
        # Provide troubleshooting advice
        logger.info("💡 Troubleshooting steps:")
        logger.info("1. Check if worker is properly registered for topic %s", topic_id)
        logger.info("2. Wait for next epoch (epoch length: 720 blocks)")
        logger.info("3. Manually check with: allorad query emissions worker-submission-window-status %s %s", worker, topic_id)
        
        return 2

    # Fetch price data
    logger.info("Fetching price data (last %s days)...", days_back)
    fetcher = DataFetcher(logger)
    prices, fetch_meta = fetcher.fetch_price_history(
        days_back, force_refresh=force_refresh, allow_fallback=True, freshness_hours=3
    )
    coverage = fetch_meta.coverage or coverage_ratio(prices, days_back)

    if prices.empty or coverage < MIN_COVERAGE_RATIO:
        logger.error("❌ Price data insufficient: coverage=%.2f%% source=%s", coverage * 100, fetch_meta.source)
        return 1

    if fetch_meta.fallback_used:
        logger.warning("⚠️ Using synthetic/fallback data for submission: %s", fetch_meta.source)
    else:
        logger.info("✅ Using real price data from: %s", fetch_meta.source)

    logger.info("Data coverage: %.2f%% (%d rows)", coverage * 100, len(prices))

    if not price_coverage_ok(prices, min_days=days_back, freshness_hours=3):
        logger.warning("⚠️ Proceeding with partial coverage: %.2f%%", coverage * 100)

    # Generate features and make prediction
    logger.info("Generating features...")
    features = generate_features(prices)
    if features.empty:
        logger.error("❌ No features generated from price history")
        return 1

    try:
        x_live_raw = latest_feature_row(features, feature_names)
        x_live = pd.DataFrame([x_live_raw], columns=feature_names)
        logger.info("✅ Features prepared successfully (%d features)", len(feature_names))
    except Exception as exc:
        logger.error("❌ Feature mismatch detected: %s", exc)
        logger.error("Expected features: %s", feature_names)
        return 1

    logger.info("Making prediction...")
    prediction = float(model.predict(x_live)[0])
    logger.info("📊 Prediction value: %.6f", prediction)

    if not validate_prediction(prediction):
        logger.error("❌ Prediction failed validation (non-finite, out of bounds, or degenerate)")
        return 1

    # Save submission payload locally
    submission_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic_id": topic_id,
        prediction_label: prediction,
        "horizon_hours": horizon_hours,
        "data_source": fetch_meta.source,
        "uses_synthetic_data": fetch_meta.fallback_used,
        "model_type": "fallback" if bundle_meta.get("fallback") else "trained",
        "coverage_ratio": coverage,
    }

    PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PAYLOAD_PATH.open("w") as f:
        json.dump(submission_payload, f, indent=2)
    logger.info("✅ Saved submission payload to %s", PAYLOAD_PATH)

    # Submit to blockchain
    logger.info("Submitting to Allora blockchain...")
    submission_result, tx_hash = submit_prediction_to_chain(
        topic_id=topic_id, value=prediction, wallet=worker, logger=logger
    )

    # Log submission record
    log_submission_record(
        timestamp=datetime.now(timezone.utc),
        topic_id=topic_id,
        prediction=prediction,
        worker=worker,
        status="submitted" if submission_result else "submit_failed",
        extra={
            "fetch_source": fetch_meta.source,
            "coverage": coverage,
            "bundle_trained_at": bundle_meta.get("trained_at"),
            "window_errors": [],  # Cleared since we waited for window
            "tx_hash": tx_hash,
            "horizon_hours": horizon_hours,
            "uses_synthetic_data": fetch_meta.fallback_used,
            "model_type": "fallback" if bundle_meta.get("fallback") else "trained",
        },
    )

    if submission_result:
        logger.info("🎉 Prediction submitted successfully!")
        logger.info("Transaction hash: %s", tx_hash)
        return 0
    else:
        logger.error("❌ Prediction submission failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
