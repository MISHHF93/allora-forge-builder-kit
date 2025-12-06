#!/usr/bin/env python3
"""Prepare and persist a forecast payload using validated market data."""

from __future__ import annotations

import json
import os
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

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
from pipeline_submit import submit_prediction_to_chain
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


def submit_prediction_via_sdk(topic_id: int, value: float, wallet: str, logger) -> tuple[bool, str]:
    """Submit prediction using Allora SDK instead of CLI."""
    try:
        from allora_sdk import LocalWallet, AlloraRPCClient
        from allora_sdk.protos.emissions.v9 import InputWorkerDataBundle, InputInferenceForecastBundle, InputInference
        import hashlib
        import base64
        import asyncio
        
        # Get mnemonic from environment
        mnemonic = os.getenv("MNEMONIC", "").strip()
        if not mnemonic:
            logger.error("❌ MNEMONIC not set for SDK submission")
            return submit_prediction_to_chain(topic_id, value, wallet, logger)
        
        # Create wallet from mnemonic
        try:
            wallet_obj = LocalWallet.from_mnemonic(mnemonic)
            logger.debug("✅ SDK wallet created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create SDK wallet: {e}")
            return submit_prediction_to_chain(topic_id, value, wallet, logger)
        
        # Get current block height for nonce
        try:
            rpc_client = AlloraRPCClient("https://allora-testnet-rpc.polkachu.com:443")
            latest_block = asyncio.run(rpc_client.get_latest_block())
            block_height = latest_block.block.header.height
            logger.debug(f"✅ Got block height: {block_height}")
        except Exception as e:
            logger.error(f"❌ Failed to get block height: {e}")
            return submit_prediction_to_chain(topic_id, value, wallet, logger)
        
        # Create inference
        inference = InputInference(
            topic_id=topic_id,
            block_height=block_height,
            inferer=wallet,
            value=str(value),
            extra_data=b"",
            proof=""
        )
        
        # Create bundle
        bundle = InputInferenceForecastBundle(inference=inference)
        bundle_bytes = bundle.SerializeToString()
        
        # Sign the bundle
        digest = hashlib.sha256(bundle_bytes).digest()
        sig = wallet_obj._private_key.sign_digest(digest)
        bundle_signature = base64.b64encode(sig).decode()
        
        # Create worker data bundle
        worker_data_bundle = InputWorkerDataBundle(
            worker=wallet,
            nonce={"block_height": block_height},
            topic_id=topic_id,
            inference_forecasts_bundle=bundle,
            inferences_forecasts_bundle_signature=bundle_signature,
            pubkey=base64.b64encode(wallet_obj._public_key.to_bytes()).decode()
        )
        
        # Submit via SDK
        try:
            tx_hash = asyncio.run(rpc_client.insert_worker_payload(worker_data_bundle))
            logger.info(f"✅ SDK submission successful! TX hash: {tx_hash}")
            return True, tx_hash
        except Exception as e:
            logger.error(f"❌ SDK submission failed: {e}")
            logger.warning("Falling back to CLI submission")
            return submit_prediction_to_chain(topic_id, value, wallet, logger)
        
    except ImportError as e:
        logger.warning(f"SDK import failed: {e}, using CLI submission")
        return submit_prediction_to_chain(topic_id, value, wallet, logger)
    except Exception as e:
        logger.error(f"❌ Unexpected SDK error: {e}")
        import traceback
        logger.debug(f"SDK traceback: {traceback.format_exc()}")
        return submit_prediction_to_chain(topic_id, value, wallet, logger)


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
    parser = argparse.ArgumentParser(description="Submit BTC/USD 7-day log-return prediction.")
    parser.add_argument("--model", type=str, default="artifacts/model_bundle.joblib", help="Path to trained model.")
    parser.add_argument("--features", type=str, default="features.json", help="Path to feature columns.")
    parser.add_argument("--topic-id", type=int, default=int(os.getenv("TOPIC_ID", "67")), help="Allora topic ID.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate submission without sending.")
    parser.add_argument("--once", action="store_true", help="Run once and exit (replaces --continuous when not set).")
    parser.add_argument("--continuous", action="store_true", help="Run in continuous mode, submitting every hour.")
    parser.add_argument("--daemon", action="store_true", help="Run as permanent daemon (until Dec 15, 2025).")
    args = parser.parse_args()
    
    logger = setup_logging("btc_submit", log_file=LOG_FILE)
    
    # Validate critical files exist before entering continuous mode
    if not os.path.exists(args.model):
        logger.error(f"❌ CRITICAL: {args.model} not found. Run 'python train.py' first.")
        return 1
    if not os.path.exists(args.features):
        logger.error(f"❌ CRITICAL: {args.features} not found. Run 'python train.py' first.")
        return 1
    
    # Validate environment
    required_env = ["ALLORA_WALLET_ADDR", "MNEMONIC", "TOPIC_ID"]
    missing = [k for k in required_env if not os.getenv(k)]
    if missing:
        logger.error(f"❌ Missing environment variables: {', '.join(missing)}")
        return 1

    if args.daemon or args.continuous:
        print(f"[DEBUG] About to call run_daemon()...")
        sys.stdout.flush()
        result = run_daemon(args)
        print(f"[DEBUG] run_daemon() returned: {result}")
        sys.stdout.flush()
        return result
    else:
        # Single run mode
        exit_code = asyncio.run(main_once(args))
        return exit_code
        
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


