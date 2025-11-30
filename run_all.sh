#!/bin/bash

set -euo pipefail

echo "▶️ Activating virtual environment..."
source .venv/bin/activate

if [ -f ".env" ]; then
  echo "📦 Loading environment variables from .env"
  set -a
  source .env
  set +a
fi

echo "🧠 Training model..."
python3 train.py

echo "📈 Submitting prediction..."
python3 submit_prediction.py
