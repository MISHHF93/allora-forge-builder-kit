#!/usr/bin/env bash
set -euo pipefail

TS() { date -Is; }
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_DIR="venv"
PYTHON_BIN="python3"
LOG_DIR="$ROOT_DIR/data/artifacts/logs"
MODE="loop" # loop | once
SUBMIT_TIMEOUT="180"
SUBMIT_RETRIES="3"

usage() {
  cat <<EOF
$(TS) Allora Forge Builder Kit runner

Usage: $0 [--once] [--venv venv] [--timeout 180] [--retries 3]

- Validates base deps (libgomp for LightGBM). If unavailable, training will fall back to RandomForestRegressor.
- In loop mode, aligns to top-of-hour UTC windows before running train+submit.
- Logs to data/artifacts/logs/run_allora-<timestamp>.log
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --once) MODE="once"; shift ;;
    --venv) VENV_DIR="$2"; shift 2 ;;
    --timeout) SUBMIT_TIMEOUT="$2"; shift 2 ;;
    --retries) SUBMIT_RETRIES="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[$(TS)] [ERROR] Unknown arg: $1" >&2; exit 64 ;;
  esac
done

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_allora-$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(TS)] [INFO] Starting runner in $MODE mode from $ROOT_DIR"

# Activate venv if present
if [[ -f "$ROOT_DIR/$VENV_DIR/bin/activate" ]]; then
  # shellcheck disable=SC1090
  source "$ROOT_DIR/$VENV_DIR/bin/activate"
  echo "[$(TS)] [INFO] Using $(python --version) from venv: $VENV_DIR"
else
  echo "[$(TS)] [WARN] venv not found at $VENV_DIR. Using system $PYTHON_BIN"
fi

# Check libgomp availability (optional)
if command -v ldconfig >/dev/null 2>&1; then
  if ! ldconfig -p | grep -q "libgomp.so.1"; then
    echo "[$(TS)] [WARN] libgomp.so.1 not found via ldconfig. If LightGBM import fails, training will fall back automatically."
  else
    echo "[$(TS)] [INFO] libgomp.so.1 present"
  fi
else
  echo "[$(TS)] [INFO] ldconfig not available; skipping libgomp check"
fi

run_once() {
  echo "[$(TS)] [INFO] Running train.py --submit (timeout=$SUBMIT_TIMEOUT retries=$SUBMIT_RETRIES)"
  set +e
  python "$ROOT_DIR/train.py" --submit --submit-timeout "$SUBMIT_TIMEOUT" --submit-retries "$SUBMIT_RETRIES"
  RC=$?
  set -e
  if [[ $RC -ne 0 ]]; then
    echo "[$(TS)] [ERROR] train.py exited with code $RC (continuing)"
  else
    echo "[$(TS)] [OK] train.py finished"
  fi
}

sleep_until_top_of_hour_utc() {
  # Compute seconds until next top-of-hour in UTC
  now_utc=$(date -u +%s)
  minute=$(date -u +%M)
  second=$(date -u +%S)
  let sec_past=$minute*60+$second
  let sec_to_sleep=3600-sec_past
  if [[ $sec_to_sleep -gt 0 && $sec_to_sleep -lt 3600 ]]; then
    echo "[$(TS)] [INFO] Sleeping ${sec_to_sleep}s until next UTC top-of-hour"
    sleep "$sec_to_sleep"
  fi
}

if [[ "$MODE" == "once" ]]; then
  run_once
  echo "[$(TS)] [DONE] once mode complete"
  exit 0
fi

# Loop mode
while true; do
  sleep_until_top_of_hour_utc
  run_once
  # Minimal cooldown to avoid tight loops in case of very fast run
  sleep 5
 done
