#!/bin/bash
# Quick wallet check and setup for Allora testnet

set -e

echo "=== Allora Wallet Setup Assistant ==="
echo

# Check wallet exists
if ! allorad keys show test-wallet -a --keyring-backend test 2>/dev/null; then
    echo "❌ Wallet 'test-wallet' not found"
    echo
    echo "To create it, set MNEMONIC environment variable:"
    echo '  export MNEMONIC="your 24-word phrase"'
    echo "  python setup_wallet.py --create"
    echo
    exit 1
fi

WALLET_ADDR=$(allorad keys show test-wallet -a --keyring-backend test)
echo "✅ Wallet found: $WALLET_ADDR"
echo

# Check on-chain status
echo "Checking account status on-chain..."
STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://testnet-rest.lavenderfive.com:443/allora/cosmos/auth/v1beta1/accounts/$WALLET_ADDR" 2>/dev/null || echo "000")

if [ "$STATUS_CODE" = "200" ]; then
    echo "✅ Account EXISTS on-chain"
    
    # Check balance
    BALANCE=$(curl -s "https://testnet-rest.lavenderfive.com:443/allora/cosmos/bank/v1beta1/balances/$WALLET_ADDR" 2>/dev/null | \
        grep -o '"amount":"[0-9]*' | grep -o '[0-9]*' | head -1)
    
    if [ -n "$BALANCE" ] && [ "$BALANCE" != "0" ]; then
        ALLO=$(echo "scale=6; $BALANCE / 1000000" | bc 2>/dev/null || echo "unknown")
        echo "✅ Balance: $ALLO ALLO"
        echo
        echo "✅ Ready to submit! Try:"
        echo "  python train_and_submit_sdk.py --submit --retrain"
    else
        echo "⚠️  Account exists but balance is 0"
        echo
        echo "Get tokens from faucet:"
        echo "  python setup_wallet.py --faucet"
    fi
else
    echo "❌ Account NOT found on-chain (status: $STATUS_CODE)"
    echo
    echo "The wallet exists locally but hasn't been created on-chain yet."
    echo "This is normal - blockchain accounts are lazy-created."
    echo
    echo "Solution: Fund your wallet to create the account:"
    echo "  1. Use faucet: python setup_wallet.py --faucet"
    echo "  2. Or manually send ALLO to: $WALLET_ADDR"
    echo "  3. Visit: https://faucet.testnet.allora.network"
    echo
    echo "After funding, wait 30-60 seconds and try again:"
    echo "  bash check_wallet.sh"
    echo "  python train_and_submit_sdk.py --submit"
fi
