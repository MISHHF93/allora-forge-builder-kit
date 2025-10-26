#!/usr/bin/env bash
set -euo pipefail

# Headless submission script for cron/systemd on Linux
# - Expects .allora_key in the running user's home directory with restrictive perms
# - Expects .env in repo root with ALLORA_API_KEY and TIINGO_API_KEY
# - Submits using the saved model and live features (no training)

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Minimal env; python-dotenv will load .env for API keys
export ALLORA_CHAIN_ID="${ALLORA_CHAIN_ID:-allora-testnet-1}"
export ALLORA_RPC_URL="${ALLORA_RPC_URL:-https://allora-rpc.testnet.allora.network}"

# Prefer python3 if available
PY="${PYTHON:-python3}"

mkdir -p "$REPO_DIR/data"
LOG_TS="$(date -Iseconds)"
echo "[$LOG_TS] cron_submit: starting submit (chain=$ALLORA_CHAIN_ID rpc=$ALLORA_RPC_URL)" >> "$REPO_DIR/data/cron_submit.log"

set +e
"$PY" -u submit_prediction.py --mode sdk --topic-id 67 --timeout 240 --source model >> "$REPO_DIR/data/cron_submit.log" 2>&1
EC=$?
set -e

LOG_TS2="$(date -Iseconds)"
echo "[$LOG_TS2] cron_submit: exit code $EC" >> "$REPO_DIR/data/cron_submit.log"
exit $EC
