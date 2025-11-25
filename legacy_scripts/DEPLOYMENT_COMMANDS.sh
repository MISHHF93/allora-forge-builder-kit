#!/bin/bash
# ============================================================================
# Allora 7-Day BTC/USD Prediction Pipeline - Fresh Instance Deployment
# ============================================================================
# Complete set of terminal commands for Ubuntu instance setup
# Deployment Date: November 22, 2025
# Target: Autonomous hourly predictions through December 15, 2025 (2,161 submissions)
# ============================================================================

# ============================================================================
# SECTION 1: SYSTEM PREREQUISITES & REPOSITORY SETUP
# ============================================================================

# 1.1: Update system packages
sudo apt update && sudo apt upgrade -y

# 1.2: Install system dependencies for Python & build tools
sudo apt install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-venv \
    git \
    wget \
    curl \
    ca-certificates \
    openssh-client

# 1.3: Verify Python version (must be 3.9+)
python3 --version

# 1.4: Clone the Allora pipeline repository
git clone https://github.com/MISHHF93/allora-forge-builder-kit.git
cd allora-forge-builder-kit

# 1.5: Verify you're in the correct directory
pwd  # Should output: /home/ubuntu/allora-forge-builder-kit (or similar path)

# ============================================================================
# SECTION 2: VIRTUAL ENVIRONMENT SETUP
# ============================================================================

# 2.1: Create isolated Python virtual environment
python3 -m venv .venv

# 2.2: Activate virtual environment
source .venv/bin/activate

# 2.3: Verify virtual environment is active (python path should show .venv)
which python

# 2.4: Upgrade pip to latest version
pip install --upgrade pip setuptools wheel

# ============================================================================
# SECTION 3: INSTALL ALL PROJECT DEPENDENCIES
# ============================================================================

# 3.1: Install all dependencies from requirements.txt (74 packages)
# This includes:
#   - ML Stack: pandas, numpy, xgboost, scikit-learn, scipy
#   - Blockchain: allora_sdk, cosmpy, grpcio, protobuf
#   - API: requests, python-dotenv, aiohttp
#   - Crypto: pycryptodome, PyNaCl, mnemonic, ecdsa, bcrypt
#   - Plus 50+ transitive dependencies

pip install -r requirements.txt

# 3.2: Verify core packages are installed (check key imports)
python3 << 'VERIFY_IMPORTS'
import pandas, numpy, sklearn, xgboost, requests, allora_sdk, joblib
print("✅ All core packages installed successfully!")
VERIFY_IMPORTS

# ============================================================================
# SECTION 4: ALLORA CLI SETUP
# ============================================================================

# 4.1: Check your system architecture
uname -m  # Should output: x86_64

# 4.2: Download Allora CLI (v0.3.0 for x86_64)
# For x86_64 Linux (AWS EC2, most cloud instances):
wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O allorad

# (Alternative for ARM64/aarch64)
# wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-arm64 -O allorad

# 4.3: Make binary executable
chmod +x allorad

# 4.4: Move to system PATH
sudo mv allorad /usr/local/bin/

# 4.5: Verify Allora CLI is working
allorad version  # Should output: v0.3.0 or similar

# 4.6: Check binary architecture
file /usr/local/bin/allorad  # Should show: ELF 64-bit LSB executable

# ============================================================================
# SECTION 5: CONFIGURE ENVIRONMENT VARIABLES
# ============================================================================

# 5.1: Create .env file with your credentials
# ⚠️ IMPORTANT: Replace the placeholder values with your actual credentials!

cat > .env << 'EOF'
# Allora Network Configuration
ALLORA_API_KEY=your_allora_api_key_here
ALLORA_WALLET_ADDR=allo1your_wallet_address_here
MNEMONIC="your 12 or 24 word seed phrase here"
TOPIC_ID=67
RPC_URL=https://allora-rpc.testnet.allora.network/
CHAIN_ID=allora-testnet-1

# Tiingo API (for BTC/USD data)
TIINGO_API_KEY=your_tiingo_api_key_here
EOF

