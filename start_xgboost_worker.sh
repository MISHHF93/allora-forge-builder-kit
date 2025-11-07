#!/bin/bash
# Single XGBoost Worker Startup Script
# Ensures only ONE worker runs for wallet: allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma

set -e

echo "================================================"
echo "Starting SINGLE XGBoost Worker for Topic 67"
echo "================================================"
echo ""

# Kill any existing workers/pipelines
echo "🛑 Stopping any existing workers..."
pkill -9 -f "python.*run_worker" 2>/dev/null || true
pkill -9 -f "python.*run_pipeline" 2>/dev/null || true
pkill -9 -f "python.*train.py" 2>/dev/null || true
sleep 2

# Verify nothing is running
RUNNING=$(ps aux | grep -E "python.*(run_worker|run_pipeline|train\.py)" | grep -v grep | wc -l)
if [ "$RUNNING" -gt 0 ]; then
    echo "❌ ERROR: Could not stop existing processes"
    ps aux | grep -E "python.*(run_worker|run_pipeline|train\.py)" | grep -v grep
    exit 1
fi

echo "✅ All existing processes stopped"
echo ""

# Verify environment
if [ ! -f ".env" ]; then
    echo "❌ ERROR: .env file not found"
    exit 1
fi

WALLET=$(grep "ALLORA_WALLET_ADDR" .env | cut -d'=' -f2)
if [ "$WALLET" != "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma" ]; then
    echo "❌ ERROR: Wallet mismatch in .env"
    echo "   Expected: allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
    echo "   Found: $WALLET"
    exit 1
fi

echo "✅ Environment verified"
echo "   Wallet: $WALLET"
echo "   Model: XGBoost"
echo "   Topic: 67 (BTC/USD 7-day log-return)"
echo ""

# Start the worker
echo "🚀 Starting XGBoost worker..."
nohup python3 -u run_worker.py > data/artifacts/logs/xgboost_worker.log 2>&1 &
WORKER_PID=$!

sleep 5

# Verify it's running
if ps -p $WORKER_PID > /dev/null; then
    echo "✅ XGBoost worker started successfully"
    echo "   PID: $WORKER_PID"
    echo ""
    echo "================================================"
    echo "📋 Management Commands:"
    echo "   View logs:  tail -f data/artifacts/logs/xgboost_worker.log"
    echo "   Check status: ps aux | grep $WORKER_PID"
    echo "   Stop worker: kill $WORKER_PID"
    echo "================================================"
    echo ""
    echo "Worker is running with XGBoost model for wallet:"
    echo "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
else
    echo "❌ ERROR: Worker failed to start"
    echo "Check logs: tail -50 data/artifacts/logs/xgboost_worker.log"
    exit 1
fi
