#!/usr/bin/env python3
"""
Enhanced submission validator module for Allora competition.

Validates that all requirements are met before attempting submission:
- Topic is active
- Unfulfilled nonces exist
- Reputers are present
- Wallet has sufficient balance
- Submission is within the correct time window
- Nonce hasn't already been fulfilled by another worker
"""

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AllroraSubmissionValidator:
    """Validates submission eligibility before attempting to submit."""
    
    def __init__(self, topic_id: int, wallet_addr: str, chain_id: str = "allora-testnet-1"):
        self.topic_id = topic_id
        self.wallet_addr = wallet_addr
        self.chain_id = chain_id
        self.rpc_url = "https://rpc.ankr.com/allora_testnet"
        
    def run_allorad(self, cmd: str) -> str:
        """Run allorad command and return JSON output."""
        try:
            # Use Allora testnet RPC endpoint for queries
            full_cmd = f"allorad {cmd} --node https://rpc.ankr.com/allora_testnet -o json"
            result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.debug(f"Command failed: {result.stderr}")
                return ""
            return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Command execution error: {e}")
            return ""
    
    def check_topic_active(self) -> Tuple[bool, str]:
        """Check if topic is active on-chain."""
        logger.info(f"🔍 Checking if topic {self.topic_id} is active...")
        
        output = self.run_allorad(f"q emissions is-topic-active {self.topic_id}")
        if not output:
            return False, "Could not query topic status (allorad unavailable)"
        
        try:
            result = json.loads(output)
            is_active = result.get("active", False)
            if is_active:
                logger.info(f"   ✅ Topic {self.topic_id} is ACTIVE")
                return True, "Topic is active"
            else:
                logger.error(f"   ❌ Topic {self.topic_id} is INACTIVE")
                return False, "Topic is not active on-chain"
        except json.JSONDecodeError:
            return False, "Could not parse topic status response"
    
    def check_unfulfilled_nonces(self) -> Tuple[List[Dict], str]:
        """Check if unfulfilled nonces exist (CRITICAL for visibility)."""
        logger.info(f"🔍 Checking for unfulfilled nonces on topic {self.topic_id}...")
        
        output = self.run_allorad(f"q emissions unfulfilled-worker-nonces {self.topic_id}")
        if not output:
            return [], "Could not query unfulfilled nonces"
        
        try:
            result = json.loads(output)
            nonces = result.get("nonces", [])
            
            if nonces:
                logger.info(f"   ✅ Found {len(nonces)} unfulfilled nonce(s)")
                return nonces, f"Found {len(nonces)} unfulfilled nonces"
            else:
                logger.error(f"   ❌ No unfulfilled nonces available")
                logger.error("      REASON: Topic quota filled or outside submission window")
                return [], "No unfulfilled nonces - submission would not appear on leaderboard"
        except json.JSONDecodeError:
            return [], "Could not parse nonces response"
    
    def check_active_reputers(self) -> Tuple[int, str]:
        """Check if active reputers exist to score submissions."""
        logger.info(f"🔍 Checking for active reputers on topic {self.topic_id}...")
        
        output = self.run_allorad(f"q emissions active-reputers {self.topic_id}")
        if not output:
            return 0, "Could not query active reputers"
        
        try:
            result = json.loads(output)
            reputers = result.get("reputers", [])
            
            if reputers:
                logger.info(f"   ✅ Found {len(reputers)} active reputer(s)")
                return len(reputers), f"Found {len(reputers)} active reputers"
            else:
                logger.warning(f"   ⚠️  No active reputers found")
                return 0, "No active reputers - submissions won't be scored"
        except json.JSONDecodeError:
            return 0, "Could not parse reputers response"
    
    def check_wallet_balance(self, min_balance_allo: float = 0.1) -> Tuple[bool, str]:
        """Check if wallet has sufficient balance for gas fees."""
        logger.info(f"🔍 Checking wallet balance for {self.wallet_addr[:20]}...")
        
        output = self.run_allorad(f"q bank balances {self.wallet_addr}")
        if not output:
            return False, "Could not query wallet balance"
        
        try:
            result = json.loads(output)
            balances = result.get("balances", [])
            
            for balance in balances:
                if balance.get("denom") == "uallo":
                    amount_uallo = int(balance.get("amount", 0))
                    amount_allo = amount_uallo / 1e18
                    
                    if amount_allo >= min_balance_allo:
                        logger.info(f"   ✅ Sufficient balance: {amount_allo:.2f} ALLO")
                        return True, f"Wallet has {amount_allo:.2f} ALLO"
                    else:
                        logger.error(f"   ❌ Insufficient balance: {amount_allo:.4f} ALLO (need {min_balance_allo})")
                        return False, f"Insufficient balance: {amount_allo:.4f} ALLO"
            
            logger.error(f"   ❌ No ALLO balance found")
            return False, "No ALLO balance found in wallet"
        except (json.JSONDecodeError, ValueError) as e:
            return False, f"Could not parse balance: {e}"
    
    def check_submission_window(self) -> Tuple[bool, str]:
        """Check if current time is within submission window."""
        logger.info(f"🔍 Checking if we're in submission window for topic {self.topic_id}...")
        
        # Get topic epoch config
        output = self.run_allorad(f"q emissions topic {self.topic_id}")
        if not output:
            return True, "Could not check submission window (skipping)"  # Non-critical
        
        try:
            topic = json.loads(output)
            epoch_length = int(topic.get("epoch_length", 3600))
            window_length = int(topic.get("worker_submission_window", 600))
            
            # Get current block time
            status_output = self.run_allorad("status")
            if not status_output:
                return True, "Could not check current time (skipping)"
            
            status = json.loads(status_output)
            current_time = status.get("sync_info", {}).get("latest_block_time", "")
            
            if not current_time:
                return True, "Could not parse current time (skipping)"
            
            # Parse timestamp
            dt = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
            timestamp = dt.timestamp()
            epoch_position = int(timestamp) % epoch_length
            window_start = epoch_length - window_length
            
            if epoch_position >= window_start:
                remaining = window_length - (epoch_position - window_start)
                logger.info(f"   ✅ Within submission window ({remaining}s remaining)")
                return True, f"Within submission window ({remaining}s remaining)"
            else:
                seconds_until = window_start - epoch_position
                logger.warning(f"   ⚠️  Outside submission window ({seconds_until}s until next window)")
                return False, f"Outside submission window (in {seconds_until}s)"
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Could not check window timing: {e}")
            return True, "Could not verify submission window (skipping)"
    
    async def validate_all(self, strict: bool = False) -> Tuple[bool, List[str]]:
        """
        Run all validation checks.
        
        Args:
            strict: If True, all checks must pass (including warnings).
                   If False, only critical checks must pass.
        
        Returns:
            (is_valid, [warnings/errors])
        """
        logger.info("\n" + "="*70)
        logger.info("🔍 RUNNING PRE-SUBMISSION VALIDATION CHECKS")
        logger.info("="*70)
        
        issues = []
        critical_issues = []
        
        # CRITICAL: Check topic is active
        active, msg = self.check_topic_active()
        if not active:
            critical_issues.append(f"CRITICAL: {msg}")
        
        # CRITICAL: Check unfulfilled nonces exist
        nonces, msg = self.check_unfulfilled_nonces()
        if not nonces:
            critical_issues.append(f"CRITICAL: {msg} - Your submission won't appear on leaderboard!")
        
        # WARNING: Check reputers exist
        reputers_count, msg = self.check_active_reputers()
        if reputers_count == 0:
            issues.append(f"WARNING: {msg} - Submissions won't be scored")
        
        # WARNING: Check wallet balance
        has_balance, msg = self.check_wallet_balance()
        if not has_balance:
            issues.append(f"WARNING: {msg}")
        
        # INFO: Check submission window
        in_window, msg = self.check_submission_window()
        if not in_window:
            issues.append(f"INFO: {msg}")
        
        # Summary
        logger.info("\n" + "="*70)
        logger.info("📋 VALIDATION SUMMARY")
        logger.info("="*70)
        
        if critical_issues:
            logger.error("\n🔴 CRITICAL ISSUES (submission will fail or won't be visible):")
            for issue in critical_issues:
                logger.error(f"   • {issue}")
        
        if issues:
            logger.warning("\n⚠️  WARNINGS (submission may succeed but with limitations):")
            for issue in issues:
                logger.warning(f"   • {issue}")
        
        is_valid = len(critical_issues) == 0
        if strict:
            is_valid = is_valid and len(issues) == 0
        
        if is_valid:
            logger.info("\n✅ VALIDATION PASSED - Safe to submit")
        else:
            logger.error("\n❌ VALIDATION FAILED - Do not submit (or submission won't be visible)")
        
        all_issues = critical_issues + issues
        return is_valid, all_issues


async def validate_before_submission(
    topic_id: int,
    wallet_addr: str,
    chain_id: str = "allora-testnet-1",
    strict: bool = False
) -> Tuple[bool, List[str]]:
    """
    Convenience function to validate submission eligibility.
    
    Returns:
        (is_valid, [issues])
    """
    validator = AllroraSubmissionValidator(topic_id, wallet_addr, chain_id)
    return await validator.validate_all(strict=strict)


# Example usage
if __name__ == "__main__":
    import os
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    topic_id = int(os.getenv("TOPIC_ID", "67"))
    wallet_addr = os.getenv("ALLORA_WALLET_ADDR", "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma")
    
    # Run validation
    is_valid, issues = asyncio.run(validate_before_submission(topic_id, wallet_addr, strict=False))
    
    if not is_valid:
        print(f"\n❌ Validation failed with {len(issues)} issue(s)")
        sys.exit(1)
    else:
        print(f"\n✅ Validation passed - ready to submit")
        sys.exit(0)