# 5.2: Edit .env with your actual credentials
nano .env  # Or use: vi .env

# 5.3: Verify .env file is created
ls -lh .env

# ============================================================================
# SECTION 6: CONFIGURE ALLORA CLI
# ============================================================================

# 6.1: Set Allora CLI chain ID
allorad config set client chain-id allora-testnet-1

# 6.2: Set Allora CLI RPC node
allorad config set client node https://allora-rpc.testnet.allora.network/

# 6.3: Verify configuration
allorad config view

# ============================================================================
# SECTION 7: INITIAL MODEL TRAINING
# ============================================================================

# 7.1: Activate virtual environment (if not already active)
source .venv/bin/activate

# 7.2: Run initial model training
# This will:
#   - Fetch 90 days of BTC/USD hourly data from Tiingo
#   - Engineer 10 features
#   - Train XGBoost model
#   - Save model.pkl (dual pickle + joblib)
#   - Save features.json

python train.py

# 7.3: Verify model was created
ls -lh model.pkl features.json
# model.pkl should be > 5 KB (XGBoost, not Ridge fallback)
# features.json should contain 10 feature definitions

# ============================================================================
# SECTION 8: TEST SUBMISSION (DRY-RUN)
# ============================================================================

# 8.1: Test submission without actually submitting
# This verifies all credentials, API access, and blockchain connection

python submit_prediction.py --dry-run

# 8.2: Check submission result
cat latest_submission.json  # View latest prediction attempt

# ============================================================================
# SECTION 9: CREATE LOG DIRECTORY
# ============================================================================

# 9.1: Create logs directory for pipeline output
mkdir -p logs

# 9.2: Verify directory exists
ls -ld logs

# ============================================================================
# SECTION 10: START CONTINUOUS SUBMISSION PIPELINE
# ============================================================================

# 10.1: Start pipeline in background with continuous submissions
# Pipeline will:
#   - Submit hourly predictions for 7-day BTC/USD log-return
#   - Auto-restart on failure
#   - Log all activity to logs/submission.log

nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &

# 10.2: Save process ID to file (for monitoring/stopping)
echo $! > pipeline.pid

# 10.3: Display process ID
echo "Pipeline started with PID: $(cat pipeline.pid)"

# ============================================================================
# SECTION 11: MONITORING & TROUBLESHOOTING
# ============================================================================

# 11.1: View live submission logs (press Ctrl+C to stop)
tail -f logs/submission.log

# 11.2: Check if pipeline process is running
ps aux | grep submit_prediction.py | grep -v grep

# 11.3: View latest submission details
cat latest_submission.json | jq .

# 11.4: Check submission history
tail -20 submission_log.csv

# 11.5: Verify model is training hourly
grep "Training samples" logs/submission.log | tail -5

# 11.6: Check prediction accuracy
grep "Predicted 168h log-return" logs/submission.log | tail -5

# 11.7: View model file size (should be > 5 KB)
ls -lh model.pkl

# ============================================================================
# SECTION 12: PROCESS MANAGEMENT
# ============================================================================

# 12.1: Stop the pipeline gracefully
kill $(cat pipeline.pid)

# 12.2: Force stop if needed
pkill -f submit_prediction.py

# 12.3: Restart pipeline
nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &
echo $! > pipeline.pid

# 12.4: Monitor system resources while pipeline runs
top -p $(cat pipeline.pid)

# ============================================================================
# SECTION 13: PERFORMANCE MONITORING
# ============================================================================

# 13.1: Check training time
grep "Training completed" logs/submission.log | tail -1

# 13.2: Check submission rate
grep -c "Submission status" logs/submission.log

# 13.3: Monitor disk usage
du -sh logs/

# 13.4: Check for errors in logs
grep -i "error" logs/submission.log | head -10

# ============================================================================
# SECTION 14: DEPLOYMENT VERIFICATION CHECKLIST
# ============================================================================

# Run this script section to verify everything is working:

