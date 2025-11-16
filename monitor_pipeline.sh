#!/bin/bash
# Pipeline monitoring script

echo "=== ALLORA PIPELINE MONITOR ==="
echo "Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# Check process status
PID=$(ps aux | grep "python3 train.py --loop" | grep -v grep | awk '{print $2}')
if [ -n "$PID" ]; then
    echo "✅ Pipeline Status: RUNNING"
    echo "   PID: $PID"
    CPU=$(ps aux | grep "$PID" | grep -v grep | awk '{print $3}')
    MEM=$(ps aux | grep "$PID" | grep -v grep | awk '{print $4}')
    echo "   CPU: ${CPU}%"
    echo "   Memory: ${MEM}%"
else
    echo "❌ Pipeline Status: NOT RUNNING"
fi

echo ""
echo "=== Recent Activity ==="
tail -15 pipeline_run.log | grep -E "INFO|WARNING|ERROR" | tail -10

echo ""
echo "=== Submission History ==="
tail -3 submission_log.csv

echo ""
echo "=== Next Scheduled Run ==="
NEXT_RUN=$(tail -5 pipeline_run.log | grep "sleeping.*until" | tail -1 | grep -oP "\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
if [ -n "$NEXT_RUN" ]; then
    echo "   Scheduled for: $NEXT_RUN"
else
    echo "   Checking..."
fi

echo ""
echo "=== Wallet Balance ==="
BALANCE=$(tail -20 pipeline_run.log | grep "balance:" | tail -1 | grep -oP "\d+\.\d+" || echo "unknown")
echo "   $BALANCE ALLO"

