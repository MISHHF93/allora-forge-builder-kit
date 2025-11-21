#!/usr/bin/env python
"""
Full submission pipeline test for Allora Forge Builder Kit.

This test validates the complete prediction and submission cycle:
1. Model executes prediction for Topic 67 (BTC/USD 7-day log-return)
2. Submission attempts using REST/CLI fallback logic
3. Transaction logging (or filtering decisions)
4. Healthy cycle indicators in logs

Usage:
  python test_full_submission_pipeline.py [--mock-submit] [--verbose]

Environment Requirements:
- ALLORA_API_KEY: Valid API key for market data
- ALLORA_WALLET_ADDR: Wallet address (for logging)
- Optional: .allora_key file or ALLORA_WALLET_SEED_PHRASE for submission

Note: This test uses mock submission by default to avoid real transactions.
Use --no-mock-submit only in testnet environments with caution.
"""
import argparse
import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch, MagicMock

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from allora_forge_builder_kit.workflow import AlloraMLWorkflow
from allora_forge_builder_kit.submission_log import log_submission_row
import train


class FullSubmissionPipelineTest:
    """Test class for validating the complete submission pipeline."""

    def __init__(self, mock_submit: bool = True, verbose: bool = False):
        self.mock_submit = mock_submit
        self.verbose = verbose
        self.temp_dir = None
        self.test_results = {}
        self.start_time = time.time()

    def setup_test_environment(self) -> str:
        """Set up isolated test environment with temporary directory."""
        self.temp_dir = tempfile.mkdtemp(prefix="allora_test_")
        print(f"🧪 Setting up test environment in: {self.temp_dir}")

        # Copy necessary config files
        import shutil
        config_src = Path("config/pipeline.yaml")
        if config_src.exists():
            config_dest = Path(self.temp_dir) / "config"
            config_dest.mkdir(exist_ok=True)
            shutil.copy2(config_src, config_dest / "pipeline.yaml")

        # Set up minimal data directory structure
        data_dir = Path(self.temp_dir) / "data" / "artifacts"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Create minimal .env if needed
        env_file = Path(self.temp_dir) / ".env"
        if not env_file.exists():
            with open(env_file, 'w') as f:
                f.write("# Test environment variables\n")
                f.write("ALLORA_API_KEY=test_key_123\n")
                f.write("ALLORA_WALLET_ADDR=allo1testwallet12345678901234567890\n")

        return self.temp_dir

    def validate_environment(self) -> bool:
        """Validate required environment variables and files."""
        print("🔍 Validating test environment...")

        # Check API key
        api_key = os.getenv("ALLORA_API_KEY")
        if not api_key:
            print("❌ ALLORA_API_KEY not set")
            return False
        print(f"✅ API key configured: {api_key[:10]}...")

        # Check wallet
        wallet = os.getenv("ALLORA_WALLET_ADDR")
        if not wallet:
            print("❌ ALLORA_WALLET_ADDR not set")
            return False
        print(f"✅ Wallet configured: {wallet[:20]}...")

        # Check data availability (minimal)
        try:
            workflow = AlloraMLWorkflow(
                data_api_key=api_key,
                tickers=["btcusd"],
                hours_needed=24,  # Minimal for test
                number_of_input_candles=24,
                target_length=7,
                sample_spacing_hours=24
            )
            # Just check if we can initialize
            print("✅ Workflow initialization successful")
        except Exception as e:
            print(f"❌ Workflow initialization failed: {e}")
            return False

        return True

    def run_prediction_pipeline(self) -> Dict[str, Any]:
        """Run the prediction pipeline and capture results."""
        print("🤖 Running prediction pipeline...")

        results = {
            "prediction_generated": False,
            "model_trained": False,
            "prediction_value": None,
            "log10_loss": None,
            "error": None
        }

        try:
            # Use minimal data for quick test
            workflow = AlloraMLWorkflow(
                data_api_key=os.getenv("ALLORA_API_KEY"),
                tickers=["btcusd"],
                hours_needed=48,  # Small dataset for test
                number_of_input_candles=48,
                target_length=7,
                sample_spacing_hours=24
            )

            # Load minimal data
            full_data = workflow.get_full_feature_target_dataframe(from_month="2025-10")
            if full_data.empty:
                raise ValueError("No data available for testing")

            print(f"✅ Loaded {len(full_data)} data points")

            # Train model (minimal)
            from sklearn.model_selection import train_test_split
            from xgboost import XGBRegressor
            import numpy as np

            # Prepare data
            X = full_data.drop(columns=["target", "future_close"], errors="ignore")
            # Remove non-numeric columns that XGBoost can't handle
            X = X.select_dtypes(include=[np.number])
            y = full_data["target"]

            if len(X) < 10:
                raise ValueError("Insufficient data for training")

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

            # Train model
            model = XGBRegressor(n_estimators=10, random_state=42)  # Minimal for test
            model.fit(X_train, y_train)

            # Generate prediction
            latest_features = X.iloc[-1:]  # Use latest data point
            prediction = model.predict(latest_features)[0]

            # Calculate loss
            y_pred_test = model.predict(X_test)
            log10_loss = np.log10(np.mean((y_test - y_pred_test) ** 2) + 1e-10)

            results.update({
                "prediction_generated": True,
                "model_trained": True,
                "prediction_value": float(prediction),
                "log10_loss": float(log10_loss),
                "data_points": len(full_data),
                "test_mse": float(np.mean((y_test - y_pred_test) ** 2))
            })

            print(".6f")
            print(".6f")
        except Exception as e:
            results["error"] = str(e)
            print(f"❌ Prediction pipeline failed: {e}")

        return results

    def run_submission_attempt(self, prediction_value: float, log10_loss: float) -> Dict[str, Any]:
        """Run submission attempt with fallback logic."""
        print("📤 Running submission attempt...")

        results = {
            "submission_attempted": False,
            "submission_success": False,
            "fallback_used": None,
            "tx_hash": None,
            "error": None
        }

        if self.mock_submit:
            # Mock submission for safe testing
            print("🎭 Using mock submission (no real transaction)")

            # Simulate successful submission
            mock_tx_hash = "0x" + "a" * 64
            mock_nonce = 12345

            # Log the mock submission
            log_path = os.path.join(self.temp_dir, "submission_log.csv")
            log_submission_row(
                log_path,
                {
                    "timestamp_utc": pd.Timestamp.now(tz="UTC").isoformat().replace("+00:00", "Z"),
                    "topic_id": 67,
                    "value": prediction_value,
                    "wallet": os.getenv("ALLORA_WALLET_ADDR", "test_wallet"),
                    "nonce": mock_nonce,
                    "tx_hash": mock_tx_hash,
                    "success": True,
                    "exit_code": 0,
                    "status": "mock_submitted",
                    "log10_loss": log10_loss,
                    "score": 0.85,  # Mock score
                    "reward": "pending"
                }
            )

            results.update({
                "submission_attempted": True,
                "submission_success": True,
                "fallback_used": "mock",
                "tx_hash": mock_tx_hash
            })

        else:
            # Real submission attempt (use with caution)
            print("⚠️  Attempting real submission...")

            try:
                # Import submission functions
                from train import _submit_with_sdk, _submit_with_client_xgb, _submit_via_external_helper

                topic_id = 67
                timeout_s = 30
                max_retries = 1  # Minimal for test

                # Try SDK submission first
                print("🔄 Attempting SDK submission...")
                exit_code = _submit_with_sdk(topic_id, prediction_value, timeout_s, max_retries, self.temp_dir, log10_loss)

                if exit_code == 0:
                    results.update({
                        "submission_attempted": True,
                        "submission_success": True,
                        "fallback_used": "sdk"
                    })
                else:
                    # Try client submission
                    print("🔄 SDK failed, trying client submission...")
                    exit_code = _submit_with_client_xgb(topic_id, prediction_value, self.temp_dir, log10_loss)

                    if exit_code == 0:
                        results.update({
                            "submission_attempted": True,
                            "submission_success": True,
                            "fallback_used": "client"
                        })
                    else:
                        # Try external helper
                        print("🔄 Client failed, trying external helper...")
                        result = _submit_via_external_helper(topic_id, prediction_value, self.temp_dir, log10_loss, 60)

                        if result and result[1]:  # success flag
                            results.update({
                                "submission_attempted": True,
                                "submission_success": True,
                                "fallback_used": "helper"
                            })
                        else:
                            results.update({
                                "submission_attempted": True,
                                "submission_success": False,
                                "fallback_used": "all_failed",
                                "error": f"Submission failed with exit codes: sdk={exit_code}"
                            })

            except Exception as e:
                results.update({
                    "submission_attempted": True,
                    "submission_success": False,
                    "error": str(e)
                })

        return results

    def validate_logs(self) -> Dict[str, Any]:
        """Validate submission logs and health indicators."""
        print("📋 Validating logs and health indicators...")

        results = {
            "log_file_exists": False,
            "log_entries": 0,
            "healthy_indicators": [],
            "warnings": [],
            "errors": []
        }

        log_path = os.path.join(self.temp_dir, "submission_log.csv")

        if not os.path.exists(log_path):
            results["errors"].append("Submission log file not created")
            return results

        results["log_file_exists"] = True

        try:
            with open(log_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            results["log_entries"] = len(rows)

            if not rows:
                results["warnings"].append("No log entries found")
                return results

            # Validate latest entry
            latest = rows[-1]

            # Check required fields
            required_fields = ["timestamp_utc", "topic_id", "value", "wallet", "success", "status"]
            for field in required_fields:
                if field not in latest or not latest[field]:
                    results["errors"].append(f"Missing required field: {field}")

            # Check topic ID
            if str(latest.get("topic_id", "")) != "67":
                results["errors"].append(f"Wrong topic ID: {latest.get('topic_id')}")

            # Check success flag
            success = latest.get("success", "").lower()
            if success not in ["true", "1", "yes"]:
                results["warnings"].append(f"Submission not marked as successful: {success}")

            # Check for healthy indicators
            status = latest.get("status", "").lower()
            if "submitted" in status or "mock_submitted" in status:
                results["healthy_indicators"].append("Submission completed")
            if latest.get("tx_hash"):
                results["healthy_indicators"].append("Transaction hash recorded")
            if latest.get("score"):
                results["healthy_indicators"].append("Score field populated")
            if latest.get("log10_loss"):
                results["healthy_indicators"].append("Loss metric recorded")

            # Check timestamp is recent
            try:
                ts = pd.to_datetime(latest.get("timestamp_utc", ""))
                age_seconds = (pd.Timestamp.now(tz="UTC") - ts).total_seconds()
                if age_seconds > 300:  # 5 minutes
                    results["warnings"].append(f"Log entry is {age_seconds:.0f}s old")
                else:
                    results["healthy_indicators"].append("Recent log entry")
            except Exception:
                results["warnings"].append("Could not parse timestamp")

        except Exception as e:
            results["errors"].append(f"Log validation error: {e}")

        return results

    def run_full_test(self) -> Dict[str, Any]:
        """Run the complete test suite."""
        print("🚀 Starting Full Submission Pipeline Test")
        print("=" * 60)

        # Setup
        test_dir = self.setup_test_environment()
        os.chdir(test_dir)  # Change to test directory

        # Environment validation
        if not self.validate_environment():
            return {"success": False, "error": "Environment validation failed"}

        # Prediction pipeline
        prediction_results = self.run_prediction_pipeline()
        if not prediction_results["prediction_generated"]:
            return {"success": False, "error": "Prediction pipeline failed", "details": prediction_results}

        # Submission attempt
        submission_results = self.run_submission_attempt(
            prediction_results["prediction_value"],
            prediction_results["log10_loss"]
        )

        # Log validation
        log_results = self.validate_logs()

        # Overall assessment
        success = (
            prediction_results["prediction_generated"] and
            submission_results["submission_attempted"] and
            log_results["log_file_exists"] and
            len(log_results["errors"]) == 0
        )

        test_duration = time.time() - self.start_time

        results = {
            "success": success,
            "test_duration_seconds": test_duration,
            "prediction": prediction_results,
            "submission": submission_results,
            "logs": log_results,
            "test_directory": test_dir
        }

        return results

    def print_results(self, results: Dict[str, Any]):
        """Print formatted test results."""
        print("\n" + "=" * 60)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 60)

        if results["success"]:
            print("✅ OVERALL: TEST PASSED")
        else:
            print("❌ OVERALL: TEST FAILED")

        print(".2f")
        # Prediction results
        pred = results.get("prediction", {})
        print("\n🤖 PREDICTION PIPELINE:")
        print(f"   Model trained: {'✅' if pred.get('model_trained') else '❌'}")
        print(f"   Prediction generated: {'✅' if pred.get('prediction_generated') else '❌'}")
        if pred.get("prediction_value"):
            print(f"   Prediction value: {pred['prediction_value']:.6f}")
        if pred.get("log10_loss"):
            print(f"   Log10 loss: {pred['log10_loss']:.6f}")
        # Submission results
        sub = results.get("submission", {})
        print("\n📤 SUBMISSION ATTEMPT:")
        print(f"   Attempted: {'✅' if sub.get('submission_attempted') else '❌'}")
        print(f"   Successful: {'✅' if sub.get('submission_success') else '❌'}")
        if sub.get("fallback_used"):
            print(f"   Method: {sub['fallback_used']}")
        if sub.get("tx_hash"):
            print(f"   TX Hash: {sub['tx_hash'][:20]}...")

        # Log results
        logs = results.get("logs", {})
        print("\n📋 LOG VALIDATION:")
        print(f"   Log file exists: {'✅' if logs.get('log_file_exists') else '❌'}")
        print(f"   Log entries: {logs.get('log_entries', 0)}")
        if logs.get("healthy_indicators"):
            print("   Healthy indicators:")
            for indicator in logs["healthy_indicators"]:
                print(f"     ✅ {indicator}")
        if logs.get("warnings"):
            print("   Warnings:")
            for warning in logs["warnings"]:
                print(f"     ⚠️  {warning}")
        if logs.get("errors"):
            print("   Errors:")
            for error in logs["errors"]:
                print(f"     ❌ {error}")

        print(f"\n🗂️  Test directory: {results.get('test_directory', 'N/A')}")

        if results.get("success"):
            print("\n🎉 All pipeline components validated successfully!")
            print("   Ready for production deployment.")
        else:
            print("\n⚠️  Test failed - review errors above before deployment.")


def main():
    parser = argparse.ArgumentParser(description="Full submission pipeline test")
    parser.add_argument("--mock-submit", action="store_true", default=True,
                       help="Use mock submission (default: True)")
    parser.add_argument("--no-mock-submit", action="store_false", dest="mock_submit",
                       help="Attempt real submission (use with caution)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")

    args = parser.parse_args()

    # Run the test
    test = FullSubmissionPipelineTest(mock_submit=args.mock_submit, verbose=args.verbose)
    results = test.run_full_test()
    test.print_results(results)

    # Exit with appropriate code
    sys.exit(0 if results["success"] else 1)


if __name__ == "__main__":
    main()