#!/usr/bin/env python3
"""
Setup wallet on Allora testnet.

This script handles:
1. Creating a wallet from mnemonic if needed
2. Funding the wallet (requires testnet faucet)
3. Verifying wallet is on-chain
4. Registering wallet for a topic if needed

Usage:
    # Show wallet info
    python setup_wallet.py --info
    
    # Create wallet from mnemonic
    python setup_wallet.py --create
    
    # Check wallet balance
    python setup_wallet.py --balance
    
    # Request faucet tokens (if faucet available)
    python setup_wallet.py --faucet
    
    # Verify wallet exists on-chain
    python setup_wallet.py --verify
    
    # Register wallet for Topic 67
    python setup_wallet.py --register-topic 67
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from typing import Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
CHAIN_ID = "allora-testnet-1"
RPC_URL = "https://testnet-rpc.lavenderfive.com:443/allora/"
REST_URL = "https://testnet-rest.lavenderfive.com:443/allora/"
FAUCET_URL = "https://faucet.testnet.allora.network"  # May vary
DEFAULT_GAS = "300000"
DEFAULT_FEES = "1000uallo"


def run_cmd(cmd: list, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)


def get_wallet_address(wallet_name: str = "test-wallet") -> Optional[str]:
    """Get wallet address from allorad."""
    rc, out, err = run_cmd(["allorad", "keys", "show", wallet_name, "-a", "--keyring-backend", "test"])
    if rc == 0:
        address = out.strip()
        if address.startswith("allo1"):
            return address
    logger.warning(f"Could not retrieve wallet address: {err}")
    return None


def wallet_exists(wallet_name: str = "test-wallet") -> bool:
    """Check if wallet exists in allorad keyring."""
    rc, _, _ = run_cmd(["allorad", "keys", "show", wallet_name, "--keyring-backend", "test"])
    return rc == 0


def create_wallet_from_mnemonic(mnemonic: str, wallet_name: str = "test-wallet") -> Optional[str]:
    """Create wallet from mnemonic phrase."""
    if wallet_exists(wallet_name):
        logger.info(f"Wallet '{wallet_name}' already exists")
        return get_wallet_address(wallet_name)
    
    logger.info(f"Creating wallet '{wallet_name}' from mnemonic...")
    
    # Use echo to pipe mnemonic to allorad (keys add doesn't need --yes)
    cmd = f"echo '{mnemonic}' | allorad keys add {wallet_name} --recover --keyring-backend test"
    rc, out, err = run_cmd(["bash", "-c", cmd])
    
    if rc == 0:
        address = get_wallet_address(wallet_name)
        if address:
            logger.info(f"✅ Wallet created: {address}")
            return address
        else:
            logger.error("Wallet created but could not retrieve address")
            return None
    else:
        logger.error(f"Failed to create wallet: {err}")
        return None


def check_account_on_chain(address: str) -> Tuple[bool, Optional[dict]]:
    """Check if account exists on-chain via REST API."""
    logger.info(f"Checking if account {address} exists on-chain...")
    
    try:
        import requests
        url = f"{REST_URL}cosmos/auth/v1beta1/accounts/{address}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            account = data.get("account", {})
            logger.info(f"✅ Account found on-chain: {account.get('address')}")
            return True, account
        elif resp.status_code == 404:
            logger.warning(f"❌ Account NOT found on-chain (404)")
            logger.warning(f"   Wallet needs to be funded first to create on-chain account")
            return False, None
        else:
            logger.error(f"REST API error: {resp.status_code} - {resp.text[:200]}")
            return False, None
    except Exception as e:
        logger.error(f"Failed to query account: {e}")
        return False, None


def get_wallet_balance(address: str) -> Optional[dict]:
    """Get wallet balance via REST API."""
    logger.info(f"Checking balance for {address}...")
    
    try:
        import requests
        url = f"{REST_URL}cosmos/bank/v1beta1/balances/{address}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            balances = data.get("balances", [])
            if balances:
                for balance in balances:
                    amount = balance.get("amount", "0")
                    denom = balance.get("denom", "")
                    if "allo" in denom.lower():
                        # Convert uallo to allo
                        allo_amount = int(amount) / 1e6
                        logger.info(f"✅ Balance: {allo_amount:.6f} ALLO")
                        return {"amount": amount, "denom": denom, "allo": allo_amount}
            logger.info(f"ℹ️  No ALLO balance found (account may not be funded)")
            return None
        elif resp.status_code == 404:
            logger.warning(f"❌ Account not found on-chain (404)")
            return None
        else:
            logger.error(f"REST API error: {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"Failed to get balance: {e}")
        return None


def request_faucet_tokens(address: str) -> bool:
    """Request tokens from faucet (implementation depends on faucet API)."""
    logger.info(f"Requesting faucet tokens for {address}...")
    
    try:
        import requests
        
        # Try common faucet endpoints
        faucet_endpoints = [
            (f"{FAUCET_URL}/claim", {"address": address}),  # POST data
            (f"{FAUCET_URL}/api/claim", {"address": address}),
        ]
        
        for endpoint, data in faucet_endpoints:
            try:
                logger.info(f"  Trying: {endpoint}")
                resp = requests.post(endpoint, json=data, timeout=10)
                
                if resp.status_code in (200, 201):
                    logger.info(f"✅ Faucet request successful!")
                    logger.info(f"   Response: {resp.text[:200]}")
                    logger.info(f"   Wait 30-60 seconds for tokens to arrive...")
                    return True
                elif resp.status_code == 429:
                    logger.warning(f"⚠️  Faucet rate limited (429) - try again later")
                    return False
            except requests.RequestException:
                continue
        
        logger.warning(f"❌ Could not reach faucet at {FAUCET_URL}")
        logger.info("   Manual funding may be required - check testnet faucet docs")
        return False
        
    except ImportError:
        logger.error("requests library required for faucet - install with: pip install requests")
        return False
    except Exception as e:
        logger.error(f"Faucet request failed: {e}")
        return False


def register_topic_worker(address: str, topic_id: int, wallet_name: str = "test-wallet") -> bool:
    """Register wallet as worker for a topic."""
    logger.info(f"Registering {address} for topic {topic_id}...")
    
    cmd = [
        "allorad", "tx", "emissions", "register-inferer",
        str(topic_id),
        "--from", wallet_name,
        "--chain-id", CHAIN_ID,
        "--gas", DEFAULT_GAS,
        "--fees", DEFAULT_FEES,
        "--yes",
        "--output", "json",
    ]
    
    rc, out, err = run_cmd(cmd, timeout=60)
    
    if rc == 0:
        try:
            response = json.loads(out)
            tx_hash = response.get("txhash")
            logger.info(f"✅ Registration successful!")
            logger.info(f"   TxHash: {tx_hash}")
            return True
        except:
            logger.info(f"✅ Registration command succeeded")
            return True
    else:
        logger.error(f"Registration failed: {err[:200]}")
        return False


def show_wallet_info(wallet_name: str = "test-wallet") -> None:
    """Display wallet information."""
    logger.info("=== Wallet Information ===\n")
    
    if not wallet_exists(wallet_name):
        logger.error(f"Wallet '{wallet_name}' not found")
        logger.info(f"Create with: python setup_wallet.py --create")
        return
    
    address = get_wallet_address(wallet_name)
    if not address:
        logger.error(f"Could not retrieve address for {wallet_name}")
        return
    
    logger.info(f"Wallet Name: {wallet_name}")
    logger.info(f"Address: {address}\n")
    
    # Check on-chain status
    exists, account = check_account_on_chain(address)
    logger.info(f"On-Chain Status: {'✅ Exists' if exists else '❌ Not found'}")
    
    if exists and account:
        logger.info(f"Account Sequence: {account.get('sequence', 'N/A')}")
        logger.info(f"Account Number: {account.get('account_number', 'N/A')}")
    
    # Check balance
    balance = get_wallet_balance(address)
    if balance:
        logger.info(f"✅ Balance: {balance['allo']:.6f} ALLO")
    else:
        logger.warning(f"❌ No balance or account not funded")


def main():
    """Main CLI."""
    parser = argparse.ArgumentParser(
        description="Setup Allora testnet wallet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument("--wallet", default="test-wallet", help="Wallet name (default: test-wallet)")
    parser.add_argument("--mnemonic", help="Mnemonic phrase for wallet creation")
    parser.add_argument("--info", action="store_true", help="Show wallet information")
    parser.add_argument("--create", action="store_true", help="Create wallet from mnemonic")
    parser.add_argument("--balance", action="store_true", help="Check wallet balance")
    parser.add_argument("--verify", action="store_true", help="Verify wallet exists on-chain")
    parser.add_argument("--faucet", action="store_true", help="Request faucet tokens")
    parser.add_argument("--register-topic", type=int, help="Register wallet for topic")
    
    args = parser.parse_args()
    
    # Read mnemonic from environment if available
    if args.create or (not any([args.info, args.balance, args.verify, args.faucet, args.register_topic])):
        if args.mnemonic:
            mnemonic = args.mnemonic
        else:
            mnemonic = os.getenv("MNEMONIC", "").strip()
        
        if mnemonic:
            create_wallet_from_mnemonic(mnemonic, args.wallet)
        elif not wallet_exists(args.wallet):
            logger.error("Wallet not found and no mnemonic provided")
            logger.info("Provide mnemonic via: --mnemonic or MNEMONIC environment variable")
            sys.exit(1)
    
    # Execute requested action
    if args.info:
        show_wallet_info(args.wallet)
    elif args.balance:
        address = get_wallet_address(args.wallet)
        if address:
            get_wallet_balance(address)
    elif args.verify:
        address = get_wallet_address(args.wallet)
        if address:
            exists, _ = check_account_on_chain(address)
            sys.exit(0 if exists else 1)
    elif args.faucet:
        address = get_wallet_address(args.wallet)
        if address:
            success = request_faucet_tokens(address)
            sys.exit(0 if success else 1)
    elif args.register_topic:
        address = get_wallet_address(args.wallet)
        if address:
            success = register_topic_worker(address, args.register_topic, args.wallet)
            sys.exit(0 if success else 1)
    else:
        show_wallet_info(args.wallet)


if __name__ == "__main__":
    main()
