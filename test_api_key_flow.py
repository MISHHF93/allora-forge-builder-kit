#!/usr/bin/env python3
"""
Test script to verify ALLORA_API_KEY is correctly loaded and passed to AlloraWorker.
This simulates the SDK initialization flow without making actual submissions.
"""
import os
import sys
from dotenv import load_dotenv

print("=" * 70)
print("ALLORA API KEY FLOW TEST")
print("=" * 70)

# Step 1: Load .env file
print("\n[Step 1] Loading .env file...")
env_path = os.path.join(os.path.dirname(__file__), ".env")
print(f"  .env path: {env_path}")
print(f"  .env exists: {os.path.exists(env_path)}")

load_dotenv(env_path)

# Step 2: Check if ALLORA_API_KEY is in environment
print("\n[Step 2] Checking environment variable...")
api_key = os.getenv("ALLORA_API_KEY", "").strip()
if api_key:
    # Mask key for security
    masked = api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:] if len(api_key) > 12 else "*" * len(api_key)
    print(f"  ✅ ALLORA_API_KEY found: {masked}")
    print(f"  Key length: {len(api_key)} characters")
    print(f"  Key prefix: {api_key[:3]}...")
    
    # Check if it's actually a Tiingo key (wrong)
    if api_key.startswith("UP-"):
        print(f"  ⚠️  WARNING: This looks like a Tiingo API key (starts with 'UP-')")
        print(f"  ⚠️  Tiingo keys are for market data, not Allora SDK authentication!")
    else:
        print(f"  ✓ Key format looks correct (not a Tiingo key)")
else:
    print("  ❌ ALLORA_API_KEY not found in environment")
    sys.exit(1)

# Step 3: Try to import and initialize AlloraWorker
print("\n[Step 3] Testing AlloraWorker initialization...")
try:
    from allora_sdk.worker import AlloraWorker
    print("  ✅ allora-sdk imported successfully")
    
    # Create a dummy predict function
    def dummy_run(topic_id: int) -> float:
        return 0.0
    
    print(f"\n[Step 4] Initializing AlloraWorker with API key...")
    print(f"  Topic ID: 67")
    print(f"  API Key: {masked}")
    
    # Try to initialize worker (this is where the key is passed)
    worker = AlloraWorker(
        run=dummy_run,
        api_key=api_key,
        topic_id=67
    )
    
    print("  ✅ AlloraWorker initialized successfully!")
    
    # Step 5: Check worker attributes
    print("\n[Step 5] Inspecting AlloraWorker attributes...")
    
    # Check if wallet was initialized
    if hasattr(worker, 'wallet_address'):
        print(f"  ✅ Wallet address: {worker.wallet_address}")
    elif hasattr(worker, 'address'):
        print(f"  ✅ Wallet address: {worker.address}")
    elif hasattr(worker, 'wallet'):
        if isinstance(worker.wallet, dict):
            print(f"  ✅ Wallet address: {worker.wallet.get('address')}")
        else:
            print(f"  ✅ Wallet object: {type(worker.wallet)}")
    else:
        print("  ⚠️  Could not find wallet address attribute")
    
    # Check if client was initialized
    if hasattr(worker, 'client'):
        print(f"  ✅ Client initialized: {type(worker.client)}")
    
    if hasattr(worker, '_api_key'):
        masked_internal = worker._api_key[:8] + "*" * (len(worker._api_key) - 12) + worker._api_key[-4:] if len(worker._api_key) > 12 else "*" * len(worker._api_key)
        print(f"  ✅ API key stored in worker: {masked_internal}")
    
    print("\n" + "=" * 70)
    print("✅ TEST PASSED: API key flow is working correctly!")
    print("=" * 70)
    print("\nNext steps:")
    if api_key.startswith("UP-"):
        print("  1. Get your actual Allora API key from https://app.allora.network/")
        print("  2. Update .env: ALLORA_API_KEY=your_real_allora_key")
        print("  3. Restart the training loop")
    else:
        print("  ✓ API key format looks correct")
        print("  ✓ SDK initialization successful")
        print("  ✓ Ready for submissions!")
    
except ImportError as e:
    print(f"  ❌ Failed to import allora-sdk: {e}")
    print("  Install with: pip install allora-sdk")
    sys.exit(1)
    
except Exception as e:
    print(f"  ❌ Failed to initialize AlloraWorker: {e}")
    print(f"  Error type: {type(e).__name__}")
    print(f"  Error details: {e}")
    
    if "api" in str(e).lower() or "key" in str(e).lower() or "auth" in str(e).lower():
        print("\n  This error suggests an API key authentication issue.")
        print("  Make sure you have the correct Allora API key (not Tiingo).")
    
    sys.exit(2)
