#!/bin/bash
#
# Allora Submission System Diagnostic & Monitoring Script
# Purpose: Verify submission daemon is healthy and submissions are on-chain
# Usage: ./monitor_submissions.sh [options]
#
# Options:
#   --full       : Full system check with on-chain validation
#   --quick      : Quick status check only
#   --csv        : Show CSV audit trail
#   --rpc        : Test RPC endpoints
#   --help       : Show this help
#

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Config
WALLET="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
TOPIC_ID="67"
RPC_PRIMARY="https://allora-rpc.testnet.allora.network/"
RPC_ALT1="https://allora-testnet-rpc.allthatnode.com:1317/"
RPC_ALT2="https://allora.api.chandrastation.com/"

# Default to quick check
MODE="${1:---quick}"

###############################################################################
# Helper Functions
###############################################################################

print_header() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

###############################################################################
# Quick Status Check
###############################################################################

check_quick_status() {
    print_header "QUICK STATUS CHECK"
    
    # Check if daemon is running
    if pgrep -f "submit_prediction.py --daemon" > /dev/null 2>&1; then
        PID=$(pgrep -f "submit_prediction.py --daemon" | head -1)
        print_success "Daemon running (PID: $PID)"
        
        # Get memory usage
        MEMORY=$(ps aux | grep "submit_prediction.py --daemon" | grep -v grep | awk '{print $6}')
        print_info "Memory usage: ${MEMORY}KB"
    else
        print_error "Daemon NOT running"
        echo "Start with: python submit_prediction.py --daemon"
        return 1
    fi
    
    # Check latest submission
    if [ -f latest_submission.json ]; then
        echo ""
        print_info "Latest submission details:"
        cat latest_submission.json | jq '{
            timestamp: .timestamp,
            status: .status,
            tx_hash: .tx_hash,
            rpc: .rpc_endpoint,
            prediction: .prediction
        }' 2>/dev/null || print_error "Cannot parse latest_submission.json"
    else
        print_error "latest_submission.json not found"
    fi
    
    # Check recent logs
    echo ""
    print_info "Recent log activity:"
    if [ -f logs/submission.log ]; then
        HEARTBEAT=$(grep "HEARTBEAT" logs/submission.log | tail -1 || echo "Not found")
        echo "Last heartbeat: $HEARTBEAT" | sed 's/.*HEARTBEAT/HEARTBEAT/'
        
        CYCLE=$(grep "SUBMISSION CYCLE" logs/submission.log | tail -1 || echo "Not found")
        echo "Last cycle: $CYCLE" | sed 's/.*SUBMISSION CYCLE/SUBMISSION CYCLE/'
        
        ERROR=$(grep "ERROR\|CRITICAL" logs/submission.log | tail -1 || echo "None")
        if [[ $ERROR != "None" ]]; then
            print_warning "Recent error: $ERROR"
        else
            print_success "No recent errors in logs"
        fi
    else
        print_error "logs/submission.log not found"
    fi
}

###############################################################################
# CSV Audit Trail
###############################################################################

check_csv_audit() {
    print_header "CSV AUDIT TRAIL"
    
    if [ ! -f submission_log.csv ]; then
        print_error "submission_log.csv not found"
        return 1
    fi
    
    TOTAL=$(grep -c "^2025" submission_log.csv || echo "0")
    SUCCESS=$(grep "success" submission_log.csv | wc -l)
    FAILED=$(grep -v "success\|^timestamp" submission_log.csv | wc -l)
    
    print_info "CSV Statistics:"
    echo "  Total submissions: $TOTAL"
    echo "  Successful: $SUCCESS"
    echo "  Failed/Skipped: $FAILED"
    
    if [ "$TOTAL" -gt 0 ]; then
        SUCCESS_RATE=$(( SUCCESS * 100 / TOTAL ))
        echo "  Success rate: $SUCCESS_RATE%"
    fi
    
    echo ""
    print_info "RPC Endpoint usage:"
    cut -d',' -f10 submission_log.csv | tail -n +2 | sort | uniq -c | sort -rn
    
    echo ""
    print_info "Last 5 submissions:"
    tail -5 submission_log.csv | column -t -s','
}