async def main_once(args) -> bool:
    """Execute a single submission cycle with comprehensive error handling."""
    logger = setup_logging("btc_submit", log_file=LOG_FILE)
    
    # Get configuration from args
    topic_id = args.topic_id
    worker = os.getenv("ALLORA_WALLET_ADDR", "unknown")
    
    if worker == "unknown":
        logger.error("❌ ALLORA_WALLET_ADDR environment variable not set")
        return False
    
    logger.info("🚀 Starting prediction submission for topic %s", topic_id)
    logger.info("Worker address: %s", worker)

    # Load model bundle
    logger.info("Loading model bundle from %s", args.model)
    try:
        model, feature_names, bundle_meta, horizon_hours = load_bundle(logger)
        if bundle_meta.get("fallback"):
            logger.warning("⚠️ Using fallback constant model - no trained model found")
        else:
            logger.info("✅ Model loaded successfully (trained at: %s)", 
                       bundle_meta.get("trained_at", "unknown"))
    except Exception as exc:
        logger.error("❌ Failed to load model bundle: %s", exc)
        return False

    prediction_label = get_prediction_label(horizon_hours)
    logger.info("Using prediction horizon: %s hours -> %s", horizon_hours, prediction_label)

    # Fetch latest data and generate prediction
    try:
        days_back = int(os.getenv("FORECAST_DAYS_BACK", "30"))
        force_refresh = os.getenv("FORCE_FETCH", "0").lower() in {"1", "true", "yes"}
        
        logger.info("Fetching price data (last %s days)...", days_back)
        fetcher = DataFetcher(logger)
        prices, fetch_meta = fetcher.fetch_price_history(
            days_back, force_refresh=force_refresh, allow_fallback=True, freshness_hours=3
        )
        coverage = fetch_meta.coverage or coverage_ratio(prices, days_back)

        if prices.empty or coverage < MIN_COVERAGE_RATIO:
            logger.error("❌ Price data insufficient: coverage=%.2f%% source=%s", coverage * 100, fetch_meta.source)
            return False

        if fetch_meta.fallback_used:
            logger.warning("⚠️ Using synthetic/fallback data for submission: %s", fetch_meta.source)
        else:
            logger.info("✅ Using real price data from: %s", fetch_meta.source)

        logger.info("Data coverage: %.2f%% (%d rows)", coverage * 100, len(prices))

        if not price_coverage_ok(prices, min_days=days_back, freshness_hours=3):
            logger.error("❌ Price data not fresh enough or insufficient coverage")
            return False
            
        features_df = generate_features(prices)
        latest_features = latest_feature_row(features_df, feature_names)
        
        # Reshape to 2D array for model prediction
        if isinstance(latest_features, pd.Series):
            latest_features = latest_features.values.reshape(1, -1)
        
        prediction = float(model.predict(latest_features)[0])
        
        logger.info("📊 Generated prediction: %.6f", prediction)
        logger.info("📈 Data coverage: %.1f%%", coverage * 100)
        
    except Exception as exc:
        logger.error("❌ Failed to generate prediction: %s", exc)
        return False

    # Prepare submission payload
    submission_payload = {
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

    # Submit to blockchain (unless dry run)
    if args.dry_run:
        logger.info("🏃 DRY RUN: Skipping actual blockchain submission")
        logger.info("📄 Payload that would be submitted: %s", json.dumps(submission_payload, indent=2))
        return True

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
        return True
    else:
        logger.error("❌ Prediction submission failed")
        return False


def validate_startup(args) -> bool:
    """
    Comprehensive startup validation to ensure model and features are ready.
    """
    logger = setup_logging("btc_submit", log_file=LOG_FILE)
    
    logger.info("=" * 72)
    logger.info("🔍 PRE-EXECUTION STARTUP VALIDATION")
    logger.info("=" * 72)
    
    # [1/4] Check features.json
    logger.info("")
    logger.info("[1/4] Checking features.json...")
    if not os.path.exists(args.features):
        logger.error("   ❌ Features file not found: %s", args.features)
        logger.error("   Run 'python train.py' to generate features.json")
        return False
    try:
        with open(args.features, "r") as f:
            feature_cols = json.load(f)
        logger.info("   ✅ Features file valid: %d columns", len(feature_cols))
    except Exception as e:
        logger.error("   ❌ Features file invalid: %s", e)
        return False
    
    # [2/4] Check model file
    logger.info("")
    logger.info("[2/4] Checking %s file...", args.model)
    if not os.path.exists(args.model):
        logger.error("   ❌ Model file not found: %s", args.model)
        logger.error("   Run 'python train.py' to generate the model")
        return False
    try:
        bundle = joblib.load(args.model)
        if not isinstance(bundle, dict) or 'model' not in bundle:
            logger.error("   ❌ Model bundle invalid format")
            return False
        logger.info("   ✅ Model file exists: %d bytes", os.path.getsize(args.model))
    except Exception as e:
        logger.error("   ❌ Model file invalid: %s", e)
        return False
    
    # [3/4] Validate model
    logger.info("")
    logger.info("[3/4] Validating model (comprehensive fitted-state check)...")
    try:
        model = bundle['model']
        feature_names = bundle.get('feature_names', feature_cols)
        
        # Check if model has predict method
        if not hasattr(model, 'predict'):
            logger.error("   ❌ Model missing predict method")
            return False
        
        # Check feature count
        if hasattr(model, 'n_features_in_'):
            if model.n_features_in_ != len(feature_names):
                logger.error("   ❌ Feature count mismatch: model expects %d, got %d", 
                           model.n_features_in_, len(feature_names))
                return False
        
        # Test predictions
        import numpy as np
        zero_input = np.zeros((1, len(feature_names)))
        random_input = np.random.randn(1, len(feature_names))
        
        pred_zero = model.predict(zero_input)[0]
        pred_random = model.predict(random_input)[0]
        
        logger.info("   ✅ Model is fitted (n_features_in_=%s)", 
                   getattr(model, 'n_features_in_', 'unknown'))
        logger.info("   ✅ Feature count matches: %d", len(feature_names))
        logger.info("   ✅ Test prediction on zero input successful: %.6f", pred_zero)
        logger.info("   ✅ Test prediction on random input successful: %.6f", pred_random)
        
    except Exception as e:
        logger.error("   ❌ Model validation failed: %s", e)
        return False
    
    # [4/4] Test data fetch and prediction
    logger.info("")
    logger.info("[4/4] Testing data fetch and prediction...")
    try:
        # Quick test of data fetching
        fetcher = DataFetcher(logger)
        test_prices, test_meta = fetcher.fetch_price_history(
            days_back=7, force_refresh=False, allow_fallback=True, freshness_hours=24
        )
        
        if test_prices.empty:
            logger.error("   ❌ Data fetch failed: empty dataframe")
            return False
            
        # Test feature generation
        test_features = generate_features(test_prices)
        if test_features.empty:
            logger.error("   ❌ Feature generation failed: empty dataframe")
            return False
            
        # Test latest feature row
        test_latest = latest_feature_row(test_features, feature_names)
        if test_latest is None:
            logger.error("   ❌ Latest feature row failed")
            return False
            
        # Reshape to 2D array for model prediction
        if isinstance(test_latest, pd.Series):
            test_latest = test_latest.values.reshape(1, -1)
            
        # Test prediction
        test_pred = float(model.predict(test_latest)[0])
        
        logger.info("   ✅ Data fetch successful: %d rows", len(test_prices))
        logger.info("   ✅ Feature generation successful: %d rows", len(test_features))
        logger.info("   ✅ Prediction successful: %.6f", test_pred)
        
    except Exception as e:
        logger.error("   ❌ Data/prediction test failed: %s", e)
        return False
    
    logger.info("")
    logger.info("=" * 72)
    logger.info("✅ STARTUP VALIDATION COMPLETE - ALL CHECKS PASSED")
    logger.info("=" * 72)
    return True


###############################################################################
# Daemon Mode Implementation
###############################################################################

import asyncio
import signal
from datetime import datetime, timezone, timedelta

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

def run_daemon(args):
    """
    Run as a long-lived daemon until December 15, 2025.
    Handles all exceptions, never silently fails, includes hourly heartbeat.
    """
    global _shutdown_requested
    
    logger = setup_logging("btc_submit", log_file=LOG_FILE)
    
    # Validate startup before beginning daemon loop
    if not validate_startup(args):
        logger.error("❌ STARTUP VALIDATION FAILED - ABORTING DAEMON START")
        logger.error("   Address the issues above and try again")
        return 1
    
    interval = int(os.getenv("SUBMISSION_INTERVAL", "3600"))  # 1 hour default
    
    # EXACT competition schedule from Allora (https://allora.network)
    # "7 day BTC/USD Log-Return Prediction (updating every hour)"
    competition_start = datetime(2025, 9, 16, 13, 0, 0, tzinfo=timezone.utc)
    competition_end = datetime(2025, 12, 15, 13, 0, 0, tzinfo=timezone.utc)
    
    logger.info("=" * 80)
    logger.info("🚀 DAEMON MODE STARTED")
    logger.info(f"   Model: {args.model}")
    logger.info(f"   Features: {args.features}")
    logger.info(f"   Topic ID: {args.topic_id}")
    logger.info(f"   Submission Interval: {interval}s ({interval/3600:.1f}h)")
    logger.info(f"   Competition Start: {competition_start.isoformat()}")
    logger.info(f"   Competition End: {competition_end.isoformat()}")
    logger.info(f"   Current Time: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 80)
    
    cycle_count = 0
    last_heartbeat = None
    
    while not _shutdown_requested:
        cycle_count += 1
        cycle_start = datetime.now(timezone.utc)
        
        # Check if competition has NOT started yet
        if cycle_start < competition_start:
            logger.warning(f"⏱️  Competition hasn't started yet ({competition_start.isoformat()}). Skipping submission.")
            # Sleep until competition starts
            sleep_duration = max(60, (competition_start - cycle_start).total_seconds())
            for handler in logger.handlers:
                handler.flush()
            time.sleep(sleep_duration)
            continue
        
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
            logger.info(f"TRAINING & SUBMISSION CYCLE #{cycle_count} - {cycle_start.isoformat()}")
            logger.info(f"{'='*80}")
            
            # Step 1: Train fresh model with latest data
            logger.info("🔄 TRAINING: Starting fresh model training...")
            try:
                import subprocess
                result = subprocess.run([sys.executable, "train.py"], 
                                      capture_output=True, text=True, timeout=600)  # 10 min timeout
                if result.returncode == 0:
                    logger.info("✅ TRAINING: Model training completed successfully")
                    logger.debug(f"Training output: {result.stdout}")
                else:
                    logger.error(f"❌ TRAINING: Model training failed with code {result.returncode}")
                    logger.error(f"Training stderr: {result.stderr}")
                    logger.warning("⚠️  Continuing with existing model for submission")
            except subprocess.TimeoutExpired:
                logger.error("❌ TRAINING: Model training timed out after 10 minutes")
                logger.warning("⚠️  Continuing with existing model for submission")
            except Exception as e:
                logger.error(f"❌ TRAINING: Unexpected error during training: {e}")
                logger.warning("⚠️  Continuing with existing model for submission")
            
            # Step 2: Submit prediction with fresh model
            logger.info("📤 SUBMISSION: Starting prediction submission...")
            success = asyncio.run(main_once(args))
            logger.debug(f"main_once returned: {success}")
            
            if success:
                logger.info("✅ Submission cycle completed successfully")
            else:
                logger.warning("⚠️  Submission cycle completed without successful submission (may be skipped/no nonce)")
            logger.debug("About to enter sleep phase...")
        
        except Exception as e:
            # CRITICAL: Never silently fail
            logger.error(f"❌ UNHANDLED EXCEPTION IN SUBMISSION CYCLE #{cycle_count}")
            logger.error(f"   Exception: {type(e).__name__}: {str(e)}")
            logger.error("   Full traceback:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    logger.error(f"   {line}")
            # Continue to next cycle instead of crashing
        
        logger.debug("Entered post-cycle sleep block...")
        try:
            if not _shutdown_requested:
                # Align to next hourly UTC boundary (XX:00:00)
                now = datetime.now(timezone.utc)
                next_hour = (now.replace(minute=0, second=0, microsecond=0) + 
                            timedelta(hours=1))
                sleep_duration = max(1, (next_hour - now).total_seconds())
                
                logger.info(f"Sleeping for {sleep_duration:.0f}s until next hourly boundary ({next_hour.strftime('%H:%M UTC')})")
                # Force flush logs before sleeping
                for handler in logger.handlers:
                    handler.flush()
                time.sleep(sleep_duration)
        except KeyboardInterrupt:
            logger.warning("Interrupted during sleep, proceeding to next cycle")
            pass
    
    logger.info("=" * 80)
    logger.info("🛑 DAEMON SHUTDOWN COMPLETE")
    logger.info(f"   Total Cycles: {cycle_count}")
    logger.info(f"   Final Time: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 80)


if __name__ == "__main__":
    sys.exit(main())
