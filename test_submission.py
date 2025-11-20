#!/usr/bin/env python3
"""Test a single submission to validate the pipeline"""
import sys
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
import pytest

import pytest

load_dotenv()

def test_submission():
    """Perform a test submission for the current hour."""

    if os.getenv("RUN_SUBMISSION_TESTS") != "1":
        pytest.skip("Submission test requires RUN_SUBMISSION_TESTS=1 to execute.")
    print("=" * 60)
    print("TEST SUBMISSION - Current Hour")
    print("=" * 60)
    print()
    
    # Get current hour
    now = datetime.now(timezone.utc)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    
    print(f"Current UTC time: {now.isoformat()}")
    print(f"Submission hour: {current_hour.isoformat()}")
    print()
    
    # Import train.py submission function
    sys.path.insert(0, os.path.dirname(__file__))
    
    # Check environment
    api_key = os.getenv('ALLORA_API_KEY')
    wallet = os.getenv('ALLORA_WALLET_ADDR')
    
    if not api_key:
        print("❌ ALLORA_API_KEY not set")
        return 1
    
    if not wallet:
        print("❌ ALLORA_WALLET_ADDR not set")
        return 1
    
    print(f"✅ API Key: {api_key[:10]}...***")
    print(f"✅ Wallet: {wallet}")
    print()
    
    # Run train.py with single submission
    print("Running: python3 train.py --submit --as-of-now")
    print()
    
    import subprocess
    result = subprocess.run(
        ['python3', 'train.py', '--submit', '--as-of-now'],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"Submission command failed: {result.stderr}"


if __name__ == '__main__':
    test_submission()
