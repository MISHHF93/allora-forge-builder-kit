#!/bin/bash
# ============================================================================
# ALLORA FORGE - AWS QUICK START
# Topic 67: 7-Day BTC/USD Log-Return Prediction
# Competition: Sep 16 - Dec 15, 2025 (Hourly Submissions)
# ============================================================================

set -e  # Exit on error

echo "════════════════════════════════════════════════════════════════════════════"
echo "🚀 ALLORA FORGE - AWS DEPLOYMENT"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# 1. Check if already in repo
if [ ! -f "train.py" ]; then
    echo "📁 Cloning repository..."
    cd ~
    git clone https://github.com/MISHHF93/allora-forge-builder-kit.git
    cd allora-forge-builder-kit
else
    echo "✅ Already in repository directory"
fi

# 2. Verify Python
echo ""
echo "🐍 Checking Python version..."
python3 --version || { echo "❌ Python 3 not found. Install it first."; exit 1; }

# 3. Install dependencies
echo ""
echo "📦 Installing dependencies..."
pip install -r requirements.txt --quiet

# 4. Check for wallet
echo ""
if [ ! -f ".allora_key" ]; then
    echo "⚠️  Wallet mnemonic not found!"
    echo ""
    echo "Please create .allora_key file with your 24-word mnemonic:"
    echo "  echo 'word1 word2 ... word24' > .allora_key"
    echo "  chmod 600 .allora_key"
    echo ""
    exit 1
else
    echo "✅ Wallet file found"
    chmod 600 .allora_key
fi

# 5. Check environment variables
echo ""
if [ -z "$ALLORA_WALLET_ADDR" ]; then
    echo "⚠️  ALLORA_WALLET_ADDR not set!"
    echo ""
    echo "Please set your wallet address:"
    echo "  export ALLORA_WALLET_ADDR='allo1xxxxxxxxx6vma'"
    echo "  echo 'export ALLORA_WALLET_ADDR=\"allo1xxxxxxxxx6vma\"' >> ~/.bashrc"
    echo ""
    exit 1
else
    echo "✅ ALLORA_WALLET_ADDR set: $ALLORA_WALLET_ADDR"
fi

if [ -z "$ALLORA_API_KEY" ]; then
    echo "⚠️  ALLORA_API_KEY not set (optional but recommended)"
    echo "  export ALLORA_API_KEY='your_api_key'"
else
    echo "✅ ALLORA_API_KEY set"
fi

# 6. Verify configuration
echo ""
echo "🔍 Verifying configuration..."
python3 -c "import train; print('✅ train.py imports successfully')" || exit 1

echo ""
echo "📋 Wallet address from mnemonic:"
python3 tools/print_wallet_address.py || exit 1

# 7. Test run (optional)
echo ""
read -p "🧪 Run test iteration before starting worker? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Running test iteration..."
    python3 train.py --once --submit
fi

# 8. Start worker
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "🚀 STARTING PRODUCTION WORKER"
echo "════════════════════════════════════════════════════════════════════════════"
./start_worker.sh

# 9. Show next steps
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT COMPLETE"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "📊 Monitoring Commands:"
echo "  ./monitor.sh              # Quick status snapshot"
echo "  ./watch_live.sh           # Live monitoring dashboard"
echo "  tail -f pipeline_run.log  # Follow logs"
echo ""
echo "📁 Key Files:"
echo "  pipeline.pid              # Worker process ID"
echo "  pipeline_run.log          # Execution logs"
echo "  submission_log.csv        # Submission history"
echo ""
echo "🔄 Worker will:"
echo "  • Train models every hour with 28-day BTC/USD data"
echo "  • Submit predictions at HH:00:00 UTC when window opens"
echo "  • Run autonomously through December 15, 2025"
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
