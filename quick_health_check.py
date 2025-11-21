#!/usr/bin/env python3
"""
Quick health check for Allora submission pipeline.
This tool verifies that the system is ready to submit and identifies blockersusing SDK directly.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

# Add parent directory to path
sys.path.insert(0, '/workspaces/allora-forge-builder-kit')

from allora_sdk.rpc_client.config import AlloraWalletConfig, AlloraNetworkConfig
from allora_sdk.rpc_client import AlloraRPCClient


async def check_health():
    """Run all health checks."""
    print("\n" + "="*70)
    print("🏥 ALLORA SUBMISSION PIPELINE HEALTH CHECK")
    print("="*70)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    wallet_address = os.getenv("ALLORA_WALLET_ADDR", "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma")
    topic_id = 67
    
    print(f"📋 Configuration:")
    print(f"   Wallet: {wallet_address}")
    print(f"   Topic: {topic_id}")
    print(f"   Network: Allora Testnet")
    print()
    
    try:
        # Initialize network config
        network_config = AlloraNetworkConfig(
            chain_id="allora-testnet-1",
            url="grpc+https://testnet-allora.lavenderfive.com:443",
            websocket_url="wss://testnet-rpc.lavenderfive.com:443/allora/websocket",
            fee_denom="uallo",
            fee_minimum_gas_price=10.0
        )
        print("✅ Network config initialized")
    except Exception as e:
        print(f"❌ Failed to initialize network config: {e}")
        return False
    
    try:
        # Initialize RPC client
        client = AlloraRPCClient(network_config)
        print("✅ RPC client connected")
    except Exception as e:
        print(f"❌ Failed to connect to RPC: {e}")
        return False
    
    # Check 1: Topic Active
    print(f"\n1️⃣  CHECKING TOPIC STATUS (Topic {topic_id})")
    print("   " + "-"*66)
    try:
        topic = await client.query_topic(topic_id)
        if topic:
            print(f"   ✅ Topic {topic_id} exists")
            # Get topic loss function if available
            if hasattr(topic, 'loss_method'):
                print(f"   📊 Loss Method: {topic.loss_method}")
        else:
            print(f"   ❌ Could not retrieve topic {topic_id}")
    except Exception as e:
        print(f"   ⚠️  Could not query topic: {e}")
    
    # Check 2: Unfulfilled Nonces (CRITICAL)
    print(f"\n2️⃣  CHECKING UNFULFILLED NONCES (Topic {topic_id}) - CRITICAL")
    print("   " + "-"*66)
    print("   ⚠️  KEY: Submissions ONLY appear on leaderboard if sent to unfulfilled nonces!")
    try:
        nonces = await client.get_unfullfilled_worker_nonces(topic_id)
        if nonces:
            print(f"   ✅ Found {len(nonces)} unfulfilled nonces")
            print(f"      Ready to submit! ✓")
        else:
            print(f"   ❌ NO unfulfilled nonces available")
            print(f"      🔴 BLOCKER: Cannot submit right now")
            print(f"      Reasons:")
            print(f"      - Topic quota filled (max submissions per epoch)")
            print(f"      - Outside submission window (submit in last ~10 min of epoch)")
            print(f"      - Epoch just ended (new nonces created with delay)")
    except Exception as e:
        print(f"   ⚠️  Could not check nonces: {e}")
    
    # Check 3: Wallet Balance
    print(f"\n3️⃣  CHECKING WALLET BALANCE")
    print("   " + "-"*66)
    print(f"   Wallet: {wallet_address}")
    try:
        balance = await client.query_balance(wallet_address)
        if balance and balance > 0:
            print(f"   ✅ Balance: {balance} uallo")
            if balance > 10000:
                print(f"      Sufficient for multiple submissions ✓")
            else:
                print(f"      ⚠️  Low balance - may only be sufficient for few submissions")
        else:
            print(f"   ❌ NO BALANCE - Cannot submit")
            print(f"      Need to fund wallet at: {wallet_address}")
    except Exception as e:
        print(f"   ⚠️  Could not check balance: {e}")
    
    # Check 4: Active Reputers
    print(f"\n4️⃣  CHECKING ACTIVE REPUTERS (Topic {topic_id})")
    print("   " + "-"*66)
    print("   ℹ️  Reputers validate and score submissions within 1-2 minutes")
    try:
        reputers = await client.get_active_reputers(topic_id)
        if reputers:
            print(f"   ✅ Found {len(reputers)} active reputers")
            print(f"      Submissions will be scored ✓")
        else:
            print(f"   ❌ NO active reputers")
            print(f"      ⚠️  Submissions won't be scored (may not appear on leaderboard)")
    except Exception as e:
        print(f"   ⚠️  Could not check reputers: {e}")
    
    # Check 5: Submission History
    print(f"\n5️⃣  CHECKING SUBMISSION HISTORY")
    print("   " + "-"*66)
    print(f"   Wallet: {wallet_address}")
    print(f"   Topic: {topic_id}")
    try:
        score = await client.query_latest_score(topic_id, wallet_address)
        if score is not None:
            print(f"   ✅ Last submission scored: {score}")
            print(f"      You've successfully submitted before ✓")
        else:
            print(f"   ℹ️  No submission history yet (may be first submission)")
    except Exception as e:
        print(f"   ⚠️  Could not check submission history: {e}")
    
    print(f"\n" + "="*70)
    print("🎯 SUMMARY & NEXT STEPS")
    print("="*70)
    print("""
✅ If all checks pass:
   - Your system is HEALTHY
   - You can submit predictions
   - Run: python competition_submission.py

⚠️  If there are warnings:
   - Check the specific issues above
   - Most common: NO UNFULFILLED NONCES (normal outside submission window)
   - Solution: Submit during the correct epoch window

🔴 If there are blockers:
   - Cannot submit until issue is resolved
   - Common blocker: NO BALANCE (need to fund wallet)
   - Contact: Check Allora docs or support
    """)
    
    await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(check_health())
    except KeyboardInterrupt:
        print("\n⏹️  Health check cancelled")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Health check failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
