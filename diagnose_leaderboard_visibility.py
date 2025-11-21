#!/usr/bin/env python3
"""
Diagnostic tool to identify why submissions aren't showing on the leaderboard.

Key insight: Submissions only appear on leaderboards when submitted to UNFULFILLED NONCES.
This tool checks:
1. Topic is active
2. Unfulfilled nonces exist
3. Reputers are present and scoring
4. Wallet balance and permissions
5. Submission timing relative to epoch windows
"""

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Try to import aiohttp for direct RPC calls
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

RPC_ENDPOINT = "https://rpc.ankr.com/allora_testnet"


async def json_rpc_call(method: str, params: list = None) -> Optional[dict]:
    """Make a JSON-RPC call to the Tendermint RPC endpoint."""
    if not AIOHTTP_AVAILABLE:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params or []
            }
            async with session.post(
                f"{RPC_ENDPOINT}/",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data:
                        return data["result"]
                    elif "error" in data:
                        logger.debug(f"JSON-RPC error: {data['error']}")
                        return None
    except Exception as e:
        logger.debug(f"JSON-RPC call failed: {e}")
    return None


def run_command(cmd: str) -> str:
    """Run shell command and return output."""
    try:
        # Use Allora testnet RPC endpoint for allorad commands
        if "allorad" in cmd:
            # Replace all --chain-id flags with --node flag
            import re
            cmd = re.sub(r'--chain-id\s+\S+', f'--node {RPC_ENDPOINT}', cmd)
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Command failed: {cmd}\nError: {e}")
        return ""


def check_topic_active(topic_id: int, chain_id: str = "allora-testnet-1") -> bool:
    """Check if topic is active on-chain."""
    logger.info(f"\n{'='*70}")
    logger.info(f"1️⃣  CHECKING TOPIC STATUS (Topic {topic_id})")
    logger.info(f"{'='*70}")
    
    cmd = f"allorad q emissions is-topic-active {topic_id} --chain-id {chain_id} -o json"
    output = run_command(cmd)
    
    if not output:
        logger.error("❌ Could not query topic status (allorad not available?)")
        logger.info("    Try: allorad q emissions topic 67 --chain-id allora-testnet-1")
        return False
    
    try:
        result = json.loads(output)
        is_active = result.get("active", False)
        
        if is_active:
            logger.info(f"✅ Topic {topic_id} is ACTIVE")
            return True
        else:
            logger.error(f"❌ Topic {topic_id} is NOT ACTIVE")
            logger.error("   🔴 REASON: Submissions to inactive topics won't appear on leaderboard")
            return False
    except json.JSONDecodeError:
        logger.warning(f"Could not parse response: {output}")
        return False


def check_unfulfilled_nonces(topic_id: int, chain_id: str = "allora-testnet-1") -> List[Dict]:
    """Get unfulfilled nonces for topic (CRITICAL for leaderboard visibility)."""
    logger.info(f"\n{'='*70}")
    logger.info(f"2️⃣  CHECKING UNFULFILLED NONCES (Topic {topic_id}) - CRITICAL")
    logger.info(f"{'='*70}")
    logger.info("⚠️  KEY INSIGHT: Submissions ONLY appear on leaderboard if sent to unfulfilled nonces!")
    
    cmd = f"allorad q emissions unfulfilled-worker-nonces {topic_id} --chain-id {chain_id} -o json"
    output = run_command(cmd)
    
    if not output:
        logger.error("❌ Could not query unfulfilled nonces")
        logger.info("    Try: allorad q emissions unfulfilled-worker-nonces 67 --chain-id allora-testnet-1")
        return []
    
    try:
        result = json.loads(output)
        nonces = result.get("nonces", [])
        
        if nonces:
            logger.info(f"✅ Found {len(nonces)} UNFULFILLED NONCE(S) - submissions CAN appear")
            for i, nonce_data in enumerate(nonces[:5]):  # Show first 5
                nonce = nonce_data.get("nonce")
                block = nonce_data.get("block_height")
                logger.info(f"   • Nonce {i+1}: {nonce} (block {block})")
            if len(nonces) > 5:
                logger.info(f"   ... and {len(nonces)-5} more")
            return nonces
        else:
            logger.error(f"❌ NO UNFULFILLED NONCES found for topic {topic_id}")
            logger.error("   🔴 CRITICAL: Without nonces, submissions CANNOT appear on leaderboard!")
            logger.error("   💡 Check if:")
            logger.error("      - Topic has met its submission quota for the epoch")
            logger.error("      - You're submitting outside the submission window (last ~10min of epoch)")
            logger.error("      - The epoch has just ended and new nonces haven't been created yet")
            return []
    except json.JSONDecodeError:
        logger.warning(f"Could not parse nonces response: {output}")
        return []


def check_active_reputers(topic_id: int, chain_id: str = "allora-testnet-1") -> int:
    """Get number of active reputers (required for scoring)."""
    logger.info(f"\n{'='*70}")
    logger.info(f"3️⃣  CHECKING ACTIVE REPUTERS (Topic {topic_id})")
    logger.info(f"{'='*70}")
    logger.info("ℹ️  Reputers validate and score submissions within 1-2 minutes")
    
    cmd = f"allorad q emissions active-reputers {topic_id} --chain-id {chain_id} -o json"
    output = run_command(cmd)
    
    if not output:
        logger.warning("❌ Could not query active reputers")
        logger.info("    Try: allorad q emissions active-reputers 67 --chain-id allora-testnet-1")
        return 0
    
    try:
        result = json.loads(output)
        reputers = result.get("reputers", [])
        
        if reputers:
            logger.info(f"✅ Found {len(reputers)} ACTIVE REPUTER(S)")
            for i, reputer in enumerate(reputers[:3]):
                logger.info(f"   • Reputer {i+1}: {reputer[:16]}...")
            return len(reputers)
        else:
            logger.error(f"❌ NO ACTIVE REPUTERS found for topic {topic_id}")
            logger.error("   🔴 WARNING: Without reputers, submissions won't be scored/validated")
            return 0
    except json.JSONDecodeError:
        logger.warning(f"Could not parse reputers response: {output}")
        return 0


def check_wallet_balance(wallet_addr: str, chain_id: str = "allora-testnet-1") -> Optional[float]:
    """Check wallet balance for gas fees."""
    logger.info(f"\n{'='*70}")
    logger.info(f"4️⃣  CHECKING WALLET BALANCE")
    logger.info(f"{'='*70}")
    logger.info(f"   Wallet: {wallet_addr}")
    
    cmd = f"allorad q bank balances {wallet_addr} --chain-id {chain_id} -o json"
    output = run_command(cmd)
    
    if not output:
        logger.warning("❌ Could not query wallet balance")
        logger.info("    Try: allorad q bank balances allo1... --chain-id allora-testnet-1")
        return None
    
    try:
        result = json.loads(output)
        balances = result.get("balances", [])
        
        for balance in balances:
            if balance.get("denom") == "uallo":
                amount_uallo = int(balance.get("amount", 0))
                amount_allo = amount_uallo / 1e18  # 1 ALLO = 1e18 uallo
                
                if amount_allo > 0.1:  # Should be plenty for gas
                    logger.info(f"✅ Sufficient balance: {amount_allo:.2f} ALLO")
                    return amount_allo
                else:
                    logger.error(f"❌ Low balance: {amount_allo:.2f} ALLO")
                    logger.error("   🔴 May not have enough for gas fees")
                    return amount_allo
        
        logger.error("❌ No ALLO balance found")
        return None
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Could not parse balance response: {e}")
        return None


def check_topic_details(topic_id: int, chain_id: str = "allora-testnet-1") -> Dict:
    """Get full topic details."""
    logger.info(f"\n{'='*70}")
    logger.info(f"5️⃣  CHECKING TOPIC DETAILS")
    logger.info(f"{'='*70}")
    
    cmd = f"allorad q emissions topic {topic_id} --chain-id {chain_id} -o json"
    output = run_command(cmd)
    
    if not output:
        logger.warning("❌ Could not query topic details")
        return {}
    
    try:
        topic = json.loads(output)
        
        # Extract key fields
        logger.info(f"Topic ID: {topic.get('id')}")
        logger.info(f"Creator: {topic.get('creator', 'N/A')[:20]}...")
        logger.info(f"Active: {topic.get('active', False)}")
        logger.info(f"Inference Synthesis Required: {topic.get('inference_synthesis_required', False)}")
        logger.info(f"Reputer Revenue Per Share: {topic.get('reputer_revenue_per_share', 'N/A')}")
        logger.info(f"Worker Submission Window: {topic.get('worker_submission_window', 'N/A')} seconds")
        logger.info(f"Epoch Length: {topic.get('epoch_length', 'N/A')} seconds")
        
        return topic
    except json.JSONDecodeError:
        logger.warning(f"Could not parse topic details")
        return {}


def check_wallet_submission_history(wallet_addr: str, topic_id: int, chain_id: str = "allora-testnet-1") -> List[Dict]:
    """Check if wallet has submitted before (and if submissions were accepted)."""
    logger.info(f"\n{'='*70}")
    logger.info(f"6️⃣  CHECKING SUBMISSION HISTORY")
    logger.info(f"{'='*70}")
    logger.info(f"   Wallet: {wallet_addr[:20]}...")
    logger.info(f"   Topic: {topic_id}")
    
    cmd = f"allorad q emissions inferer-score-ema {topic_id} {wallet_addr} --chain-id {chain_id} -o json"
    output = run_command(cmd)
    
    if not output:
        logger.warning("❌ No score history found (may be first submission)")
        return []
    
    try:
        result = json.loads(output)
        logger.info(f"✅ Found submission history:")
        logger.info(f"   EMA Score: {result.get('ema', 'N/A')}")
        logger.info(f"   Count: {result.get('count', 'N/A')}")
        return [result]
    except json.JSONDecodeError:
        logger.info("ℹ️  No previous score history (first submission likely)")
        return []


def analyze_submission_timing(topic_id: int, chain_id: str = "allora-testnet-1"):
    """Analyze if submissions are in the correct time window."""
    logger.info(f"\n{'='*70}")
    logger.info(f"7️⃣  ANALYZING SUBMISSION TIMING")
    logger.info(f"{'='*70}")
    
    # Get current block time
    cmd = f"allorad status --chain-id {chain_id} -o json"
    output = run_command(cmd)
    
    if not output:
        logger.warning("❌ Could not query current block time")
        return
    
    try:
        status = json.loads(output)
        current_time = status.get("sync_info", {}).get("latest_block_time", "")
        height = status.get("sync_info", {}).get("latest_block_height", "")
        
        logger.info(f"Current block time: {current_time}")
        logger.info(f"Current height: {height}")
        
        # Get topic details for epoch info
        cmd = f"allorad q emissions topic {topic_id} --chain-id {chain_id} -o json"
        output = run_command(cmd)
        
        if output:
            topic = json.loads(output)
            epoch_length = int(topic.get("epoch_length", 3600))
            window = int(topic.get("worker_submission_window", 600))
            
            logger.info(f"\nTopic Epoch Configuration:")
            logger.info(f"   Epoch length: {epoch_length}s (~{epoch_length//60} minutes)")
            logger.info(f"   Submission window: {window}s (~{window//60} minutes, end of epoch)")
            logger.info(f"\n💡 Submissions should be made in the last {window}s of each epoch")
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Could not analyze timing: {e}")


def diagnose_all(topic_id: int = 67, wallet_addr: str = None, chain_id: str = "allora-testnet-1"):
    """Run complete diagnostics."""
    logger.info("\n" + "=" * 70)
    logger.info("🔍 ALLORA LEADERBOARD VISIBILITY DIAGNOSTIC")
    logger.info("=" * 70)
    logger.info(f"Purpose: Identify why submissions aren't showing on leaderboard")
    logger.info(f"Date: {datetime.now(timezone.utc).isoformat()}")
    
    # Check prerequisites
    cmd_check = run_command("which allorad")
    if not cmd_check:
        logger.error("\n❌ FATAL: 'allorad' CLI not found on PATH")
        logger.error("   Install: https://github.com/allora-network/allora-chain")
        logger.error("   Or set up RPC endpoint for queries")
        return
    
    logger.info(f"✅ Found allorad: {cmd_check}")
    
    # Run diagnostics
    results = {}
    
    results["topic_active"] = check_topic_active(topic_id, chain_id)
    results["unfulfilled_nonces"] = check_unfulfilled_nonces(topic_id, chain_id)
    results["reputers_count"] = check_active_reputers(topic_id, chain_id)
    
    if wallet_addr:
        results["wallet_balance"] = check_wallet_balance(wallet_addr, chain_id)
        results["submission_history"] = check_wallet_submission_history(wallet_addr, topic_id, chain_id)
    
    results["topic_details"] = check_topic_details(topic_id, chain_id)
    analyze_submission_timing(topic_id, chain_id)
    
    # Summary
    logger.info(f"\n{'='*70}")
    logger.info("📊 DIAGNOSTIC SUMMARY & RECOMMENDATIONS")
    logger.info(f"{'='*70}")
    
    if not results["topic_active"]:
        logger.error("\n🔴 BLOCKER: Topic is not active")
        logger.error("   ACTION: Wait for topic to be activated or contact Allora support")
    
    if not results["unfulfilled_nonces"]:
        logger.error("\n🔴 BLOCKER: No unfulfilled nonces available")
        logger.error("   CAUSES:")
        logger.error("   1. Topic quota filled (max submissions per epoch reached)")
        logger.error("   2. Outside submission window (submit in last ~10min of epoch)")
        logger.error("   3. Epoch just ended (new nonces created with delay)")
        logger.error("   ACTION: Check epoch timing and try submitting during correct window")
    else:
        logger.info(f"\n✅ GOOD: {len(results['unfulfilled_nonces'])} unfulfilled nonce(s) available")
        logger.info("   ✓ Submissions CAN appear on leaderboard")
    
    if results["reputers_count"] < 1:
        logger.error("\n⚠️  WARNING: No active reputers")
        logger.error("   ACTION: Submissions won't be scored; they may not appear on leaderboard")
    else:
        logger.info(f"\n✅ GOOD: {results['reputers_count']} reputer(s) active")
        logger.info("   ✓ Submissions WILL be scored")
    
    if wallet_addr and results["wallet_balance"] is not None and results["wallet_balance"] < 0.1:
        logger.error("\n⚠️  WARNING: Low wallet balance")
        logger.error("   ACTION: Add ALLO for gas fees")
    
    logger.info(f"\n{'='*70}")
    logger.info("🎯 PRIMARY REASON SUBMISSIONS NOT ON LEADERBOARD:")
    logger.info(f"{'='*70}")
    
    if not results["unfulfilled_nonces"]:
        logger.error(">>> NO UNFULFILLED NONCES - Submissions cannot be accepted <<<")
        logger.error("\nFix: Ensure you're submitting during the submission window")
        logger.error("     (typically last 10 minutes of each 1-hour epoch)")
    elif not results["reputers_count"]:
        logger.error(">>> NO REPUTERS - Submissions won't be scored <<<")
        logger.error("\nFix: Contact Allora support to ensure reputers are running")
    else:
        logger.info(">>> All prerequisites met - check network/wallet permissions <<<")
        logger.info("    Submissions should be visible within 2-5 min (tx) + 1-2 min (scoring)")


if __name__ == "__main__":
    import os
    
    topic_id = int(os.getenv("TOPIC_ID", "67"))
    wallet_addr = os.getenv("ALLORA_WALLET_ADDR")
    chain_id = os.getenv("CHAIN_ID", "allora-testnet-1")
    
    diagnose_all(topic_id, wallet_addr, chain_id)
