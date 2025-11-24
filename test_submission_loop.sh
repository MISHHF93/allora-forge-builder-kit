#!/bin/bash
# Test submission loop - runs submission every 10 seconds for quick testing

echo "🧪 TEST SUBMISSION LOOP STARTED"
echo "================================"
echo "Running submission tests every 10 seconds"
echo "Monitor with: tail -f /workspaces/allora-forge-builder-kit/logs/submission.log"
echo ""

cd /workspaces/allora-forge-builder-kit

iteration=0
while true; do
    iteration=$((iteration + 1))
    timestamp=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
    
    echo "[$timestamp] Running test cycle #$iteration..."
    
    python3 submit_prediction.py --once --model model.pkl --features features.json 2>&1 | grep -E "✅|⚠️|❌|Prediction|LEADERBOARD|nonce|Logged"
    
    echo "[$timestamp] Test cycle #$iteration complete. Waiting 10 seconds before next test..."
    echo ""
    
    sleep 10
done
