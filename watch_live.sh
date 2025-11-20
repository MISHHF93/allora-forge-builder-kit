#!/bin/bash
echo "🔴 LIVE MONITORING - Press Ctrl+C to stop"
echo ""
while true; do
    clear
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "🔍 ALLORA PIPELINE - LIVE MONITOR"
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo ""
    
    # PID Status
    PID=$(cat pipeline.pid 2>/dev/null)
    if ps -p $PID > /dev/null 2>&1; then
        CPU=$(ps -p $PID -o %cpu --no-headers | xargs)
        MEM=$(ps -p $PID -o %mem --no-headers | xargs)
        TIME=$(ps -p $PID -o etime --no-headers | xargs)
        echo "✅ Process Running | PID: $PID | CPU: ${CPU}% | MEM: ${MEM}% | Runtime: $TIME"
    else
        echo "⚠️  Process NOT running"
    fi
    
    echo ""
    echo "───────────────────────────────────────────────────────────────────────────"
    echo "📝 RECENT LOG (Last 20 lines):"
    echo "───────────────────────────────────────────────────────────────────────────"
    tail -20 pipeline_run.log 2>/dev/null | grep -E "(INFO|WARNING|ERROR|Lifecycle|Submission|iteration|Topic now)" | sed 's/^/  /'
    
    echo ""
    echo "───────────────────────────────────────────────────────────────────────────"
    echo "📊 LATEST SUBMISSION:"
    echo "───────────────────────────────────────────────────────────────────────────"
    LATEST=$(tail -1 submission_log.csv 2>/dev/null | tail -1)
    if [ ! -z "$LATEST" ]; then
        TIMESTAMP=$(echo "$LATEST" | cut -d',' -f1 | xargs)
        SUCCESS=$(echo "$LATEST" | cut -d',' -f7 | xargs)
        STATUS=$(echo "$LATEST" | cut -d',' -f9 | xargs)
        LOSS=$(echo "$LATEST" | cut -d',' -f10 | xargs)
        TX=$(echo "$LATEST" | cut -d',' -f6 | xargs)
        
        if [ "$SUCCESS" = "true" ]; then
            echo "  ✅ SUCCESS at $TIMESTAMP"
            echo "  📡 TX Hash: $TX"
            echo "  📊 Loss: $LOSS"
        else
            echo "  ⏸️  SKIPPED at $TIMESTAMP"
            echo "  📋 Status: $STATUS"
            echo "  📊 Loss: $LOSS"
        fi
    fi
    
    echo ""
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo "⏰ $(date '+%Y-%m-%d %H:%M:%S %Z') | Refreshing every 5 seconds..."
    echo "═══════════════════════════════════════════════════════════════════════════"
    
    sleep 5
done
