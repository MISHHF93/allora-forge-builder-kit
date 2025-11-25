#!/bin/bash
set -euo pipefail

TOPIC_ID=67
WORKER_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
RPC="https://allora-testnet-rpc.polkachu.com"
LOG_FILE="logs/submission.log"
HEAL_LOG="logs/heal_daemon.log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Check for yq
if ! command -v yq &> /dev/null; then
  echo "[ERROR] 'yq' is required. Please install yq." | tee -a "$HEAL_LOG"
  exit 1
fi

# Step 1: Check if worker has an unfulfilled nonce
response=$(allorad query emissions unfulfilled-worker-nonces "$TOPIC_ID" --node "$RPC")
has_nonce=$(echo "$response" | yq '.nonces.nonces[] | select(.worker == "'"$WORKER_ADDR"'") | .block_height' || true)

if [ -n "$has_nonce" ]; then
  echo "[$TIMESTAMP] ✅ Unfulfilled nonce found for worker at block $has_nonce" | tee -a "$HEAL_LOG"

  # Step 2: Check if submission already occurred in log
  if grep -q "block_height: \"$has_nonce\"" "$LOG_FILE"; then
    echo "[$TIMESTAMP] 🟢 Submission already attempted for block $has_nonce. No action needed." | tee -a "$HEAL_LOG"
  else
    echo "[$TIMESTAMP] ⚠️  No submission log found for block $has_nonce. Restarting daemon..." | tee -a "$HEAL_LOG"

    # Kill any running Python submit process
    pkill -f submit_prediction.py || true
    sleep 2

    # Restart it (assumes .venv is used)
    nohup .venv/bin/python submit_prediction.py --continuous >> "$LOG_FILE" 2>&1 &

    echo "[$TIMESTAMP] 🔄 Daemon restarted to attempt submission." | tee -a "$HEAL_LOG"
  fi
else
  echo "[$TIMESTAMP] ⏳ No nonce assigned to worker currently." | tee -a "$HEAL_LOG"
fi
