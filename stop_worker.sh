#!/bin/bash
#
# Stop the Allora Worker
#

cd "$(dirname "$0")"

echo "Stopping Allora Worker..."

if pgrep -f "python.*run_worker.py" > /dev/null; then
    pkill -SIGTERM -f "python.*run_worker.py"
    echo "✅ Shutdown signal sent to worker"
    echo "⏳ Waiting for graceful shutdown..."
    sleep 3
    
    if pgrep -f "python.*run_worker.py" > /dev/null; then
        echo "⚠️  Worker still running, forcing shutdown..."
        pkill -SIGKILL -f "python.*run_worker.py"
        echo "✅ Worker forcefully stopped"
    else
        echo "✅ Worker stopped gracefully"
    fi
else
    echo "ℹ️  No worker process found"
fi
