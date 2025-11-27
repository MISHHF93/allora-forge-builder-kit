#!/bin/bash

# ---------------------------------------------
# Allora Forge Enhanced Diagnostic Pipeline Runner
# ---------------------------------------------
# - Runs train + submit prediction in a loop for 3 hours
# - Captures logs, highlights common failures
# - Checks if nonce is fulfilled
# - Verifies worker registration, activity, and pending tasks
# ---------------------------------------------

set -euo pipefail

TOPIC_ID="67"
WORKER_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
else
  echo "[❌] Virtual environment not found at .venv/. Please set it up first."
  exit 1
fi

PYTHON_EXEC=".venv/bin/python"

# Start time
start_time=$(date +%s)
end_time=$((start_time + 10800))  # 3 hours

# Timestamped log file
log_file="diagnostics/$(date '+%Y-%m-%d_%H-%M-%S')_pipeline.log"
mkdir -p diagnostics

echo "[🚀] Starting 3-hour diagnostic run..."
echo "[📝] Logging to $log_file"
echo "-----------------------------------" | tee -a "$log_file"

run_once() {
  echo "-----------------------------------" | tee -a "$log_file"
  echo "[⏱] Diagnostic iteration started: $(date)" | tee -a "$log_file"

  echo "[📚] Running train.py..." | tee -a "$log_file"
  $PYTHON_EXEC train.py >> "$log_file" 2>&1 && echo "[✅] train.py succeeded." | tee -a "$log_file" || echo "[❌] train.py failed!" | tee -a "$log_file"

  echo "[📤] Running submit_prediction.py..." | tee -a "$log_file"
  $PYTHON_EXEC submit_prediction.py >> "$log_file" 2>&1 && echo "[✅] submit_prediction.py succeeded." | tee -a "$log_file" || echo "[❌] submit_prediction.py failed!" | tee -a "$log_file"

  # Pull last known block height submitted
  last_nonce=$(grep -oP 'block_height=\K[0-9]+' "$log_file" | tail -1)
  if [[ -n "$last_nonce" ]]; then
    echo "[🔎] Checking if nonce $last_nonce is fulfilled..." | tee -a "$log_file"
    chain_response=$(allorad q emissions worker-nonce-unfulfilled "$TOPIC_ID" "$last_nonce" 2>&1)

    if echo "$chain_response" | grep -q "true"; then
      echo "[⚠️] Nonce $last_nonce is UNFULFILLED!" | tee -a "$log_file"
    elif echo "$chain_response" | grep -q "false"; then
      echo "[✅] Nonce $last_nonce is fulfilled." | tee -a "$log_file"
    else
      echo "[❓] Unknown response: $chain_response" | tee -a "$log_file"
    fi
  else
    echo "[⚠️] No block height found for nonce check." | tee -a "$log_file"
  fi

  # 🔍 Worker diagnostics
  echo "[🔧] Worker diagnostics for $WORKER_ADDR on topic $TOPIC_ID" | tee -a "$log_file"

  echo "[🔹] Checking worker registration..." | tee -a "$log_file"
  allorad q emissions is-worker-registered "$TOPIC_ID" "$WORKER_ADDR" 2>&1 | tee -a "$log_file"

  echo "[🔹] Checking last worker commit..." | tee -a "$log_file"
  allorad q emissions topic-last-worker-commit "$TOPIC_ID" 2>&1 | tee -a "$log_file"

  echo "[🔹] Checking unfulfilled worker nonces..." | tee -a "$log_file"
  allorad q emissions unfulfilled-worker-nonces "$TOPIC_ID" 2>&1 | tee -a "$log_file"

  echo "[🔹] Checking latest inference for this worker..." | tee -a "$log_file"
  allorad q emissions worker-latest-inference "$TOPIC_ID" "$WORKER_ADDR" 2>&1 | tee -a "$log_file"

  echo "[✅] Diagnostic iteration complete: $(date)" | tee -a "$log_file"
}

# Run the diagnostic loop
while [ "$(date +%s)" -lt "$end_time" ]; do
  run_once
  sleep 10
done

# Summary
echo "[🔍] Analyzing logs for issues..."
echo "------ ERRORS FOUND ------" >> "$log_file"
grep -iE "error|failed|429|traceback|exception" "$log_file" | sort | uniq >> "$log_file"

echo "[🎯] Diagnostic complete. Log saved to: $log_file"

