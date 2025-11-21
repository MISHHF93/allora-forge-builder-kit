#!/bin/bash
# Start the Allora competition pipeline with wallet credentials

# Set wallet credentials (User's production wallet)
export MNEMONIC="tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random"
export ALLORA_WALLET_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"

# Verify credentials are set
if [ -z "$MNEMONIC" ] || [ -z "$ALLORA_WALLET_ADDR" ]; then
    echo "ERROR: Wallet credentials not set!"
    exit 1
fi

echo "✅ Wallet credentials loaded:"
echo "   Address: $ALLORA_WALLET_ADDR"
echo "   Mnemonic: ${MNEMONIC:0:30}..."

# Start the pipeline
echo "🚀 Starting Allora competition pipeline..."
cd /workspaces/allora-forge-builder-kit
nohup python3 competition_submission.py > submission.log 2>&1 &

echo "✅ Pipeline started (PID: $!)"
echo "   Output: submission.log"
echo "   Monitor with: tail -f submission.log"
