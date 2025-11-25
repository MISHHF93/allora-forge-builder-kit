#!/bin/bash
set -euo pipefail

RPC1="https://allora-testnet-rpc.polkachu.com"
RPC2="https://allora-rpc.testnet.allora.network"

TX_HASH=$(jq -r '.tx_hash' latest_submission.json)

if [ -z "$TX_HASH" ] || [ "$TX_HASH" == "null" ]; then
  echo "[ERROR] TX_HASH not found in latest_submission.json"
  exit 1
fi

echo "[INFO] Validating transaction: $TX_HASH"

# Declare global variable for the transaction JSON response
TX_JSON=""

check_tx() {
  local rpc=$1
  echo "[INFO] Querying $TX_HASH on $rpc ..."
  local response
  response=$(allorad query tx "$TX_HASH" --type=hash --output=json --node="$rpc" 2>/dev/null || true)

  if echo "$response" | jq -e '.code == 0' >/dev/null; then
    echo "[SUCCESS] Transaction $TX_HASH confirmed via $rpc"
    TX_JSON="$response"
    return 0
  else
    echo "[WARN] Transaction not confirmed via $rpc"
    return 1
  fi
}

# Try Polkachu RPC
if ! check_tx "$RPC1"; then
  # Fallback to official RPC
  if ! check_tx "$RPC2"; then
    echo "[ERROR] Transaction not confirmed on any known RPC."
    exit 2
  fi
fi

# Extract prediction value and topic_id from the JSON response
PREDICTION=$(echo "$TX_JSON" | jq -r '
  .events[] |
  select(.type == "emissions.v9.EventInsertInfererPayload") |
  .attributes[] |
  select(.key == "value") |
  .value' | tr -d '"')

TOPIC_ID=$(echo "$TX_JSON" | jq -r '
  .events[] |
  select(.type == "emissions.v9.EventInsertInfererPayload") |
  .attributes[] |
  select(.key == "topic_id") |
  .value' | tr -d '"')

if [ -n "$PREDICTION" ] && [ -n "$TOPIC_ID" ]; then
  echo "[INFO] Parsed prediction: $PREDICTION"
  echo "[INFO] Parsed topic ID: $TOPIC_ID"
else
  echo "[WARN] Could not parse prediction or topic_id from transaction data."
fi

