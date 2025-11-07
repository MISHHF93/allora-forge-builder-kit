#!/bin/bash
#
# Production Worker Startup Script for Allora Topic 67
# 
# This script starts the continuous worker in production mode.
# The worker will run indefinitely, responding to network submission windows.
#
# Usage:
#   ./start_worker.sh          # Start with default settings
#   ./start_worker.sh --debug  # Start with debug logging
#

set -e

cd "$(dirname "$0")"

echo "================================================"
echo "Allora Topic 67 - Production Worker Startup"
echo "================================================"
echo ""

# Check for existing worker
if pgrep -f "python.*run_worker.py" > /dev/null; then
    echo "❌ Worker is already running!"
    echo ""
    echo "Running worker processes:"
    ps aux | grep -E "python.*run_worker.py" | grep -v grep
    echo ""
    echo "To stop the worker, run: pkill -f 'python.*run_worker.py'"
    exit 1
fi

# Check environment
if [ ! -f .env ]; then
    echo "❌ No .env file found!"
    echo "Please create a .env file with MNEMONIC and TIINGO_API_KEY"
    exit 1
fi

# Check dependencies
if ! python3 -c "import allora_sdk" 2>/dev/null; then
    echo "❌ allora_sdk not installed!"
    echo "Please run: pip install -r requirements.txt"
    exit 1
fi

echo "✅ Environment checks passed"
echo ""

# Determine run mode
DEBUG_FLAG=""
if [ "$1" = "--debug" ]; then
    DEBUG_FLAG="--debug"
    echo "🔍 Starting in DEBUG mode"
else
    echo "🚀 Starting in PRODUCTION mode"
fi

echo "📅 Competition: Sep 16, 2025 - Dec 15, 2025"
echo "🎯 Topic: 67 (BTC/USD 7-day log-return)"
echo "⏰ Polling interval: 120 seconds"
echo ""
echo "================================================"
echo ""

# Start worker in background
nohup python3 run_worker.py $DEBUG_FLAG > data/artifacts/logs/worker_output.log 2>&1 &
WORKER_PID=$!

echo "✅ Worker started with PID: $WORKER_PID"
echo ""
echo "📋 Monitoring commands:"
echo "   View logs:  tail -f data/artifacts/logs/worker_output.log"
echo "   View events: tail -f data/artifacts/logs/worker_continuous.log"
echo "   Check status: ps aux | grep $WORKER_PID"
echo "   Stop worker: kill $WORKER_PID"
echo ""
echo "Worker is now running in the background..."
echo "Logs will be written to data/artifacts/logs/worker_output.log"
echo ""
