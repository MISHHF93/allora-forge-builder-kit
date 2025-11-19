#!/usr/bin/env python3
"""Validate the ALLORA_API_KEY and wallet configuration without making submissions."""
import os
import re
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
if not api_key:
    print("  ❌ ALLORA_API_KEY not found in environment")
    sys.exit(1)

masked = api_key[:8] + "*" * (len(api_key) - 12) + api_key[-4:] if len(api_key) > 12 else "*" * len(api_key)
print(f"  ✅ ALLORA_API_KEY found: {masked}")
print(f"  Key length: {len(api_key)} characters")
looks_allora = api_key.startswith("UP-") and len(api_key) > 12
looks_tiingo = bool(re.fullmatch(r"[0-9a-fA-F]{32}", api_key))

if looks_tiingo:
    print("  ⚠️  WARNING: This key looks like a Tiingo token. Set TIINGO_API_KEY separately.")
elif not looks_allora:
    print("  ⚠️  WARNING: Expected Allora keys to start with 'UP-'. Double-check your developer portal key.")
else:
    print("  ✓ Key format matches Allora developer keys")

print("  ℹ️  Reminder: ALLORA_API_KEY is only used for fetching OHLCV market data.")

# Step 3: Ensure wallet credentials exist
print("\n[Step 3] Verifying wallet credentials...")
mnemonic = os.getenv("ALLORA_MNEMONIC") or os.getenv("MNEMONIC")
mnemonic_file = os.getenv("ALLORA_MNEMONIC_FILE") or os.getenv("MNEMONIC_FILE")
key_path = os.path.join(os.path.dirname(__file__), ".allora_key")
if mnemonic:
    print("  ✅ Mnemonic loaded from environment (hidden)")
elif mnemonic_file and os.path.exists(mnemonic_file):
    print(f"  ✅ Mnemonic file found: {mnemonic_file}")
elif os.path.exists(key_path):
    print(f"  ✅ Found .allora_key at {key_path}")
else:
    print("  ❌ Wallet mnemonic not found. Create .allora_key or set ALLORA_MNEMONIC.")
    sys.exit(1)

# Step 4: Initialize AlloraWorker with wallet (no API key)
print("\n[Step 4] Testing AlloraWorker initialization (wallet-based)...")
try:
    from allora_sdk.worker import AlloraWorker
    from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig
    print("  ✅ allora-sdk imported successfully")

    wallet_cfg = AlloraWalletConfig.from_env()
    network_cfg = AlloraNetworkConfig(
        chain_id=os.getenv("ALLORA_CHAIN_ID", "allora-testnet-1"),
        url=os.getenv("ALLORA_GRPC_URL") or "grpc+https://testnet-allora.lavenderfive.com:443",
        websocket_url=os.getenv("ALLORA_WS_URL") or "wss://testnet-rpc.lavenderfive.com:443/allora/websocket",
        fee_denom="uallo",
        fee_minimum_gas_price=10.0,
    )

    def dummy_run(topic_id: int) -> float:
        return 0.0

    worker = AlloraWorker(
        run=dummy_run,
        wallet=wallet_cfg,
        network=network_cfg,
        topic_id=67,
        polling_interval=15,
    )

    print("  ✅ AlloraWorker initialized without using ALLORA_API_KEY")

    addr = None
    for attr in ("wallet_address", "address", "wallet"):
        val = getattr(worker, attr, None)
        if isinstance(val, dict):
            val = val.get("address")
        if isinstance(val, str) and val:
            addr = val
            break
    if addr:
        print(f"  ✅ Wallet address: {addr}")
    else:
        print("  ⚠️  Could not automatically determine wallet address")

    print("\n" + "=" * 70)
    print("✅ TEST PASSED: API key ready for data fetches; wallet ready for submissions.")
    print("=" * 70)

except ImportError as e:
    print(f"  ❌ Failed to import allora-sdk: {e}")
    print("  Install with: pip install allora-sdk")
    sys.exit(1)
except Exception as e:
    print(f"  ❌ Failed to initialize AlloraWorker: {e}")
    print(f"  Error type: {type(e).__name__}")
    sys.exit(2)
