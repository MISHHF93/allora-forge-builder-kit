#!/bin/bash
# Quick status monitor for train.py loop

echo "═══════════════════════════════════════════════════════════════════"
echo "  ALLORA FORGE BUILDER KIT - STATUS MONITOR"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Process status
PID=$(ps aux | grep "python3 train.py --loop" | grep -v grep | awk '{print $2}')
if [ -z "$PID" ]; then
    echo "❌ Process: NOT RUNNING"
    echo ""
    echo "To start: python3 train.py --loop --submit"
    exit 1
else
    CPU=$(ps aux | grep "$PID" | grep -v grep | awk '{print $3}')
    MEM=$(ps aux | grep "$PID" | grep -v grep | awk '{print $4}')
    echo "✅ Process: RUNNING (PID: $PID)"
    echo "   CPU: ${CPU}% | Memory: ${MEM}%"
fi

echo ""

# Timing
CURRENT=$(date -u +"%Y-%m-%d %H:%M:%S UTC")
NEXT_CYCLE=$(grep "sleeping.*until" pipeline_run.log 2>/dev/null | tail -1 | grep -oP '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z' || echo "calculating...")
echo "⏰ Current time: $CURRENT"
echo "   Next cycle: $NEXT_CYCLE"

echo ""

# Recent activity
LAST_ITERATION=$(grep "\[loop\] iteration=" pipeline_run.log 2>/dev/null | tail -1 | sed 's/.*\[loop\]/[loop]/')
if [ ! -z "$LAST_ITERATION" ]; then
    echo "🔄 Last iteration: $LAST_ITERATION"
fi

echo ""

# Submission status
echo "📊 Recent submissions (last 3):"
tail -3 submission_log.csv 2>/dev/null | while IFS=',' read -r timestamp topic value wallet nonce hash success code status rest; do
    if [ "$timestamp" != "timestamp_utc" ]; then
        if [ "$success" = "true" ]; then
            echo "   ✅ $timestamp: SUCCESS (nonce $nonce)"
        else
            echo "   ❌ $timestamp: $status"
        fi
    fi
done

echo ""

# Error check
ERROR_COUNT=$(grep -i "error\|failed\|exception" pipeline_run.log 2>/dev/null | tail -20 | wc -l)
if [ "$ERROR_COUNT" -gt 0 ]; then
    echo "⚠️  Recent errors/warnings: $ERROR_COUNT"
    echo "   View with: grep -i 'error\|failed' pipeline_run.log | tail -20"
else
    echo "✅ No recent errors detected"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "Commands:"
echo "  tail -f pipeline_run.log     # Watch live logs"
echo "  ./monitor_status.sh           # Run this status check"
echo "  tail -5 submission_log.csv    # View recent submissions"
echo "═══════════════════════════════════════════════════════════════════"
