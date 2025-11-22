#!/usr/bin/env python3
"""
BTC/USD 7-Day Log-Return Prediction Monitoring Tool
---------------------------------------------------
Checks wallet balance, submission status, logs, and system health.

Usage:
    python monitor.py [--check-balance] [--check-submissions] [--tail-logs LINES]
"""

import os
import sys
import json
import logging
import argparse
import subprocess
import shutil
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import requests

###############################################################################
# Logging Setup
###############################################################################
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%SZ'
)
logger = logging.getLogger("btc_monitor")

###############################################################################
# Check Balance
###############################################################################
def check_balance() -> dict:
    """Check wallet balance via CLI."""
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("Allora CLI not found")
        return {}
    wallet = os.getenv("ALLORA_WALLET_ADDR", "").strip()
    if not wallet:
        logger.error("ALLORA_WALLET_ADDR not set")
        return {}
    cmd = [cli, "query", "bank", "balances", wallet,
           "--node", "https://allora-rpc.testnet.allora.network/",
           "--output", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            balances = {b["denom"]: float(b["amount"]) for b in data.get("balances", [])}
            logger.info(f"Balances: {balances}")
            return balances
        else:
            logger.error(f"Balance check failed: {proc.stderr}")
            return {}
    except Exception as e:
        logger.error(f"Balance check error: {e}")
        return {}

###############################################################################
# Check Submissions
###############################################################################
def check_submissions(topic_id: int) -> dict:
    """Check latest submission status."""
    try:
        with open("latest_submission.json", "r") as f:
            latest = json.load(f)
        logger.info(f"Latest submission: {latest}")
        # Could query blockchain for confirmation, but for now just local
        return latest
    except Exception as e:
        logger.error(f"Submission check error: {e}")
        return {}

###############################################################################
# Tail Logs
###############################################################################
def tail_logs(lines: int = 10):
    """Tail the submission log."""
    try:
        with open("submission_log.csv", "r") as f:
            content = f.readlines()
            for line in content[-lines:]:
                print(line.strip())
    except Exception as e:
        logger.error(f"Log tail error: {e}")

###############################################################################
# System Health
###############################################################################
def system_health():
    """Basic system checks."""
    # Check if model and features exist
    model_exists = os.path.exists("model.pkl")
    features_exist = os.path.exists("features.json")
    logger.info(f"Model exists: {model_exists}")
    logger.info(f"Features exist: {features_exist}")
    # Check API keys
    api_key = bool(os.getenv("TIINGO_API_KEY", "").strip())
    logger.info(f"Tiingo API key set: {api_key}")
    wallet = bool(os.getenv("ALLORA_WALLET_ADDR", "").strip())
    logger.info(f"Wallet set: {wallet}")

###############################################################################
# Main
###############################################################################
def main():
    parser = argparse.ArgumentParser(description="Monitor BTC/USD prediction system.")
    parser.add_argument("--check-balance", action="store_true", help="Check wallet balance.")
    parser.add_argument("--check-submissions", action="store_true", help="Check submission status.")
    parser.add_argument("--tail-logs", type=int, default=0, help="Tail submission logs (specify lines).")
    parser.add_argument("--system-health", action="store_true", help="Check system health.")
    args = parser.parse_args()

    if args.check_balance:
        check_balance()
    if args.check_submissions:
        check_submissions(int(os.getenv("TOPIC_ID", "67")))
    if args.tail_logs > 0:
        tail_logs(args.tail_logs)
    if args.system_health:
        system_health()
    if not any([args.check_balance, args.check_submissions, args.tail_logs > 0, args.system_health]):
        logger.info("No action specified. Use --help for options.")

if __name__ == "__main__":
    main()