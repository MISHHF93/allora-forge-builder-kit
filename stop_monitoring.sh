#!/bin/bash
# Stop continuous monitoring

REPO_ROOT="/workspaces/allora-forge-builder-kit"
LOG_DIR="$REPO_ROOT/data/artifacts/logs"
PID_FILE="$LOG_DIR/continuous_monitor.pid"

echo "Stopping continuous monitoring..."

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping continuous monitor (PID: $PID)"
        kill "$PID" 2>/dev/null || true
        sleep 2
        if kill -0 "$PID" 2>/dev/null; then
            echo "Force killing..."
            kill -9 "$PID" 2>/dev/null || true
        fi
    else
        echo "Process $PID not running"
    fi
    rm -f "$PID_FILE"
    echo "✅ Continuous monitoring stopped"
else
    echo "No PID file found - monitoring may not be running"
fi