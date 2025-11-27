#!/bin/bash

# Configuration
WALLET_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
PREDICTION_FILE="artifacts/latest_submission.json"
CHAIN_ID="allora-testnet-1"
NODE_URL="https://allora-testnet-rpc.polkachu.com"
FEES="1000uallo"
KEYRING="test"

# Step 1: Ensure jq is installed
if ! command -v jq &> /dev/null; then
    echo "❌ jq is not installed. Please install it first."
    exit 1
fi

# Step 2: Check wallet address format
if [[ ! $WALLET_ADDR =~ ^allo1[a-z0-9]{38}$ ]]; then
    echo "❌ Wallet address format appears invalid: $WALLET_ADDR"
else
    echo "✅ Wallet address format looks valid."
fi

# Step 3: Extract prediction from file
if [[ ! -f "$PREDICTION_FILE" ]]; then
    echo "❌ Prediction file not found: $PREDICTION_FILE"
    exit 1
fi

PREDICTION=$(jq -r '.prediction_log_return_7d' "$PREDICTION_FILE")
if [[ -z "$PREDICTION" || "$PREDICTION" == "null" ]]; then
    echo "❌ Failed to extract prediction value from JSON."
    exit 1
fi

echo "✅ Prediction value extracted: $PREDICTION"

# Step 4: Dry-run the insert-worker-payload command with --generate-only
echo "🔍 Running dry-run with --generate-only..."

CMD_OUTPUT=$(allorad tx emissions insert-worker-payload \
    "$WALLET_ADDR" \
    "$PREDICTION" \
    --keyring-backend "$KEYRING" \
    --chain-id "$CHAIN_ID" \
    --fees "$FEES" \
    --gas auto \
    --gas-adjustment 1.3 \
    --node "$NODE_URL" \
    --generate-only 2>&1)

# Step 5: Check if dry-run succeeded
if echo "$CMD_OUTPUT" | grep -q "Error:"; then
    echo "❌ Dry-run failed with output:"
    echo "$CMD_OUTPUT"
    exit 1
else
    echo "✅ Dry-run succeeded. Here's the generated transaction:"
    echo "$CMD_OUTPUT"
fi

# Step 6: Next steps
echo "🎯 If dry-run works, you can submit with:"
echo ""
echo "allorad tx emissions insert-worker-payload \\"
echo "  \"$WALLET_ADDR\" \\"
echo "  \"$PREDICTION\" \\"
echo "  --keyring-backend $KEYRING \\"
echo "  --chain-id $CHAIN_ID \\"
echo "  --fees $FEES \\"
echo "  --gas auto \\"
echo "  --gas-adjustment 1.3 \\"
echo "  --node $NODE_URL \\"
echo "  -y"
