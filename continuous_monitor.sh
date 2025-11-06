#!/bin/bash
# Continuous monitoring and submission script for Allora competition
# Runs in a loop, checking every 5 minutes if it's time to submit

set -euo pipefail

REPO_ROOT="/workspaces/allora-forge-builder-kit"
LOG_DIR="$REPO_ROOT/data/artifacts/logs"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="$LOG_DIR/continuous_monitor_$TIMESTAMP.log"

mkdir -p "$LOG_DIR"

log() {
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") $*" | tee -a "$LOG_FILE"
}

log "Starting continuous monitoring for Allora competition submissions"

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
        exit 0
    fi

    # Check if it's time to submit (near top of hour, within 5 minutes)
    if [[ "$CURRENT_MINUTE" -le 5 ]]; then
        log "Time to check submission for hour $(date -u +"%H"):00"

        # Run the pipeline
        cd "$REPO_ROOT"
        if python -m allora_forge_builder_kit.cli train-and-submit >> "$LOG_FILE" 2>&1; then
            log "Pipeline completed successfully"
        else
            log "Pipeline failed with exit code $?"
        fi

        # Wait until next hour to avoid multiple submissions
        sleep 3300  # Wait 55 minutes (until 5 minutes before next hour)
    else
        # Not submission time, just log we're monitoring
        NEXT_SUBMISSION=$((60 - CURRENT_MINUTE + 5))
        log "Monitoring active. Next submission check in ${NEXT_SUBMISSION} minutes (at :05)"
        sleep 300  # Check every 5 minutes
    fi
done