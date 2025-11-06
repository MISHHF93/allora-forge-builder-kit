#!/bin/bash
# Check status of continuous monitoring

echo "=== Allora Competition Monitor Status ==="
echo "Current time: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo ""

# Check if monitor is running
if ps aux | grep -q "[c]ontinuous_monitor"; then
    echo "✅ Continuous monitoring: ACTIVE"
    echo "   Process: $(ps aux | grep [c]ontinuous_monitor | awk '{print $2}')"
else
    echo "❌ Continuous monitoring: INACTIVE"
fi

echo ""
echo "=== Cron Job Status ==="
if crontab -l | grep -q "run_pipeline.sh"; then
    echo "✅ Cron job: ACTIVE"
    echo "   Schedule: $(crontab -l | grep run_pipeline.sh)"
else
    echo "❌ Cron job: INACTIVE"
fi

echo ""
echo "=== Latest Submission ==="
if [ -f "data/artifacts/logs/submission_log.csv" ]; then
    tail -1 data/artifacts/logs/submission_log.csv | awk -F',' '{print "Time: "$1, "Status: "$8, "Success: "$6}'
else
    echo "No submission log found"
fi

echo ""
echo "=== Next Submission Window ==="
CURRENT_HOUR=$(date -u +"%H")
NEXT_HOUR=$(( (CURRENT_HOUR + 1) % 24 ))
printf -v NEXT_TIME "%02d:05" $NEXT_HOUR
echo "Next check: Today at ${NEXT_TIME} UTC"