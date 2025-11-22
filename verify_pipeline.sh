#!/bin/bash
###############################################################################
# Allora Pipeline Verification Script
###############################################################################
# Purpose: Verify single pipeline instance runs successfully and logs
#          complete submissions matching the artifact pattern.
#
# Usage:
#   ./verify_pipeline.sh [--test-duration HOURS] [--dry-run]
#
# Example:
#   ./verify_pipeline.sh --test-duration 2 --dry-run
#   ./verify_pipeline.sh --test-duration 24
###############################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
TEST_DURATION_HOURS=2
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --test-duration)
      TEST_DURATION_HOURS="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

###############################################################################
# Helper functions
###############################################################################
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}

warn() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $*" >&2
}

check_env() {
  log "Checking environment..."
  
  if [ ! -f .env ]; then
    error ".env file not found"
  fi
  
  source .env
  
  local required=("ALLORA_WALLET_ADDR" "MNEMONIC" "TOPIC_ID")
  for var in "${required[@]}"; do
    if [ -z "${!var}" ]; then
      error "Missing required environment variable: $var"
    fi
  done
  
  log "✓ Environment configured"
  log "  - Wallet: ${ALLORA_WALLET_ADDR:0:15}..."
  log "  - Topic ID: $TOPIC_ID"
}

check_files() {
  log "Checking required files..."
  
  local required=("model.pkl" "features.json" "submit_prediction.py" "train.py")
  for file in "${required[@]}"; do
    if [ ! -f "$file" ]; then
      error "Missing required file: $file"
    fi
  done
  
  log "✓ All required files present"
}

check_venv() {
  log "Checking virtual environment..."
  
  if [ ! -d .venv ]; then
    error "Virtual environment not found at .venv"
  fi
  
  source .venv/bin/activate
  log "✓ Virtual environment activated"
}

count_submissions() {
  if [ ! -f submission_log.csv ]; then
    echo "0"
    return
  fi
  tail -n +2 submission_log.csv | wc -l
}

count_successful() {
  if [ ! -f submission_log.csv ]; then
    echo "0"
    return
  fi
  grep "success" submission_log.csv | wc -l
}

validate_csv_record() {
  local line="$1"
  local fields=$(echo "$line" | awk -F',' '{print NF}')
  
  if [ "$fields" -lt 8 ]; then
    return 1
  fi
  return 0
}

###############################################################################
# Main verification
###############################################################################
main() {
  log "========================================"
  log "Allora Pipeline Verification"
  log "========================================"
  log "Test Duration: ${TEST_DURATION_HOURS} hour(s)"
  log "Dry Run: $DRY_RUN"
  echo ""
  
  # Pre-flight checks
  check_env
  check_files
  check_venv
  
  # Check for existing pipeline
  log "Checking for existing pipeline processes..."
  existing=$(ps aux | grep "submit_prediction.py.*continuous" | grep -v grep | wc -l || true)
  if [ "$existing" -gt 0 ]; then
    error "Found $existing existing pipeline process(es). Stop them first with: pkill -f 'submit_prediction.py.*continuous'"
  fi
  log "✓ No existing pipeline processes"
  echo ""
  
  # Record baseline
  log "Recording baseline..."
  baseline_submissions=$(count_submissions)
  baseline_successful=$(count_successful)
  log "  - Current submissions: $baseline_submissions"
  log "  - Successful submissions: $baseline_successful"
  echo ""
  
  # Start pipeline
  log "Starting single pipeline instance..."
  
  if [ "$DRY_RUN" = true ]; then
    log "DRY-RUN MODE: Showing command that would be executed:"
    echo ""
    echo "nohup python submit_prediction.py --continuous > logs/pipeline_test.log 2>&1 &"
    echo "PIPELINE_PID=\$!"
    echo ""
    error "Dry-run mode - exiting before starting pipeline"
  fi
  
  # Start in background
  nohup python submit_prediction.py --continuous > logs/pipeline_test.log 2>&1 &
  PIPELINE_PID=$!
  
  log "✓ Pipeline started with PID: $PIPELINE_PID"
  echo ""
  
  # Monitor for test duration
  log "Monitoring pipeline for $TEST_DURATION_HOURS hour(s)..."
  echo "  You can check logs at: tail -f logs/pipeline_test.log"
  echo ""
  
  TEST_SECONDS=$((TEST_DURATION_HOURS * 3600))
  INTERVAL=60
  ELAPSED=0
  
  while [ $ELAPSED -lt $TEST_SECONDS ]; do
    # Check if pipeline is still running
    if ! kill -0 $PIPELINE_PID 2>/dev/null; then
      error "Pipeline process (PID $PIPELINE_PID) died unexpectedly!"
    fi
    
    # Count current submissions
    current_submissions=$(count_submissions)
    current_successful=$(count_successful)
    new_submissions=$((current_submissions - baseline_submissions))
    new_successful=$((current_successful - baseline_successful))
    
    elapsed_time=$(printf "%02d:%02d:%02d" $((ELAPSED/3600)) $((ELAPSED%3600/60)) $((ELAPSED%60)))
    
    echo -ne "\r[$elapsed_time] Submissions: $current_submissions (+$new_submissions) | Success: $new_successful "
    
    ELAPSED=$((ELAPSED + INTERVAL))
    sleep $INTERVAL
  done
  
  echo ""
  echo ""
  log "Test period complete. Checking results..."
  echo ""
  
  # Final stats
  final_submissions=$(count_submissions)
  final_successful=$(count_successful)
  new_submissions=$((final_submissions - baseline_submissions))
  new_successful=$((final_successful - baseline_submissions))
  
  log "FINAL RESULTS:"
  log "  - Total submissions: $final_submissions (+$new_submissions new)"
  log "  - Successful submissions: $final_successful (+$new_successful new)"
  
  if [ $new_submissions -gt 0 ]; then
    success_rate=$((new_successful * 100 / new_submissions))
    log "  - Success rate: $success_rate%"
  else
    warn "No new submissions during test period"
  fi
  
  # Validate recent records
  echo ""
  log "Validating recent CSV records..."
  if [ -f submission_log.csv ]; then
    invalid_count=0
    recent=$(tail -n 5 submission_log.csv)
    while IFS= read -r line; do
      if ! validate_csv_record "$line"; then
        invalid_count=$((invalid_count + 1))
        warn "Invalid record: $line"
      fi
    done <<< "$recent"
    
    if [ $invalid_count -eq 0 ]; then
      log "✓ All recent records are complete (8 fields)"
    else
      error "$invalid_count invalid records found"
    fi
  fi
  
  # Check for single pipeline
  echo ""
  log "Verifying single pipeline instance..."
  current_processes=$(ps aux | grep "submit_prediction.py.*continuous" | grep -v grep | wc -l || true)
  if [ "$current_processes" -eq 1 ]; then
    log "✓ Exactly one pipeline process running"
  else
    error "Expected 1 pipeline process, found $current_processes"
  fi
  
  # Final message
  echo ""
  log "========================================"
  if [ $new_successful -gt 0 ]; then
    log "✓ VERIFICATION PASSED"
    log "  - Single pipeline running successfully"
    log "  - Submissions logged with complete records"
    log "  - Ready for production deployment"
  else
    log "⚠ VERIFICATION INCONCLUSIVE"
    log "  - Pipeline running but no successful submissions yet"
    log "  - Check logs: tail -f logs/pipeline_test.log"
    log "  - May need longer test duration or blockchain fixes"
  fi
  log "========================================"
}

main "$@"