###############################################################################
# RPC Endpoint Testing
###############################################################################

test_rpc_endpoint() {
    local url=$1
    local name=$2
    
    print_info "Testing $name ($url)"
    
    # Test with curl
    RESPONSE=$(curl -s -m 5 "$url/status" 2>&1 || echo "TIMEOUT")
    
    if [[ $RESPONSE == "TIMEOUT" ]]; then
        print_error "$name: TIMEOUT (5s)"
        return 1
    elif [[ $RESPONSE == *"<"* ]]; then
        print_error "$name: HTML response (likely error page)"
        return 1
    elif echo "$RESPONSE" | grep -q "node_info" 2>/dev/null; then
        print_success "$name: Responding (JSON valid)"
        
        # Extract node info
        CHAIN=$(echo "$RESPONSE" | jq -r '.result.node_info.network' 2>/dev/null || echo "?")
        VERSION=$(echo "$RESPONSE" | jq -r '.result.node_info.version' 2>/dev/null || echo "?")
        echo "  Chain: $CHAIN, Version: $VERSION"
        return 0
    else
        print_warning "$name: Invalid response (may be down)"
        return 1
    fi
}

check_rpc_health() {
    print_header "RPC ENDPOINT HEALTH CHECK"
    
    echo ""
    test_rpc_endpoint "$RPC_PRIMARY" "Primary (Allora)" && GOOD=$((GOOD + 1)) || GOOD=0
    echo ""
    test_rpc_endpoint "$RPC_ALT1" "Fallback #1 (AllThatNode)" && GOOD=$((GOOD + 1)) || true
    echo ""
    test_rpc_endpoint "$RPC_ALT2" "Fallback #2 (ChandraStation)" && GOOD=$((GOOD + 1)) || true
    
    echo ""
    if [ $GOOD -gt 0 ]; then
        print_success "At least one RPC endpoint is healthy"
    else
        print_error "All RPC endpoints appear to be down"
        return 1
    fi
}

###############################################################################
# Full System Check
###############################################################################

