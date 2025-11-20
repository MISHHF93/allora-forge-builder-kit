#!/usr/bin/env python3
"""Test a single submission to validate the pipeline"""
import sys
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
import pytest
import subprocess

load_dotenv()

def test_submission():
    """Perform a test submission for the current hour."""
    print("=" * 60)
    print("TEST SUBMISSION - Current Hour")
    print("=" * 60)
    print()

    now = datetime.now(timezone.utc)
    current_hour = now.replace(minute=0, second=0, microsecond=0)

    print(f"Current UTC time: {now.isoformat()}")
    print(f"Submission hour: {current_hour.isoformat()}")
    print()

    sys.path.insert(0, os.path.dirname(__file__))

    api_key = os.getenv("ALLORA_API_KEY")
    wallet = os.getenv("ALLORA_WALLET_ADDR")

    if not api_key:
        pytest.skip("ALLORA_API_KEY not set; skipping submission smoke test")

    if not wallet:
        pytest.skip("ALLORA_WALLET_ADDR not set; skipping submission smoke test")

    print(f"✅ API Key: {api_key[:10]}...***")
    print(f"✅ Wallet: {wallet}")
    print()

    print("Running: python3 train.py --submit --as-of-now")
    print()

    result = subprocess.run(
        ["python3", "train.py", "--submit", "--as-of-now"],
        capture_output=False,
        text=True,
    )

    assert result.returncode == 0, "train.py submission command failed"


if __name__ == "__main__":
    load_dotenv()
    try:
        test_submission()
        sys.exit(0)
    except SystemExit as exc:
        raise
    except Exception:
        sys.exit(1)
