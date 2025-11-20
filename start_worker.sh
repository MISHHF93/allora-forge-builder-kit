#!/bin/bash
#
# Start Worker Script - Topic 67 Hourly Submission Pipeline
# Cleans old processes, verifies configuration, and starts fresh worker
#

set -e

echo "════════════════════════════════════════════════════════════════════════════"
echo "STARTING WORKER - Topic 67 (7-Day BTC/USD Log-Return Prediction)"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# 1. Kill any existing workers
echo "1. Cleaning old processes..."
pkill -f "python.*train\.py" 2>/dev/null || true
sleep 2

# Verify all old PIDs are gone
OLD_PIDS="38269 65018 78831 93220 176450 185034"
for pid in $OLD_PIDS; do
    if ps -p $pid > /dev/null 2>&1; then
        echo "   ⚠️  Killing stale PID $pid"
        kill -9 $pid 2>/dev/null || true
    fi
done

# Confirm no train.py processes remain
REMAINING=$(pgrep -f "python.*train\.py" | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "   ⚠️  $REMAINING worker(s) still running, force killing..."
    pkill -9 -f "python.*train\.py" 2>/dev/null || true
    sleep 2
fi

echo "   ✅ All old processes cleaned"
echo ""

# 2. Verify configuration
echo "2. Verifying configuration..."

if [ ! -f "config/pipeline.yaml" ]; then
    echo "   ❌ config/pipeline.yaml not found!"
    exit 1
fi

if [ ! -f ".allora_key" ]; then
    echo "   ⚠️  .allora_key not found - submissions may fail"
fi

if [ -z "$ALLORA_API_KEY" ]; then
    echo "   ⚠️  ALLORA_API_KEY not set - data fetching may fail"
fi

echo "   ✅ Configuration verified"
echo ""

# 3. Check bug fix
echo "3. Verifying bug fix..."
if grep -q "CRITICAL FIX: epoch_len is in SECONDS" train.py; then
    echo "   ✅ Bug fix present (epoch_len seconds→blocks conversion)"
else
    echo "   ❌ Bug fix NOT found in train.py!"
    exit 1
fi
echo ""

# 4. Start worker
echo "4. Starting worker..."
echo "   Command: python train.py --loop --schedule-mode loop --submit"
echo "   Log: pipeline_run.log"
echo ""

nohup python train.py --loop --schedule-mode loop --submit > /dev/null 2>&1 &
sleep 3

# Get new PID
NEW_PID=$(pgrep -f "python.*train\.py.*--loop.*--submit" || echo "")

if [ -z "$NEW_PID" ]; then
    echo "   ❌ Worker failed to start!"
    tail -20 pipeline_run.log
    exit 1
fi

echo $NEW_PID > pipeline.pid
echo "   ✅ Worker started successfully"
echo "   PID: $NEW_PID"
echo ""

# 5. Verify worker is running
sleep 2
if ps -p $NEW_PID > /dev/null 2>&1; then
    echo "5. Worker status: ✅ RUNNING"
else
    echo "5. Worker status: ❌ DIED IMMEDIATELY"
    tail -20 pipeline_run.log
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "WORKER STARTED SUCCESSFULLY"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "📊 Status:"
echo "   PID: $NEW_PID"
echo "   Mode: Loop with hourly submission"
echo "   Schedule: Every hour at HH:00 UTC"
echo "   Submission: Enabled (--submit)"
echo "   Bug Fix: Applied (blocks calculation)"
echo ""
echo "📁 Files:"
echo "   Process ID: pipeline.pid"
echo "   Main Log: pipeline_run.log"
echo "   Submissions: submission_log.csv"
echo ""
echo "💡 Monitoring:"
echo "   Live: ./watch_live.sh"
echo "   Snapshot: ./monitor.sh"
echo "   Logs: tail -f pipeline_run.log"
echo ""
echo "⏰ Next submission: Top of next hour when window opens"
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
