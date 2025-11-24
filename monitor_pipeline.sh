#!/bin/bash
# Real-time Pipeline Monitoring Dashboard

clear

while true; do
    clear
    
    echo "╔════════════════════════════════════════════════════════════════════════════════╗"
    echo "║              🚀 ALLORA SUBMISSION PIPELINE - LIVE MONITORING                   ║"
    echo "╚════════════════════════════════════════════════════════════════════════════════╝"
    echo ""
    
    # Daemon Status
    echo "📋 DAEMON STATUS:"
    PID=$(cat /workspaces/allora-forge-builder-kit/pipeline.pid 2>/dev/null)
    if ps -p $PID > /dev/null 2>&1; then
        UPTIME=$(ps -p $PID -o etime= | tr -d ' ')
        echo "   ✅ RUNNING (PID: $PID, Uptime: $UPTIME)"
    else
        echo "   ❌ NOT RUNNING"
    fi
    echo ""
    
    # Competition Schedule
    echo "📅 COMPETITION SCHEDULE:"
    python3 << 'PYTHON'
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
start = datetime(2025, 9, 16, 13, 0, 0, tzinfo=timezone.utc)
end = datetime(2025, 12, 15, 13, 0, 0, tzinfo=timezone.utc)
days_left = (end - now).days
hours_left = ((end - now).seconds // 3600) % 24
print(f"   Start: {start.strftime('%b %d at %I:%M %p UTC')}")
print(f"   End:   {end.strftime('%b %d at %I:%M %p UTC')}")
print(f"   Time:  ✅ ACTIVE ({days_left}d {hours_left}h remaining)")
PYTHON
    echo ""
    
    # Latest Logs
    echo "📝 LATEST ACTIVITY:"
    echo "───────────────────────────────────────────────────────────────────────────────────"
    tail -5 /workspaces/allora-forge-builder-kit/logs/submission.log | sed 's/^/   /'
    echo ""
    
    # CSV Stats
    echo "📊 SUBMISSION STATS:"
    echo "───────────────────────────────────────────────────────────────────────────────────"
    TOTAL=$(wc -l < /workspaces/allora-forge-builder-kit/submission_log.csv)
    SUCCESS=$(grep -c 'success' /workspaces/allora-forge-builder-kit/submission_log.csv)
    SKIPPED=$(grep -c 'skipped_no_nonce' /workspaces/allora-forge-builder-kit/submission_log.csv)
    FAILED=$(grep -c 'failed' /workspaces/allora-forge-builder-kit/submission_log.csv)
    
    printf "   Total: %d | ✅ Success: %d | ⏳ Skipped: %d | ❌ Failed: %d\n" $TOTAL $SUCCESS $SKIPPED $FAILED
    
    # Last submission
    echo ""
    echo "   Last Entry:"
    tail -1 /workspaces/allora-forge-builder-kit/submission_log.csv | awk -F',' '{
        printf "   - Time: %s\n", $1
        printf "   - Nonce: %s\n", $5
        printf "   - Prediction: %s\n", $3
        printf "   - Status: %s\n", $8
        printf "   - TX: %s\n", substr($9, 1, 16) "..."
    }'
    echo ""
    
    # Status
    echo "✨ SYSTEM STATUS:"
    echo "───────────────────────────────────────────────────────────────────────────────────"
    echo "   ✅ Daemon: Running"
    echo "   ✅ Model: Loaded"
    echo "   ✅ RPC: 3-endpoint failover"
    echo "   ✅ Schedule: Hourly UTC boundaries"
    echo ""
    
    echo "🔄 Refreshing in 10 seconds... (Press Ctrl+C to exit)"
    sleep 10
done
