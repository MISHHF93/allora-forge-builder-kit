#!/bin/bash
# Start continuous monitoring with auto-restart capability

REPO_ROOT="/workspaces/allora-forge-builder-kit"
LOG_DIR="$REPO_ROOT/data/artifacts/logs"
PID_FILE="$LOG_DIR/continuous_monitor.pid"

echo "Starting continuous monitoring for Allora competition..."

# Kill any existing instances
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing continuous monitor (PID: $OLD_PID)"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

# Start the monitoring script
cd "$REPO_ROOT"
nohup ./continuous_monitor.sh > /dev/null 2>&1 &

# Give it a moment to start
sleep 2

# Check if it's running
if [ -f "$PID_FILE" ]; then
    NEW_PID=$(cat "$PID_FILE")
    if kill -0 "$NEW_PID" 2>/dev/null; then
        echo "✅ Continuous monitoring started successfully (PID: $NEW_PID)"
        exit 0
    fi
fi

echo "❌ Failed to start continuous monitoring"
exit 1