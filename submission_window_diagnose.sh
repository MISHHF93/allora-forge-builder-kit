#!/bin/bash
set -euo pipefail

TOPIC_ID=67
WORKER_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
RPC="https://allora-testnet-rpc.polkachu.com"

echo "[INFO] 🕵️  Diagnosing submission schedule for topic $TOPIC_ID and worker $WORKER_ADDR..."

# Get current latest block height
LATEST_BLOCK=$(curl -s "$RPC/status" | jq -r '.result.sync_info.latest_block_height')
echo "[INFO] 📦 Latest block height: $LATEST_BLOCK"

# Query unfulfilled nonces
NONCES_YAML=$(allorad query emissions unfulfilled-worker-nonces "$TOPIC_ID" --node "$RPC")

# Check for yq
if ! command -v yq >/dev/null 2>&1; then
  echo "[ERROR] 'yq' is not installed. Please install yq to parse YAML properly."
  exit 1
fi

# Extract relevant nonces
NONCE_BLOCKS=$(echo "$NONCES_YAML" | yq '.nonces.nonces[].block_height' 2>/dev/null || true)

if [ -z "$NONCE_BLOCKS" ]; then
  echo "[INFO] ✅ No unfulfilled nonces currently available."
  exit 0
fi

echo "[INFO] 🚨 Unfulfilled nonces detected:"
echo "$NONCE_BLOCKS" | while read -r block; do
  block_clean=$(echo "$block" | tr -d '"')
  echo " - Block height: $block_clean"

  # Arithmetic
  if [[ "$block_clean" =~ ^[0-9]+$ ]]; then
    block_diff=$((LATEST_BLOCK - block_clean))
    seconds_ago=$((block_diff * 6))
    minutes_ago=$((seconds_ago / 60))
    echo "   ⏱️  Estimated window opened: ~$seconds_ago seconds (~$minutes_ago min) ago"
  else
    echo "   ⚠️  Skipped invalid block number: $block_clean"
  fi
done

