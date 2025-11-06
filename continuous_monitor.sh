#!/bin/bash
# Continuous monitoring and submission script for Allora competition
# Runs in a loop, checking every 5 minutes if it's time to submit

# Make script more robust
set -uo pipefail  # Remove -e to handle errors gracefully

REPO_ROOT="/workspaces/allora-forge-builder-kit"
LOG_DIR="$REPO_ROOT/data/artifacts/logs"
PID_FILE="$LOG_DIR/continuous_monitor.pid"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="$LOG_DIR/continuous_monitor_$TIMESTAMP.log"

mkdir -p "$LOG_DIR"

# Function to cleanup on exit
cleanup() {
    log "Continuous monitoring stopping..."
    rm -f "$PID_FILE"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT SIGHUP

log() {
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") $*" | tee -a "$LOG_FILE"
}

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        log "Continuous monitoring already running (PID: $OLD_PID)"
        exit 1
    else
        log "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Write PID file
echo $$ > "$PID_FILE"

log "Starting continuous monitoring for Allora competition submissions (PID: $$)"

while true; do
    CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    CURRENT_MINUTE=$(date -u +"%M")

    # Check if within competition timeframe
    COMPETITION_START="2025-09-16T00:00:00Z"
    COMPETITION_END="2025-12-15T23:00:00Z"

    if [[ "$CURRENT_TIME" < "$COMPETITION_START" ]]; then
        log "Before competition start ($COMPETITION_START), waiting..."
        sleep 300  # Wait 5 minutes
        continue
    fi

    if [[ "$CURRENT_TIME" > "$COMPETITION_END" ]]; then
        log "After competition end ($COMPETITION_END), stopping"
        cleanup
    fi

    # Check if it's time to submit (near top of hour, within 5 minutes)
    if [[ "$CURRENT_MINUTE" -le 5 ]]; then
        log "Time to check submission for hour $(date -u +"%H"):00"

        # Run the pipeline with error handling
        cd "$REPO_ROOT" || {
            log "ERROR: Cannot change to repo directory $REPO_ROOT"
            sleep 60
            continue
        }
        
        if python -m allora_forge_builder_kit.cli train-and-submit >> "$LOG_FILE" 2>&1; then
            log "Pipeline completed successfully"
        else
            EXIT_CODE=$?
            log "Pipeline failed with exit code $EXIT_CODE"
            # Don't exit, just log and continue
        fi

        # Wait until next hour to avoid multiple submissions
        log "Waiting 55 minutes until next submission window..."
        sleep 3300  # Wait 55 minutes (until 5 minutes before next hour)
    else
        # Not submission time, just log we're monitoring
        NEXT_SUBMISSION=$((60 - CURRENT_MINUTE + 5))
        log "Monitoring active. Next submission check in ${NEXT_SUBMISSION} minutes (at :05)"
        sleep 300  # Check every 5 minutes
    fi
done