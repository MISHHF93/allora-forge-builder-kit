#!/bin/bash
# Allora Competition Pipeline Launcher
# Topic 67: 7-day BTC/USD Log-Return Prediction (Hourly Submissions)
# This script starts the pipeline with full environment validation

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "════════════════════════════════════════════════════════════════════"
echo "Allora Competition Pipeline Launcher"
echo "════════════════════════════════════════════════════════════════════"

# Load environment from .env file
if [ -f .env ]; then
    echo "✅ Loading environment from .env file..."
    export $(grep -v '^#' .env | xargs)
else
    echo "⚠️  .env file not found - using system environment variables"
fi

# Verify credentials are set
echo ""
echo "1. WALLET CREDENTIAL VERIFICATION"
echo "────────────────────────────────────────────────────────────────────"

if [ -z "$MNEMONIC" ]; then
    echo "❌ ERROR: MNEMONIC not set in .env or environment"
    exit 1
fi

if [ -z "$ALLORA_WALLET_ADDR" ]; then
    echo "❌ ERROR: ALLORA_WALLET_ADDR not set in .env or environment"
    exit 1
fi

if [ -z "$TOPIC_ID" ]; then
    TOPIC_ID="67"
    export TOPIC_ID
fi

echo "✅ Wallet credentials loaded:"
echo "   Address: $ALLORA_WALLET_ADDR"
echo "   Topic ID: $TOPIC_ID"
echo "   Mnemonic: ${MNEMONIC:0:30}... (masked)"

# Verify Python environment
echo ""
echo "2. PYTHON ENVIRONMENT CHECK"
echo "────────────────────────────────────────────────────────────────────"

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✅ Python version: $PYTHON_VERSION"

# Check required packages
REQUIRED_PACKAGES=("xgboost" "numpy" "sklearn" "allora_sdk")
MISSING_PACKAGES=()

for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if python3 -c "import $pkg" 2>/dev/null; then
        # Map back to display names
        case $pkg in
            sklearn) echo "✅ scikit-learn installed" ;;
            allora_sdk) echo "✅ allora-sdk installed" ;;
            *) echo "✅ $pkg installed" ;;
        esac
    else
        case $pkg in
            sklearn) MISSING_PACKAGES+=("scikit-learn"); echo "⚠️  scikit-learn not found" ;;
            allora_sdk) MISSING_PACKAGES+=("allora-sdk"); echo "⚠️  allora-sdk not found" ;;
            *) MISSING_PACKAGES+=("$pkg"); echo "⚠️  $pkg not found" ;;
        esac
    fi
done

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo ""
    echo "Installing missing packages: ${MISSING_PACKAGES[*]}"
    pip install -q "${MISSING_PACKAGES[@]}"
    echo "✅ Dependencies installed"
fi

# Perform RPC connectivity check
echo ""
echo "3. RPC ENDPOINT CONNECTIVITY CHECK"
echo "────────────────────────────────────────────────────────────────────"

RPC_CHECK=$(python3 << 'PYTHON_EOF'
import sys
try:
    from allora_forge_builder_kit.rpc_utils import diagnose_rpc_connectivity
    status = diagnose_rpc_connectivity()
    working = sum(1 for v in status.values() if v)
    if working >= 1:
        print(f"{working}")
    else:
        print("0")
except Exception as e:
    print("0")
PYTHON_EOF
)

if [ "$RPC_CHECK" -ge 1 ]; then
    echo "✅ RPC endpoints verified ($RPC_CHECK working)"
else
    echo "⚠️  RPC endpoint check had issues, continuing anyway..."
fi

# Create logs directory if needed
echo ""
echo "4. LOG DIRECTORY SETUP"
echo "────────────────────────────────────────────────────────────────────"

LOG_DIR="$(pwd)/logs"
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
    echo "✅ Created logs directory: $LOG_DIR"
else
    echo "✅ Logs directory exists: $LOG_DIR"
fi

LOG_FILE="$LOG_DIR/submission.log"
PID_FILE="$LOG_DIR/pipeline.pid"

# Check if pipeline is already running
echo ""
echo "5. EXISTING PROCESS CHECK"
echo "────────────────────────────────────────────────────────────────────"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Pipeline already running (PID: $OLD_PID)"
        echo "   To stop: kill $OLD_PID"
        echo "   Or: pkill -f 'competition_submission.py'"
        exit 1
    else
        echo "✅ Previous process not running, starting fresh"
        rm -f "$PID_FILE"
    fi
else
    echo "✅ No previous process detected"
fi

# Start the pipeline
echo ""
echo "6. STARTING PIPELINE"
echo "────────────────────────────────────────────────────────────────────"

echo "🚀 Starting Allora competition pipeline..."
echo "   Topic: 67 (7-day BTC/USD Log-Return Prediction)"
echo "   Wallet: $ALLORA_WALLET_ADDR"
echo "   Interval: Hourly submissions"
echo "   Logging: $LOG_FILE"
echo ""

# Create a proper Python startup script that loads the environment
STARTUP_SCRIPT="/tmp/allora_startup_$$.py"
cat > "$STARTUP_SCRIPT" << 'STARTUP_EOF'
#!/usr/bin/env python3
import os
import sys

# Read .env file and set environment variables
# Try multiple paths to find .env
env_paths = [
    ".env",  # Current directory
    os.path.expanduser("~/.env"),  # Home directory
    "/workspaces/allora-forge-builder-kit/.env",  # Default workspace
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),  # Script directory
]

env_file = None
for path in env_paths:
    if os.path.exists(path):
        env_file = path
        break

if not env_file:
    print(f"ERROR: Could not find .env file. Tried: {env_paths}")
    sys.exit(1)

# Determine project directory
project_dir = os.path.dirname(os.path.abspath(env_file))

with open(env_file, 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key.strip()] = value.strip()

# Change to project directory and run pipeline
os.chdir(project_dir)
os.execvp("python3", ["python3", "competition_submission.py"])
STARTUP_EOF

chmod +x "$STARTUP_SCRIPT"

# Start in background with nohup
nohup python3 "$STARTUP_SCRIPT" > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PID_FILE"

# Give the process a moment to start
sleep 2

# Verify process is running
if kill -0 $NEW_PID 2>/dev/null; then
    echo "✅ Pipeline started successfully"
    echo "   PID: $NEW_PID"
    echo "   Log file: $LOG_FILE"
    echo ""
    echo "════════════════════════════════════════════════════════════════════"
    echo "MONITORING TIPS:"
    echo "  • View logs:        tail -f $LOG_FILE"
    echo "  • Last 100 lines:   tail -100 $LOG_FILE"
    echo "  • Stop pipeline:    pkill -f 'competition_submission.py'"
    echo "  • Check status:     ps aux | grep 'competition_submission.py'"
    echo "════════════════════════════════════════════════════════════════════"
    
    # Clean up startup script
    rm -f "$STARTUP_SCRIPT"
else
    echo "❌ Failed to start pipeline"
    cat "$LOG_FILE"
    rm -f "$STARTUP_SCRIPT"
    exit 1
fi