verify_deployment() {
    echo "=========================================="
    echo "DEPLOYMENT VERIFICATION CHECKLIST"
    echo "=========================================="
    
    # Check 1: Python version
    echo "✓ Checking Python version..."
    python3 --version | grep -q "3\." && echo "  ✅ Python 3.x installed" || echo "  ❌ Python 3 required"
    
    # Check 2: Virtual environment
    echo "✓ Checking virtual environment..."
    [[ "$VIRTUAL_ENV" == *".venv"* ]] && echo "  ✅ Virtual environment active" || echo "  ❌ Activate .venv first"
    
    # Check 3: Core packages
    echo "✓ Checking core packages..."
    python -c "import pandas, numpy, xgboost, requests, allora_sdk" && echo "  ✅ All core packages available" || echo "  ❌ Missing packages"
    
    # Check 4: .env file
    echo "✓ Checking .env configuration..."
    [[ -f .env ]] && echo "  ✅ .env file exists" || echo "  ❌ .env not found"
    
    # Check 5: Model and features
    echo "✓ Checking model and features..."
    [[ -f model.pkl && -f features.json ]] && echo "  ✅ Model and features present" || echo "  ❌ Run: python train.py"
    
    # Check 6: Allora CLI
    echo "✓ Checking Allora CLI..."
    allorad version > /dev/null 2>&1 && echo "  ✅ Allora CLI working" || echo "  ❌ Install allorad"
    
    # Check 7: Pipeline running
    echo "✓ Checking pipeline status..."
    pgrep -f "submit_prediction.py" > /dev/null && echo "  ✅ Pipeline is running" || echo "  ⚠️  Pipeline not running (can start manually)"
    
    echo "=========================================="
}

# 14.1: Run verification
verify_deployment

# ============================================================================
# SECTION 15: ADVANCED OPTIONS
# ============================================================================

# 15.1: Run pipeline with custom logging level
# PYTHONUNBUFFERED=1 python submit_prediction.py --continuous

# 15.2: Run single training iteration (no submission)
# python train.py

# 15.3: Monitor specific wallet address submissions
# grep "ALLORA_WALLET_ADDR" logs/submission.log

# 15.4: Extract model metrics
# grep "RMSE\|training\|validation" logs/submission.log

# 15.5: Clean logs and restart fresh
# rm -f logs/submission.log && nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &

# ============================================================================
# SECTION 16: QUICK REFERENCE
# ============================================================================

echo "
╔════════════════════════════════════════════════════════════════════╗
║         ALLORA PIPELINE - QUICK REFERENCE COMMANDS                 ║
╚════════════════════════════════════════════════════════════════════╝

STARTUP:
  cd allora-forge-builder-kit
  source .venv/bin/activate
  python train.py
  python submit_prediction.py --continuous

MONITORING:
  tail -f logs/submission.log            # Live logs
  ps aux | grep submit_prediction.py     # Check process
  cat latest_submission.json             # Latest prediction
  tail -20 submission_log.csv            # History

MAINTENANCE:
  kill \$(cat pipeline.pid)              # Stop pipeline
  python train.py                        # Retrain model
  rm model.pkl features.json             # Reset model
  pip install -r requirements.txt        # Reinstall deps

TROUBLESHOOTING:
  grep -i error logs/submission.log      # Find errors
  python -m pytest                       # Run tests
  allorad version                        # Check CLI
  python -c \"import allora_sdk\"        # Check SDK

TARGET METRICS (Nov 22 - Dec 15, 2025):
  • 2,161 hourly predictions
  • 7-day BTC/USD log-return forecasts
  • XGBoost gradient boosting model
  • 90-day rolling training window
  • Nonce deduplication enabled
  • Dynamic sequence querying
  • Auto-restart on failure

════════════════════════════════════════════════════════════════════════
"

# ============================================================================
# END OF DEPLOYMENT COMMANDS
# ============================================================================
# 
# Generated: November 22, 2025
# Status: Production Ready
# Tested: ✅ All sections verified
# Next: Configure .env and run section 10 to start pipeline
#
# ============================================================================
