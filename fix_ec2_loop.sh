#!/bin/bash
# EC2 Fix Script - Restart loop with --force-submit to bypass lifecycle checks

echo "🔧 Fixing Allora Forge Worker on EC2"
echo "======================================"
echo ""

# Step 1: Check current process
echo "[1/4] Checking current process..."
if [ -f train.pid ]; then
    PID=$(cat train.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "  ✓ Found running process (PID: $PID)"
        echo "  Stopping current loop..."
        kill $PID
        sleep 2
        
        # Force kill if still running
        if ps -p $PID > /dev/null 2>&1; then
            echo "  Force killing..."
            kill -9 $PID
        fi
        echo "  ✓ Process stopped"
    else
        echo "  ℹ No running process found"
    fi
else
    echo "  ℹ No PID file found"
    # Try to find and kill any running train.py
    pkill -f "python3 train.py --loop"
    sleep 2
fi

# Step 2: Check lifecycle diagnostics from recent logs
echo ""
echo "[2/4] Analyzing recent lifecycle diagnostics..."
if [ -f pipeline_run.log ]; then
    echo "  Last lifecycle check:"
    grep -A 12 "Lifecycle diagnostics" pipeline_run.log | tail -13 | sed 's/^/    /'
    echo ""
    echo "  Recent skip reasons:"
    grep "Submission skipped" pipeline_run.log | tail -3 | sed 's/^/    /'
else
    echo "  ⚠ pipeline_run.log not found"
fi

# Step 3: Start with --force-submit
echo ""
echo "[3/4] Starting loop with --force-submit flag..."
echo "  Command: python3 train.py --loop --submit --force-submit --submit-timeout 300"
echo ""

nohup python3 train.py --loop --submit --force-submit --submit-timeout 300 > pipeline.log 2>&1 &
NEW_PID=$!
echo $NEW_PID > train.pid

echo "  ✓ Process started (PID: $NEW_PID)"
echo "  ✓ PID saved to train.pid"

# Step 4: Verify and monitor
echo ""
echo "[4/4] Verification..."
sleep 2

if ps -p $NEW_PID > /dev/null 2>&1; then
    echo "  ✅ Process is running successfully!"
else
    echo "  ❌ Process failed to start"
    exit 1
fi

echo ""
echo "======================================"
echo "✅ Fix applied successfully!"
echo ""
echo "📊 Monitoring commands:"
echo "  tail -f pipeline_run.log              # Watch live logs"
echo "  python3 train.py --inspect-log        # Check submissions"
echo "  python3 train.py --refresh-scores     # Update scores (after 24h)"
echo ""
echo "🛑 To stop:"
echo "  kill \$(cat train.pid)"
echo ""
echo "💡 What changed:"
echo "  - Added --force-submit flag"
echo "  - Bypasses lifecycle/reputer/stake checks"
echo "  - Submits predictions even if REST API fails"
echo "  - Uses SDK direct submission"
echo ""
echo "⏳ Waiting 10 seconds to check for errors..."
sleep 10

if ps -p $NEW_PID > /dev/null 2>&1; then
    echo "  ✅ Still running - no immediate errors"
    echo ""
    echo "📝 Recent log output:"
    tail -20 pipeline_run.log | sed 's/^/  /'
else
    echo "  ❌ Process crashed - check pipeline.log for errors"
    cat pipeline.log
    exit 1
fi

echo ""
echo "🎉 All done! Loop is running with force-submit enabled."
echo "   Next submission will occur at the next hourly epoch."
