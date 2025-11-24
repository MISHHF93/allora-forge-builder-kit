#!/usr/bin/env python3
"""
Diagnostic Script: .env File and Wallet Validation
====================================================

Validates:
1. .env file is properly formatted and parsed
2. MNEMONIC has correct format (24 or 12 words)
3. ALLORA_WALLET_ADDR is valid bech32
4. RPC endpoints are reachable
5. LocalWallet can be created from mnemonic
"""

import os
import sys
import json
import re
from dotenv import load_dotenv
import requests

# Load .env
load_dotenv()

print("=" * 80)
print("ALLORA WALLET & RPC ENDPOINT DIAGNOSTIC")
print("=" * 80)

# 1. Check .env file location
print("\n📋 [STEP 1] Checking .env file...")
env_file_path = os.path.join(os.getcwd(), ".env")
if os.path.exists(env_file_path):
    print(f"✅ .env file found at: {env_file_path}")
    with open(env_file_path, "r") as f:
        env_content = f.read()
    print(f"   File size: {len(env_content)} bytes")
    print(f"   Lines: {len(env_content.split(chr(10)))}")
else:
    print(f"❌ .env file NOT found at: {env_file_path}")
    sys.exit(1)

# 2. Validate MNEMONIC
print("\n🔐 [STEP 2] Validating MNEMONIC...")
mnemonic = os.getenv("MNEMONIC", "").strip()
if not mnemonic:
    print("❌ MNEMONIC not set in .env")
    sys.exit(1)

mnemonic_words = mnemonic.split()
print(f"   Word count: {len(mnemonic_words)}")

if len(mnemonic_words) == 24:
    print("✅ MNEMONIC has 24 words (standard BIP39)")
elif len(mnemonic_words) == 12:
    print("✅ MNEMONIC has 12 words (also valid BIP39)")
else:
    print(f"❌ MNEMONIC has {len(mnemonic_words)} words (must be 12 or 24)")
    sys.exit(1)

# Check if all words are valid ASCII
all_ascii = all(ord(c) < 128 for word in mnemonic_words for c in word)
if all_ascii:
    print("✅ All words are ASCII (valid)")
else:
    print("❌ Some words contain non-ASCII characters")
    sys.exit(1)

print(f"   First word: {mnemonic_words[0]}")
print(f"   Last word: {mnemonic_words[-1]}")

# 3. Validate ALLORA_WALLET_ADDR
print("\n👛 [STEP 3] Validating ALLORA_WALLET_ADDR...")
wallet_addr = os.getenv("ALLORA_WALLET_ADDR", "").strip()
if not wallet_addr:
    print("❌ ALLORA_WALLET_ADDR not set in .env")
    sys.exit(1)

# Bech32 format check (Allora addresses start with "allo1")
if wallet_addr.startswith("allo1"):
    print(f"✅ Wallet address starts with 'allo1' (correct prefix)")
else:
    print(f"❌ Wallet address does NOT start with 'allo1': {wallet_addr[:10]}...")
    sys.exit(1)

# Length check (Bech32 Allora addresses are ~43 chars)
if len(wallet_addr) >= 40 and len(wallet_addr) <= 45:
    print(f"✅ Wallet address length is valid ({len(wallet_addr)} chars)")
else:
    print(f"❌ Wallet address length seems off ({len(wallet_addr)} chars, expected ~43)")

print(f"   Address: {wallet_addr}")

# 4. Check other required env vars
print("\n🔧 [STEP 4] Checking other required environment variables...")
required_vars = {
    "TIINGO_API_KEY": "Tiingo API key for data fetching",
    "TOPIC_ID": "Allora topic ID",
    "RPC_URL": "Primary RPC endpoint",
    "CHAIN_ID": "Blockchain chain ID",
    "FEE_DENOM": "Fee denomination",
}

for var_name, description in required_vars.items():
    value = os.getenv(var_name, "").strip()
    if value:
        masked_value = value[:20] + "..." if len(value) > 20 else value
        print(f"✅ {var_name}: {masked_value}")
    else:
        print(f"❌ {var_name}: NOT SET ({description})")

