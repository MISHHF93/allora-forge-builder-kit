#!/bin/bash
# Automated Allora Forge Builder Kit Pipeline Runner
# Runs hourly training and submission for Topic 67 competition

set -euo pipefail

# Configuration
REPO_ROOT="/workspaces/allora-forge-builder-kit"
LOG_DIR="$REPO_ROOT/data/artifacts/logs"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_FILE="$LOG_DIR/pipeline_run_$TIMESTAMP.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Function to log with timestamp
log() {
    echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") $*" | tee -a "$LOG_FILE"
}

# Main execution
log "Starting automated pipeline run"

# Check if we're within competition timeframe
CURRENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
COMPETITION_START="2025-09-16T00:00:00Z"
COMPETITION_END="2025-12-15T23:00:00Z"

if [[ "$CURRENT_TIME" < "$COMPETITION_START" ]]; then
    log "Before competition start, exiting"
    exit 0
fi

if [[ "$CURRENT_TIME" > "$COMPETITION_END" ]]; then
    log "After competition end, exiting"
    exit 0
fi

# Check if it's top of the hour (within 5 minutes)
MINUTE=$(date -u +"%M")
if [[ "$MINUTE" -gt 5 ]]; then
    log "Not top of hour (minute: $MINUTE), exiting"
    exit 0
fi

log "Running train-and-submit for Topic 67"

# Run the pipeline
cd "$REPO_ROOT"
if python -m allora_forge_builder_kit.cli train-and-submit >> "$LOG_FILE" 2>&1; then
    log "Pipeline completed successfully"
else
    log "Pipeline failed with exit code $?"
    # Don't exit with error to avoid cron spam, but log it
fi

log "Automated pipeline run completed"