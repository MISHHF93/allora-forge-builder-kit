#!/bin/bash

END_DATE_UTC="2025-12-15T13:00:00Z"
LOG_FILE="logs/submission.log"

echo "[CHECK] Current UTC time:"
current_time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "        $current_time"

echo "[CHECK] Target end time (UTC):"
echo "        $END_DATE_UTC"

if [[ "$current_time" > "$END_DATE_UTC" ]]; then
    echo "❌ ERROR: We are past the deadline."
    exit 1
else
    echo "✅ Instance time is within range."
fi

echo "[CHECK] Uptime:"
uptime -p

echo "[CHECK] Checking for 'submit_prediction.py' process..."
pid=$(pgrep -f submit_prediction.py)
if [ -n "$pid" ]; then
    echo "✅ Pipeline is running (PID: $pid)"
else
    echo "❌ Pipeline is NOT running!"
    echo "   Checking log for shutdown messages..."
    if [ -f "$LOG_FILE" ]; then
        if grep -q "DAEMON SHUTDOWN COMPLETE" "$LOG_FILE"; then
            echo "⚠️  Found shutdown message in logs:"
            grep "DAEMON SHUTDOWN COMPLETE" "$LOG_FILE" | tail -n 1
        else
            echo "✅ No shutdown messages found."
        fi
    else
        echo "❌ Log file not found!"
    fi
    exit 2
fi

echo "[CHECK] Log activity in last 10 lines:"
tail -n 10 "$LOG_FILE"

echo "[CHECK COMPLETE] System and pipeline are healthy (for now)."
