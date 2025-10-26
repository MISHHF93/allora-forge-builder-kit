#!/usr/bin/env bash
set -euo pipefail

TS() { date -Is; }
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[$(TS)] [INFO] Resolving wallet via scripts/resolve_wallet.py"
if ! RESOLVED=$(python3 -u ./scripts/resolve_wallet.py 2>&1 | awk 'NF{line=$0} END{print line}'); then
  echo "[$(TS)] [ERROR] Wallet resolver failed" >&2
  exit 2
fi
if [[ -z "$RESOLVED" || "$RESOLVED" != allo* ]]; then
  echo "[$(TS)] [ERROR] Resolver returned unexpected output: '$RESOLVED'" >&2
  exit 2
fi
export ALLORA_WALLET_ADDR="$RESOLVED"
echo "[$(TS)] [INFO] Using wallet: $ALLORA_WALLET_ADDR"

echo "[$(TS)] [INFO] Training start: python3 -u train.py"
if ! TRAIN_OUT=$(python3 -u ./train.py 2>&1); then
  CODE=$?
  echo "[$(TS)] [ERROR] Training failed with exit code $CODE" >&2
  echo "[$(TS)] [ERROR] Training output: $TRAIN_OUT" >&2
  exit $CODE
fi
echo "[$(TS)] [INFO] Training complete"

echo "[$(TS)] [INFO] Submission start: python3 -u submit_prediction.py --mode sdk --topic-id 67 --timeout 120"
if ! SUBMIT_OUT=$(python3 -u ./submit_prediction.py --mode sdk --topic-id 67 --timeout 120 2>&1); then
  CODE=$?
  echo "[$(TS)] [ERROR] Submission failed with exit code $CODE" >&2
  echo "[$(TS)] [ERROR] Submission output: $SUBMIT_OUT" >&2
  exit $CODE
fi
echo "[$(TS)] [INFO] Submission complete"
echo "[$(TS)] [INFO] Done"
exit 0
