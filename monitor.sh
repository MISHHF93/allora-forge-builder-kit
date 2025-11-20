#!/bin/bash
# Real-time pipeline monitoring script

echo "═══════════════════════════════════════════════════════════════════════════"
echo "🔍 ALLORA PIPELINE MONITOR"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

# Check PIDs
echo "�� PROCESS STATUS:"
echo "───────────────────────────────────────────────────────────────────────────"
PIDS=$(ps aux | grep "python train.py" | grep -v grep)
if [ -z "$PIDS" ]; then
    echo "⚠️  No pipeline processes running"
else
    echo "$PIDS" | awk '{printf "✅ PID %s | CPU: %s%% | MEM: %s%% | CMD: %s %s %s\n", $2, $3, $4, $11, $12, $13}'
    PID_COUNT=$(echo "$PIDS" | wc -l)
    echo ""
    echo "Total processes: $PID_COUNT"
    
    # Check stored PID
    if [ -f pipeline.pid ]; then
        STORED_PID=$(cat pipeline.pid)
        if ps -p $STORED_PID > /dev/null 2>&1; then
            echo "✅ Stored PID ($STORED_PID) is running"
        else
            echo "⚠️  Stored PID ($STORED_PID) is NOT running"
        fi
    fi
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "📝 RECENT LOG ACTIVITY (Last 15 lines):"
echo "───────────────────────────────────────────────────────────────────────────"
if [ -f pipeline_loop.log ]; then
    tail -15 pipeline_loop.log | sed 's/^/  /'
else
    echo "  No log file found"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "📊 SUBMISSION HISTORY (Last 5 attempts):"
echo "───────────────────────────────────────────────────────────────────────────"
python train.py --inspect-log --inspect-tail 5 2>/dev/null | grep -E "^(202|false|true)" | tail -5 | while IFS=, read -r timestamp topic value wallet nonce tx success exit status loss score reward; do
    timestamp=$(echo $timestamp | xargs)
    success=$(echo $success | xargs)
    status=$(echo $status | xargs)
    
    if [ "$success" = "true" ]; then
        icon="✅"
    else
        icon="⏸️ "
    fi
    
    printf "%s %s | Status: %-25s | Loss: %s\n" "$icon" "$timestamp" "$status" "$loss"
done

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "🎯 CURRENT STATUS:"
echo "───────────────────────────────────────────────────────────────────────────"

# Get latest submission status
LATEST=$(tail -1 submission_log.csv 2>/dev/null)
if [ ! -z "$LATEST" ]; then
    echo "Last attempt: $(echo $LATEST | cut -d',' -f1 | xargs)"
    SUCCESS=$(echo $LATEST | cut -d',' -f7 | xargs)
    STATUS=$(echo $LATEST | cut -d',' -f9 | xargs)
    TX=$(echo $LATEST | cut -d',' -f6 | xargs)
    
    if [ "$SUCCESS" = "true" ]; then
        echo "✅ Status: SUCCESSFUL SUBMISSION"
        echo "📡 TX Hash: $TX"
    else
        echo "⏸️  Status: $STATUS"
        if [[ "$STATUS" == *"window"* ]]; then
            echo "💡 TIP: Waiting for submission window to open"
        fi
    fi
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "⏰ $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "═══════════════════════════════════════════════════════════════════════════"