# 5. Test RPC endpoints from .env or defaults
print("\n🌐 [STEP 5] Testing RPC endpoint connectivity...")

# Load RPC endpoints (same logic as submit_prediction.py)
rpc_env = os.getenv("RPC_ENDPOINTS", "").strip()
rpc_endpoints = []

if rpc_env:
    # Handle comma-separated URLs
    if "," in rpc_env:
        urls = [url.strip() for url in rpc_env.split(",")]
        rpc_endpoints = [
            {"url": url if url.endswith("/") else url + "/", "name": f"Custom-{i+1}"} 
            for i, url in enumerate(urls)
        ]
        print(f"📋 Loaded {len(rpc_endpoints)} RPC endpoints from .env (RPC_ENDPOINTS)")
    # Handle JSON array format
    elif rpc_env.startswith("["):
        try:
            urls = json.loads(rpc_env)
            rpc_endpoints = [
                {"url": url if url.endswith("/") else url + "/", "name": f"Custom-{i+1}"} 
                for i, url in enumerate(urls)
            ]
            print(f"📋 Loaded {len(rpc_endpoints)} RPC endpoints from .env (JSON format)")
        except json.JSONDecodeError:
            print("⚠️  RPC_ENDPOINTS in .env is not valid JSON, using defaults")

# Fall back to hardcoded defaults if no .env config
if not rpc_endpoints:
    rpc_endpoints = [
        {"url": "https://allora-rpc.testnet.allora.network/", "name": "Primary"},
        {"url": "https://allora-testnet-rpc.allthatnode.com:1317/", "name": "AllThatNode"},
        {"url": "https://allora.api.chandrastation.com/", "name": "ChandraStation"},
    ]
    print(f"📋 Using {len(rpc_endpoints)} hardcoded RPC endpoints")

print(f"\n   Testing {len(rpc_endpoints)} endpoint(s):")
for endpoint in rpc_endpoints:
    try:
        response = requests.get(
            endpoint["url"],
            timeout=5,
            headers={"User-Agent": "allora-diagnostic/1.0"}
        )
        if response.status_code < 500:
            print(f"   ✅ {endpoint['name']}: Responsive ({response.status_code})")
        else:
            print(f"   ⚠️  {endpoint['name']}: Server error ({response.status_code})")
    except requests.exceptions.ConnectTimeout:
        print(f"   ❌ {endpoint['name']}: Connection timeout")
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ {endpoint['name']}: Connection error - {str(e)[:50]}")
    except Exception as e:
        print(f"   ⚠️  {endpoint['name']}: {type(e).__name__}")

# 6. Try to create wallet from mnemonic
print("\n🔓 [STEP 6] Testing wallet creation from mnemonic...")
try:
    from allora_sdk import LocalWallet
    try:
        wallet_obj = LocalWallet.from_mnemonic(mnemonic)
        print(f"✅ LocalWallet created successfully from mnemonic")
        print(f"   Wallet address: {wallet_obj.address}")
        print(f"   Private key exists: {wallet_obj._private_key is not None}")
        
        # Compare with env wallet
        if wallet_obj.address == wallet_addr:
            print(f"✅ Wallet address matches ALLORA_WALLET_ADDR")
        else:
            print(f"⚠️  Wallet address from mnemonic ({wallet_obj.address}) != env variable ({wallet_addr})")
            print(f"   This might be okay if using different derivation paths")
    except ValueError as e:
        print(f"❌ Failed to create wallet: {e}")
        print(f"   Error type: ValueError")
        print(f"   Common causes:")
        print(f"     - Invalid mnemonic (not in BIP39 word list)")
        print(f"     - Mnemonic corrupted (extra spaces, wrong encoding)")
        print(f"   Solution: Verify mnemonic is exactly as generated")
    except Exception as e:
        print(f"❌ Unexpected error: {type(e).__name__}: {e}")
except ImportError:
    print("❌ allora_sdk not installed - cannot test wallet creation")
    print("   Install with: pip install allora-sdk")

print("\n" + "=" * 80)
print("DIAGNOSTIC COMPLETE")
print("=" * 80)
