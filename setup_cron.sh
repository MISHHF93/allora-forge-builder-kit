#!/bin/bash
# Cron scheduler setup for Allora competition submission
# This script configures automated hourly submissions

REPO_DIR="/workspaces/allora-forge-builder-kit"
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
LOGS_DIR="$REPO_DIR/logs"

# Make scripts executable
chmod +x "$LOGS_DIR/rotate_logs.sh" 2>/dev/null || true
chmod +x "$LOGS_DIR/healthcheck.sh" 2>/dev/null || true
chmod +x "$REPO_DIR/competition_submission.py" 2>/dev/null || true

# Display current crontab (if exists)
echo "Current crontab:"
crontab -l 2>/dev/null || echo "(no crontab scheduled)"

echo ""
echo "To enable automatic submissions, add these lines to your crontab (crontab -e):"
echo ""
echo "# Allora competition submissions - every hour at HH:00:00 UTC"
echo "0 * * * * cd $REPO_DIR && $PYTHON_BIN competition_submission.py --once >> $LOGS_DIR/pipeline_run.log 2>&1"
echo ""
echo "# Log rotation - every hour at HH:05:00 UTC"
echo "5 * * * * $LOGS_DIR/rotate_logs.sh >> $LOGS_DIR/pipeline_run.log 2>&1"
echo ""
echo "# Health check - every hour at HH:10:00 UTC"
echo "10 * * * * $LOGS_DIR/healthcheck.sh"
echo ""
echo "Note: All times in UTC. Adjust as needed for your timezone."
