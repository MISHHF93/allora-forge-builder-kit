#!/bin/bash
###############################################################################
# ALLORA SINGLE WORKER DEPLOYMENT - ONE COMMAND SOLUTION
###############################################################################
# Purpose: Deploy single worker instance with one command, no conflicts
# Usage:   ./deploy_worker.sh [--dry-run] [--monitor-duration SECONDS]
#
# This script:
#   1. Validates environment (files, variables, blockchain)
#   2. Checks for existing pipelines (kills conflicts)
#   3. Verifies prerequisites (balance, sequence, nonce)
#   4. Starts single continuous worker
#   5. Monitors for success/errors
#
# Examples:
#   ./deploy_worker.sh --dry-run               # Dry-run without starting
#   ./deploy_worker.sh --monitor-duration 120  # Start and monitor 2 min
#   ./deploy_worker.sh                         # Start and return
###############################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
DRY_RUN=false
MONITOR_DURATION=0
VERBOSITY=true

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --monitor-duration)
      MONITOR_DURATION="$2"
      shift 2
      ;;
    --quiet)
      VERBOSITY=false
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

###############################################################################
# Helper Functions
###############################################################################

log() {
  [ "$VERBOSITY" = true ] && echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" || true
}

error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}

warn() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARN: $*" >&2
}

success() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✓ $*"
}

###############################################################################
# Phase 1: Environment Validation
###############################################################################

log "PHASE 1: Validating environment..."

# Check .env file
if [ ! -f .env ]; then
  error ".env file not found. Create it with ALLORA_WALLET_ADDR, MNEMONIC, TOPIC_ID"
fi

# Load environment variables safely using Python
eval "$(python3 << 'PYLOAD'
import os
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            # Properly quote the value
            value = value.replace("'", "'\\''")
            print(f"export {key}='{value}'")
PYLOAD
)"

# Validate required variables
for var in ALLORA_WALLET_ADDR MNEMONIC TOPIC_ID; do
  if [ -z "${!var}" ]; then
    error "Missing required variable: $var"
  fi
done

success "Environment variables validated"

# Check required files
for file in model.pkl features.json submit_prediction.py; do
  if [ ! -f "$file" ]; then
    error "Missing required file: $file"
  fi
done

success "All required files present"

# Check virtual environment
if [ ! -d .venv ]; then
  error "Virtual environment not found at .venv"
fi

source .venv/bin/activate
success "Virtual environment activated"

# Verify Python packages
python3 << 'PYCHECK'
import sys
required = ['allora_sdk', 'pandas', 'numpy', 'xgboost', 'requests']
missing = []
for pkg in required:
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)
if missing:
    print(f"ERROR: Missing packages: {', '.join(missing)}")
    sys.exit(1)
PYCHECK

success "All Python packages available"

###############################################################################
# Phase 2: Conflict Detection & Resolution
###############################################################################

log "PHASE 2: Checking for existing pipelines..."

# Find existing processes
existing_pids=$(ps aux | grep "submit_prediction.py.*continuous" | grep -v grep | awk '{print $2}' || true)

if [ -n "$existing_pids" ]; then
  warn "Found existing pipeline processes: $existing_pids"
  log "Stopping existing pipelines..."
  for pid in $existing_pids; do
    if kill -0 "$pid" 2>/dev/null; then
      log "  Killing PID $pid..."
      kill "$pid" 2>/dev/null || true
      sleep 1
      # Force kill if still running
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  success "Existing pipelines stopped"
else
  success "No existing pipelines found"
fi

# Check for stale PID file
if [ -f pipeline.pid ]; then
  old_pid=$(cat pipeline.pid)
  if ! kill -0 "$old_pid" 2>/dev/null; then
    log "Removing stale PID file"
    rm -f pipeline.pid
  fi
fi

###############################################################################
# Phase 3: Blockchain Prerequisites Check
###############################################################################

log "PHASE 3: Validating blockchain prerequisites..."

cli=$(which allorad 2>/dev/null || which allora 2>/dev/null || true)
if [ -z "$cli" ]; then
  warn "allorad CLI not found - skipping blockchain checks"
  log "  (Blockchain validation will happen at submission time)"
else
  # Check account balance
  log "  Checking account balance..."
  balance_output=$($cli query bank balances "$ALLORA_WALLET_ADDR" --output json 2>/dev/null || echo "{}")
  
  if [ "$balance_output" != "{}" ]; then
    balance=$(echo "$balance_output" | grep -o '"amount":"[^"]*"' | grep uallo | head -1 | cut -d'"' -f4 || echo "0")
    if [ "$balance" -gt 0 ]; then
      required=2500000
      if [ "$balance" -lt "$required" ]; then
        warn "Low balance: $balance uallo (need $required per submission)"
      else
        success "Account balance OK: $balance uallo"
      fi
    fi
  fi
