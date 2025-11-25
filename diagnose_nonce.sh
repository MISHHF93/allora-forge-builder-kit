#!/bin/bash
set -euo pipefail

TOPIC_ID=67
WORKER_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
RPC="https://allora-testnet-rpc.polkachu.com"

echo "[INFO] Checking unfulfilled nonces for topic $TOPIC_ID and worker $WORKER_ADDR..."

response=$(allorad query emissions unfulfilled-worker-nonces $TOPIC_ID --node "$RPC")

# Check if yq is available
if ! command -v yq &> /dev/null; then
  echo "[ERROR] yq is not installed. Please install it to parse YAML."
  exit 1
fi

# Parse response for worker match
has_nonce=$(echo "$response" | yq '.nonces.nonces[] | select(.worker == "'"$WORKER_ADDR"'") | .block_height' || true)

if [ -n "$has_nonce" ]; then
  echo "[✅] Worker has an unfulfilled nonce at block height: $has_nonce"
else
  echo "[⏳] No unfulfilled nonce currently available for this worker."
fi
