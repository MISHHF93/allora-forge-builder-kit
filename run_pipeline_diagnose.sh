#!/bin/bash

set -euo pipefail

# CONFIGURATION
TOPIC_ID="67"
ADDRESS="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
BLOCK_LOG="diagnostic_block_heights.log"
LOG_FILE="pipeline_log_$(date +%Y%m%d_%H%M%S).log"

echo "[🚀] Starting 3-hour diagnostic pipeline run..."
START_TIME=$(date +%s)
END_TIME=$((START_TIME + 10800))  # 3 hours

touch "$BLOCK_LOG"

while [ "$(date +%s)" -lt "$END_TIME" ]; do
  echo "[⏳] Running training and submission cycle..."
  
  # Run training and submission
  python train.py >> "$LOG_FILE" 2>&1
  python submit_prediction.py >> "$LOG_FILE" 2>&1

  echo "[🔍] Extracting latest nonce from log..."
  LAST_NONCE=$(grep 'block_height=' "$LOG_FILE" | tail -1 | sed -E 's/.*block_height=([0-9]+).*/\1/')

  if [[ -z "$LAST_NONCE" ]]; then
    echo "[⚠️] Could not determine nonce. Skipping chain check." | tee -a "$LOG_FILE"
  else
    echo "[🔎] Checking chain state for nonce=$LAST_NONCE..."
    
    # Query chain
    allorad q emissions worker-nonce-unfulfilled "$TOPIC_ID" "$LAST_NONCE" > temp_chain_check.txt 2>&1
    
    if grep -q "true" temp_chain_check.txt; then
      echo "[❌] Nonce $LAST_NONCE is still unfulfilled!" | tee -a "$LOG_FILE"
    else
      echo "[✅] Nonce $LAST_NONCE is fulfilled." | tee -a "$LOG_FILE"
    fi
    
    echo "$LAST_NONCE" >> "$BLOCK_LOG"
  fi

  echo "[🛌] Sleeping for 5 minutes before next run..."
  sleep 300
done

echo "[🎯] Diagnostic complete. Log saved to $LOG_FILE"

