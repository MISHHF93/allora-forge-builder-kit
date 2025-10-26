#!/usr/bin/env bash
set -euo pipefail

TS() { date -Is; }
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Defaults
VENV_DIR="venv"
PYTHON_BIN="python3"
REQUIREMENTS_FILE="requirements.txt"

usage() {
  cat <<EOF
$(TS) Setup EC2/Ubuntu instance for Allora Forge Builder Kit

Usage: $0 [--venv venv] [--python python3]

Steps:
  1) apt-get update; install libs: libgomp1 libgl1-mesa-glx python3-venv python3-pip git
  2) create virtualenv in ./${VENV_DIR}
  3) pip install -U pip wheel setuptools
  4) pip install -r requirements.txt (graceful if LightGBM unavailable)
  5) echo guidance if LightGBM missing
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv) VENV_DIR="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[$(TS)] [ERROR] Unknown arg: $1" >&2; exit 64 ;;
  esac
done

if ! command -v apt-get >/dev/null 2>&1; then
  echo "[$(TS)] [WARN] apt-get not found. This script targets Ubuntu/Debian. Proceeding anyway..." >&2
fi

# 1) System packages
if command -v apt-get >/dev/null 2>&1; then
  echo "[$(TS)] [INFO] Installing system packages..."
  sudo apt-get update -y
  sudo apt-get install -y --no-install-recommends \
    libgomp1 libgl1-mesa-glx \
    python3-venv python3-pip git ca-certificates
fi

# 2) Virtual environment
VENV_ACTIVATE="$ROOT_DIR/${VENV_DIR}/bin/activate"
if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "[$(TS)] [INFO] Creating venv at ${VENV_DIR}"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1090
source "$VENV_ACTIVATE"
echo "[$(TS)] [INFO] Using $(python --version) in venv $(dirname "$VENV_ACTIVATE")"

# 3) Base pip tooling
python -m pip install -U pip setuptools wheel

# 4) Requirements (graceful on LightGBM)
set +e
python -m pip install -r "$REQUIREMENTS_FILE"
RC=$?
set -e
if [[ $RC -ne 0 ]]; then
  echo "[$(TS)] [WARN] pip install -r ${REQUIREMENTS_FILE} returned ${RC}. Will continue; train.py can fall back to scikit-learn RandomForest."
fi

# LightGBM check
cat <<'EON'
Note:
- LightGBM requires libgomp (installed above). If import still fails, ensure libgomp1 is present:
    sudo apt-get update && sudo apt-get install -y libgomp1
- Fallback is enabled: train.py will use scikit-learn RandomForestRegressor when LightGBM is unavailable.
EON

echo "[$(TS)] [OK] Setup complete"