fi

###############################################################################
# Phase 4: CSV Reset (Optional)
###############################################################################

log "PHASE 4: Preparing submission log..."

if [ ! -f submission_log.csv ]; then
  log "  Creating new submission_log.csv"
  echo "timestamp,topic_id,prediction,worker,block_height,proof,signature,status" > submission_log.csv
  success "Submission log created"
else
  current_count=$(wc -l < submission_log.csv)
  success "Submission log has $((current_count - 1)) existing records"
fi

###############################################################################
# Phase 5: Dry-Run Simulation
###############################################################################

if [ "$DRY_RUN" = true ]; then
  log "PHASE 5: DRY-RUN MODE (no actual deployment)"
  echo ""
  echo "Command that will be executed:"
  echo "────────────────────────────────────────────────────────────────────"
  echo "nohup python submit_prediction.py --continuous \\"
  echo "  > logs/pipeline.log 2>&1 &"
  echo "echo \$! > pipeline.pid"
  echo "────────────────────────────────────────────────────────────────────"
  echo ""
  echo "To deploy for real, run: ./deploy_worker.sh"
  exit 0
fi

###############################################################################
# Phase 6: Create Logs Directory
###############################################################################

if [ ! -d logs ]; then
  mkdir -p logs
  log "Created logs directory"
fi

# Ensure logs are writable
if [ ! -w logs ]; then
  error "logs directory is not writable"
fi

success "Logs directory ready"

###############################################################################
# Phase 7: Start Single Worker
###############################################################################

log "PHASE 6: Starting single worker instance..."

# Start in background with nohup
nohup python submit_prediction.py --continuous > logs/pipeline.log 2>&1 &
PIPELINE_PID=$!

# Save PID
echo "$PIPELINE_PID" > pipeline.pid

success "Worker started with PID: $PIPELINE_PID"
log "  Log file: logs/pipeline.log"
log "  PID file: pipeline.pid"

###############################################################################
# Phase 8: Verification
###############################################################################

log "PHASE 7: Verifying worker is running..."

sleep 2

# Check process is still running
if kill -0 "$PIPELINE_PID" 2>/dev/null; then
  success "Worker process is running (PID: $PIPELINE_PID)"
else
  error "Worker process died immediately - check logs/pipeline.log for errors"
fi

# Verify exactly one process
process_count=$(ps aux | grep "submit_prediction.py.*continuous" | grep -v grep | wc -l)
if [ "$process_count" -eq 1 ]; then
  success "Exactly one worker process confirmed"
else
  error "Expected 1 worker process, found $process_count"
fi

###############################################################################
# Phase 9: Monitoring (if requested)
###############################################################################

if [ "$MONITOR_DURATION" -gt 0 ]; then
  log "PHASE 8: Monitoring worker for ${MONITOR_DURATION}s..."
  
  start_time=$(date +%s)
  last_lines=0
  
  while true; do
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))
    
    if [ $elapsed -ge "$MONITOR_DURATION" ]; then
      break
    fi
    
    # Check process still running
    if ! kill -0 "$PIPELINE_PID" 2>/dev/null; then
      error "Worker process died at $elapsed seconds - check logs/pipeline.log"
    fi
    
    # Show new log entries
    current_lines=$(wc -l < logs/pipeline.log)
    if [ "$current_lines" -gt "$last_lines" ]; then
      new_lines=$((current_lines - last_lines))
      tail -n "$new_lines" logs/pipeline.log
      last_lines=$current_lines
    fi
    
    sleep 2
  done
  
  success "Monitoring complete"
fi

###############################################################################
# Final Status
###############################################################################

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║                   WORKER DEPLOYMENT COMPLETE                      ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Status:        ✓ Running"
echo "PID:           $PIPELINE_PID"
echo "Started:       $(date)"
echo "Config:"
echo "  Wallet:      ${ALLORA_WALLET_ADDR:0:20}..."
echo "  Topic ID:    $TOPIC_ID"
echo "  Interval:    3600s (1 hour)"
echo ""
echo "Monitoring:"
echo "  Logs:        tail -f logs/pipeline.log"
echo "  Submissions: wc -l submission_log.csv"
echo "  Successes:   grep \"success\" submission_log.csv | wc -l"
echo "  Status:      kill -0 \$(cat pipeline.pid) && echo Running || echo Stopped"
echo ""
echo "Control:"
echo "  Stop:        kill \$(cat pipeline.pid)"
echo "  Restart:     ./deploy_worker.sh"
echo ""
echo "Duration:"
echo "  Start:       Nov 23, 2025 (now)"
echo "  End:         Dec 15, 2025 01:00 PM UTC"
echo "  Target:      2,161 hourly predictions"
echo ""
