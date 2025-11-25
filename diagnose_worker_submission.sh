#!/bin/bash
set -euo pipefail

# === CONFIG ===
TOPIC_ID=67
WORKER_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
RPC="https://allora-testnet-rpc.polkachu.com"

echo "[INFO] 🧠 Running worker submission diagnostics for topic $TOPIC_ID..."
echo "[INFO] 🧩 Worker: $WORKER_ADDR"
echo "[INFO] 🌐 RPC: $RPC"

# === Get current block height ===
LATEST_BLOCK=$(curl -s "$RPC/status" | jq -r '.result.sync_info.latest_block_height')
echo "[INFO] ⛓️  Latest block height: $LATEST_BLOCK"

# === Get submission window status ===
echo "[INFO] 🔍 Querying submission window..."
WINDOW=$(allorad query emissions worker-submission-window-status "$TOPIC_ID" "$WORKER_ADDR" --node "$RPC")

WINDOW_START=$(echo "$WINDOW" | awk '/window_start_block:/ {print $2}' | head -n 1 | tr -d '"')
WINDOW_END=$(echo "$WINDOW" | awk '/window_end_block:/ {print $2}' | head -n 1 | tr -d '"')

if [[ -z "$WINDOW_START" || -z "$WINDOW_END" ]]; then
  echo "[ERROR] ❌ Could not retrieve window information."
  exit 1
fi

echo "[INFO] 🪟 Window: $WINDOW_START → $WINDOW_END"

# === Time left in window ===
BLOCKS_LEFT=$(( WINDOW_END - LATEST_BLOCK ))
SECONDS_LEFT=$(( BLOCKS_LEFT * 6 ))

if (( BLOCKS_LEFT <= 0 )); then
  echo "[WARN] ⚠️  Submission window has already ended!"
else
  echo "[INFO] ⏰ Estimated time remaining: $SECONDS_LEFT seconds (~$((SECONDS_LEFT / 60)) min)"
fi

# === Check if worker already submitted ===
echo "[INFO] 🧪 Checking latest inference..."
INFERENCE=$(allorad query emissions worker-latest-inference "$TOPIC_ID" "$WORKER_ADDR" --node "$RPC" 2>&1 || true)

if echo "$INFERENCE" | grep -q "not found"; then
  echo "[INFO] ❌ No submission found yet in this window."
else
  echo "[INFO] ✅ Submission appears to have been made."
  echo "$INFERENCE" | head -n 10
fi

# === Final summary ===
echo "[INFO] ✅ Diagnostics complete."
