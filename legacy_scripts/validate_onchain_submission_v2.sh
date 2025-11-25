#!/bin/bash

JSON_FILE="latest_submission.json"
HISTORY_FILE="submission_history.csv"
RPC_ETH="https://rpc.ankr.com/allora_testnet"
RPC_COSMOS="https://allora-testnet-rpc.polkachu.com"
LEADERBOARD_URL="https://forge.allora.network/competitions/21"
TMP_HTML="/tmp/leaderboard.html"

command -v jq >/dev/null 2>&1 || { echo "❌ jq missing"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "❌ curl missing"; exit 1; }

TX_HASH=$(jq -r '.tx_hash' "$JSON_FILE")
STATUS=$(jq -r '.status' "$JSON_FILE")
TIMESTAMP=$(jq -r '.timestamp' "$JSON_FILE")

if [[ -z "$TX_HASH" || "$TX_HASH" == "null" ]]; then
  echo "❌ No TX hash in $JSON_FILE"
  exit 1
fi

echo "🔍 TX_HASH: $TX_HASH"
echo "📦 Status: $STATUS"
echo "🕒 Timestamp: $TIMESTAMP"

# First attempt (eth style)
RESPONSE=$(curl -s -X POST "$RPC_ETH" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "method":"eth_getTransactionReceipt",
    "params":["0x'"$TX_HASH"'"],
    "id":1
  }')

if echo "$RESPONSE" | jq . >/dev/null 2>&1; then
  CONFIRMED=$(echo "$RESPONSE" | jq -r '.result.status')
  if [[ "$CONFIRMED" == "0x1" ]]; then
    FINAL_STATUS="confirmed"
  elif [[ "$CONFIRMED" == "0x0" ]]; then
    FINAL_STATUS="failed"
  else
    FINAL_STATUS="pending"
  fi
else
  echo "⚠️  Eth‑style RPC returned non‑JSON or unsupported method."
  # Try Cosmos style
  RESPONSE2=$(curl -s "$RPC_COSMOS/tx?hash=0x$TX_HASH")
  if echo "$RESPONSE2" | jq . >/dev/null 2>&1; then
    # inspect JSON result: maybe result.code=0 means success
    CODE=$(echo "$RESPONSE2" | jq -r '.result.tx_result.code')
    if [[ "$CODE" == "0" ]]; then
      FINAL_STATUS="confirmed"
    else
      FINAL_STATUS="failed"
    fi
  else
    FINAL_STATUS="unvalidated_rpc_error"
  fi
fi

# Log
echo "$TIMESTAMP,$TX_HASH,$STATUS,$FINAL_STATUS" >> "$HISTORY_FILE"
echo "📝 Logged to $HISTORY_FILE"

# Leaderboard check
curl -s "$LEADERBOARD_URL" > "$TMP_HTML"
echo "[LEADERBOARD snapshot]"
grep -A2 "Mish or Ariel" "$TMP_HTML" | sed 's/<[^>]*>//g' || echo "❌ Participant not found"

exit 0
