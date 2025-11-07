#!/usr/bin/env python3
"""Test a single submission to validate the pipeline"""
import sys
import os
import asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

async def test_submission():
    """Perform a test submission for the current hour"""
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
        capture_output=False,
        text=True
    )
    
    return result.returncode

if __name__ == '__main__':
    exit_code = asyncio.run(test_submission())
    sys.exit(exit_code)
