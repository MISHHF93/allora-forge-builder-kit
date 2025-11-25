#!/bin/bash
set -euo pipefail

# === CONFIG ===
WORKER_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
TOPIC_ID="67"
RPC="https://allora-testnet-rpc.polkachu.com"
PYTHON_SCRIPT="submit_prediction.py"
LOG_TAG="[MODEL-DIAGNOSE]"

echo "$LOG_TAG 🔍 Starting full model logic diagnostics..."
echo "$LOG_TAG 🧠 Topic: $TOPIC_ID | Worker: $WORKER_ADDR"
echo "$LOG_TAG 🌐 RPC: $RPC"

# === 1. Check for duplicate processes ===
echo "$LOG_TAG 🚨 Checking for duplicate submission scripts..."
PIDS=$(pgrep -f "$PYTHON_SCRIPT" || true)
if [ -n "$PIDS" ]; then
  echo "$LOG_TAG ⚠️ Active instances of $PYTHON_SCRIPT:"
  echo "$PIDS"
else
  echo "$LOG_TAG ✅ No active submission scripts found."
fi

# === 2. Check submission window ===
echo "$LOG_TAG 🪟 Checking submission window status..."
status=$(allorad query emissions worker-submission-window-status "$TOPIC_ID" "$WORKER_ADDR" --node "$RPC" 2>/dev/null || true)

if [[ "$status" == *"is_open: true"* ]]; then
  echo "$LOG_TAG ✅ Submission window is OPEN"
else
  echo "$LOG_TAG ❌ Submission window is CLOSED or unavailable"
  echo "$status"
fi

# === 3. Check worker registration & whitelist ===
echo "$LOG_TAG 👤 Checking worker registration and whitelist..."
worker_status=$(echo "$status" | grep -E "is_registered|is_whitelisted")

if [[ "$worker_status" == *"is_registered: true"* ]] && [[ "$worker_status" == *"is_whitelisted: true"* ]]; then
  echo "$LOG_TAG ✅ Worker is registered and whitelisted."
else
  echo "$LOG_TAG ❌ Worker not registered or not whitelisted."
  echo "$worker_status"
fi

# === 4. Model Readiness ===
echo "$LOG_TAG 🧪 Testing model prediction logic..."
if .venv/bin/python submit_prediction.py --dry-run > /tmp/model_test.log 2>&1; then
  echo "$LOG_TAG ✅ Model is callable and dry-run completed successfully."
else
  echo "$LOG_TAG ❌ Model dry-run failed. Check /tmp/model_test.log for details."
fi

echo "$LOG_TAG ✅ Diagnostics complete."
