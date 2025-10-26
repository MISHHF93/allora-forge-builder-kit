#!/usr/bin/env bash
set -euo pipefail

# Headless training script for cron/systemd on Linux

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

PY="${PYTHON:-python3}"

mkdir -p "$REPO_DIR/data"
LOG_TS="$(date -Iseconds)"
echo "[$LOG_TS] cron_train: starting" >> "$REPO_DIR/data/cron_train.log"

set +e
"$PY" -u train.py >> "$REPO_DIR/data/cron_train.log" 2>&1
EC=$?
set -e

LOG_TS2="$(date -Iseconds)"
echo "[$LOG_TS2] cron_train: exit code $EC" >> "$REPO_DIR/data/cron_train.log"
exit $EC
