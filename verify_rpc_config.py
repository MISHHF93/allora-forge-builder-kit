#!/usr/bin/env python3
"""Verify all RPC endpoints are correctly configured."""

import sys
from pathlib import Path

print("\n" + "="*70)
print("🔍 ALLORA TESTNET RPC CONFIGURATION VERIFICATION")
print("="*70 + "\n")

# Define expected endpoints
EXPECTED = {
    "RPC (HTTP)": "https://rpc.ankr.com/allora_testnet",
    "gRPC": "grpc+https://allora-rpc.testnet.allora.network/",
    "REST": "https://allora-rpc.testnet.allora.network/",
    "WebSocket": "wss://allora-rpc.testnet.allora.network/websocket",
    "Chain ID": "allora-testnet-1"
}

# Import and check modules
modules_to_check = [
    ("train.py", [
        ("DEFAULT_RPC", "https://rpc.ankr.com/allora_testnet"),
        ("DEFAULT_GRPC", "grpc+https://allora-rpc.testnet.allora.network/"),
        ("DEFAULT_REST", "https://allora-rpc.testnet.allora.network/"),
        ("DEFAULT_WEBSOCKET", "wss://allora-rpc.testnet.allora.network/websocket"),
        ("CHAIN_ID", "allora-testnet-1")
    ]),
    ("allora_forge_builder_kit.submission", [
        ("DEFAULT_RPC_URL", "https://rpc.ankr.com/allora_testnet"),
        ("DEFAULT_GRPC_URL", "grpc+https://allora-rpc.testnet.allora.network/"),
        ("DEFAULT_REST_URL", "https://allora-rpc.testnet.allora.network/"),
        ("DEFAULT_WEBSOCKET_URL", "wss://allora-rpc.testnet.allora.network/websocket")
    ])
]

all_correct = True

for module_name, checks in modules_to_check:
    print(f"📦 Module: {module_name}")
    try:
        module = __import__(module_name, fromlist=[check[0] for check in checks])
        for var_name, expected_val in checks:
            actual_val = getattr(module, var_name, None)
            if actual_val == expected_val:
                print(f"   ✅ {var_name}: {actual_val}")
            else:
                print(f"   ❌ {var_name}")
                print(f"      Expected: {expected_val}")
                print(f"      Got:      {actual_val}")
                all_correct = False
    except Exception as e:
        print(f"   ❌ Error loading module: {e}")
        all_correct = False
    print()

print("="*70)
if all_correct:
    print("✅ ALL RPC ENDPOINTS CORRECTLY CONFIGURED")
    print("\nEndpoints Summary:")
    for name, endpoint in EXPECTED.items():
        print(f"  • {name}: {endpoint}")
else:
    print("❌ SOME ENDPOINTS ARE MISCONFIGURED - SEE ABOVE")
print("="*70 + "\n")

sys.exit(0 if all_correct else 1)