check_full_system() {
    print_header "FULL SYSTEM DIAGNOSTIC"
    
    # 1. Process check
    echo ""
    print_info "Step 1/6: Process Status"
    if pgrep -f "submit_prediction.py --daemon" > /dev/null 2>&1; then
        PID=$(pgrep -f "submit_prediction.py --daemon" | head -1)
        print_success "Daemon running (PID: $PID)"
    else
        print_error "Daemon NOT running"
        return 1
    fi
    
    # 2. File checks
    echo ""
    print_info "Step 2/6: Required Files"
    [ -f model.pkl ] && print_success "model.pkl found" || print_error "model.pkl missing"
    [ -f features.json ] && print_success "features.json found" || print_error "features.json missing"
    [ -f latest_submission.json ] && print_success "latest_submission.json found" || print_warning "latest_submission.json missing"
    [ -f logs/submission.log ] && print_success "logs/submission.log found" || print_error "logs/submission.log missing"
    
    # 3. RPC endpoint health
    echo ""
    print_info "Step 3/6: RPC Endpoint Health"
    check_rpc_health || true
    
    # 4. Recent log analysis
    echo ""
    print_info "Step 4/6: Recent Log Analysis"
    if [ -f logs/submission.log ]; then
        HEARTBEAT=$(grep "HEARTBEAT" logs/submission.log | tail -1)
        if [ -n "$HEARTBEAT" ]; then
            print_success "Heartbeat found: $(echo $HEARTBEAT | tail -c 50)"
        else
            print_warning "No heartbeat found in logs"
        fi
        
        ERRORS=$(grep "ERROR\|CRITICAL" logs/submission.log | tail -3)
        if [ -z "$ERRORS" ]; then
            print_success "No errors in recent logs"
        else
            print_warning "Errors found:"
            echo "$ERRORS" | sed 's/^/  /'
        fi
    fi
    
    # 5. Transaction validation
    echo ""
    print_info "Step 5/6: Latest Transaction Validation"
    if [ -f latest_submission.json ]; then
        TX_HASH=$(jq -r '.tx_hash' latest_submission.json 2>/dev/null || echo "")
        if [ -z "$TX_HASH" ] || [ "$TX_HASH" == "null" ] || [ "$TX_HASH" == "" ]; then
            print_warning "No transaction hash in latest_submission.json"
        else
            print_info "Querying transaction: $TX_HASH"
            
            RESULT=$(curl -s -m 10 "${RPC_PRIMARY}cosmos/tx/v1beta1/txs/$TX_HASH" 2>&1)
            if echo "$RESULT" | grep -q '"code":0'; then
                print_success "Transaction confirmed on-chain (code: 0)"
                BLOCK=$(echo "$RESULT" | jq -r '.tx_response.height' 2>/dev/null || echo "?")
                print_info "Block height: $BLOCK"
            elif echo "$RESULT" | grep -q '"code"'; then
                CODE=$(echo "$RESULT" | jq -r '.tx_response.code' 2>/dev/null || echo "?")
                print_error "Transaction failed on-chain (code: $CODE)"
            else
                print_warning "Cannot validate transaction (query failed)"
            fi
        fi
    fi
    
    # 6. Summary
    echo ""
    print_info "Step 6/6: System Summary"
    DAYS_LEFT=$(date -d "2025-12-15" +%s 2>/dev/null | awk -v now="$(date +%s)" '{print int(($1 - now) / 86400)}' || echo "?")
    echo "  Days until competition end: $DAYS_LEFT"
    echo "  Wallet address: $WALLET"
    echo "  Topic ID: $TOPIC_ID"
    
    echo ""
    print_success "Full diagnostic complete"
}

###############################################################################
# Help
###############################################################################

show_help() {
    cat << EOF
${BLUE}Allora Submission System Diagnostic & Monitoring Script${NC}

Usage: $0 [OPTIONS]

Options:
  --quick       : Quick status check (default)
  --full        : Comprehensive system diagnostic with on-chain validation
  --csv         : Show CSV audit trail and statistics
  --rpc         : Test all RPC endpoints
  --help        : Show this help message

Examples:
  $0 --quick              # Quick status check
  $0 --full               # Full diagnostic
  $0 --csv                # View submission history
  $0 --rpc                # Test RPC endpoints

Examples (standalone commands):
  # Check if daemon is running
  ps aux | grep submit_prediction.py

  # View latest submission
  cat latest_submission.json | jq .

  # Monitor logs in real-time
  tail -f logs/submission.log

  # Check RPC health
  curl https://allora-rpc.testnet.allora.network/status

  # Query latest transaction
  TX=\$(cat latest_submission.json | jq -r .tx_hash)
  curl https://allora-rpc.testnet.allora.network/cosmos/tx/v1beta1/txs/\$TX | jq .tx_response.code

${YELLOW}Status Colors:${NC}
  ${GREEN}✅${NC} Success / Healthy
  ${RED}❌${NC} Error / Unhealthy
  ${YELLOW}⚠️${NC} Warning / Attention needed

For more details, see RPC_FAILOVER_QUICK_REFERENCE.md and LEADERBOARD_INVESTIGATION.md
EOF
}

###############################################################################
# Main
###############################################################################

case "$MODE" in
    --quick)
        check_quick_status
        ;;
    --full)
        check_quick_status
        echo ""
        check_full_system
        ;;
    --csv)
        check_csv_audit
        ;;
    --rpc)
        check_rpc_health
        ;;
    --help|-h)
        show_help
        ;;
    *)
        echo "Unknown option: $MODE"
        show_help
        exit 1
        ;;
esac

echo ""
