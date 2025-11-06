#!/bin/bash
# Setup cron job for hourly pipeline execution
# Run this on your cloud instance to schedule the pipeline

# Add to crontab (runs at minute 5 of every hour)
CRON_JOB="5 * * * * /workspaces/allora-forge-builder-kit/run_pipeline.sh"

# Check if cron job already exists
if crontab -l | grep -q "run_pipeline.sh"; then
    echo "Cron job already exists"
else
    # Add the cron job
    (crontab -l ; echo "$CRON_JOB") | crontab -
    echo "Added cron job: $CRON_JOB"
fi

echo "Current crontab:"
crontab -l