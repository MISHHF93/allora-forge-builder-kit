#!/bin/bash
# ============================================================================
# ALLORA FORGE - EC2 INSTANCE BOOTSTRAP
# Instance: i-0dc6b17115f9836fa (44.249.158.207)
# Topic 67: 7-Day BTC/USD Log-Return Prediction
# ============================================================================

set -e

echo "════════════════════════════════════════════════════════════════════════════"
echo "🚀 ALLORA FORGE - EC2 DEPLOYMENT (i-0dc6b17115f9836fa)"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# Update system packages
echo "📦 Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install essential packages
echo "📦 Installing essential packages..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    build-essential \
    curl \
    wget \
    jq

# Install allorad CLI if not present
if ! command -v allorad &> /dev/null; then
    echo "📦 Installing allorad CLI..."
    # Add Allora installation steps here based on official docs
    # For now, assume it's pre-installed or add manual install steps
    echo "⚠️  Please ensure allorad is installed manually if needed"
else
    echo "✅ allorad CLI already installed"
    allorad version
fi

# Clone repository if not exists
if [ ! -d "allora-forge-builder-kit" ]; then
    echo ""
    echo "📁 Cloning repository..."
    git clone https://github.com/MISHHF93/allora-forge-builder-kit.git
    cd allora-forge-builder-kit
else
    echo ""
    echo "✅ Repository already exists"
    cd allora-forge-builder-kit
    echo "📥 Pulling latest changes..."
    git pull origin main
fi

# Install Python dependencies
echo ""
echo "🐍 Installing Python dependencies..."
pip3 install -r requirements.txt

# Setup wallet
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "🔐 WALLET CONFIGURATION"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

if [ ! -f ".allora_key" ]; then
    echo "⚠️  Wallet mnemonic file not found!"
    echo ""
    echo "Please create .allora_key with your 24-word mnemonic:"
    echo "  nano .allora_key"
    echo ""
    echo "Paste your mnemonic, save (Ctrl+O, Enter, Ctrl+X), then run:"
    echo "  chmod 600 .allora_key"
    echo ""
    echo "After creating the file, re-run this script or continue manually."
    exit 1
else
    echo "✅ Wallet file found"
    chmod 600 .allora_key
fi

# Setup environment variables
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "🔧 ENVIRONMENT CONFIGURATION"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

if [ -z "$ALLORA_WALLET_ADDR" ]; then
    echo "⚠️  ALLORA_WALLET_ADDR not set!"
    echo ""
    echo "Getting wallet address from mnemonic..."
    WALLET_ADDR=$(python3 tools/print_wallet_address.py 2>/dev/null | tail -1)
    
    if [ ! -z "$WALLET_ADDR" ]; then
        echo "✅ Detected wallet address: $WALLET_ADDR"
        export ALLORA_WALLET_ADDR="$WALLET_ADDR"
        echo "export ALLORA_WALLET_ADDR=\"$WALLET_ADDR\"" >> ~/.bashrc
    else
        echo "❌ Could not derive wallet address"
        echo "Please set manually:"
        echo "  export ALLORA_WALLET_ADDR='allo1xxxxxxxxx6vma'"
        echo "  echo 'export ALLORA_WALLET_ADDR=\"allo1xxxxxxxxx6vma\"' >> ~/.bashrc"
        exit 1
    fi
else
    echo "✅ ALLORA_WALLET_ADDR already set: $ALLORA_WALLET_ADDR"
fi

if [ -z "$ALLORA_API_KEY" ]; then
    echo "⚠️  ALLORA_API_KEY not set (optional but recommended)"
    echo ""
    read -p "Enter your ALLORA_API_KEY (or press Enter to skip): " api_key
    if [ ! -z "$api_key" ]; then
        export ALLORA_API_KEY="$api_key"
        echo "export ALLORA_API_KEY=\"$api_key\"" >> ~/.bashrc
        echo "✅ API key configured"
    else
        echo "⏭️  Skipping API key (pipeline will work with CLI queries only)"
    fi
else
    echo "✅ ALLORA_API_KEY already set"
fi

# Verify configuration
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "🔍 VERIFICATION"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

echo "Python version:"
python3 --version

echo ""
echo "Wallet address:"
python3 tools/print_wallet_address.py

echo ""
echo "Testing train.py import:"
python3 -c "import train; print('✅ train.py imports successfully')"

# Show current configuration
echo ""
echo "════════════════════════════════════════════════════════════════════════════"
echo "📊 CURRENT CONFIGURATION"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Repository: $(pwd)"
echo "Branch: $(git branch --show-current)"
echo "Latest commits:"
git log --oneline -3
echo ""
echo "Environment:"
echo "  ALLORA_WALLET_ADDR: ${ALLORA_WALLET_ADDR:-'Not set'}"
echo "  ALLORA_API_KEY: ${ALLORA_API_KEY:+Set (hidden)}${ALLORA_API_KEY:-'Not set'}"
echo ""

# Ask to start worker
echo "════════════════════════════════════════════════════════════════════════════"
echo "🚀 START PRODUCTION WORKER?"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""
read -p "Start worker now? (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo ""
    echo "Starting worker..."
    ./start_worker.sh
    
    echo ""
    echo "════════════════════════════════════════════════════════════════════════════"
    echo "✅ DEPLOYMENT COMPLETE"
    echo "════════════════════════════════════════════════════════════════════════════"
    echo ""
    echo "Worker is now running. Monitor with:"
    echo "  ./monitor.sh              # Status snapshot"
    echo "  ./watch_live.sh           # Live dashboard"
    echo "  tail -f pipeline_run.log  # Follow logs"
    echo ""
    echo "Worker PID: $(cat pipeline.pid 2>/dev/null || echo 'See pipeline.pid')"
    echo ""
else
    echo ""
    echo "Skipped worker start. You can start manually with:"
    echo "  ./start_worker.sh"
    echo ""
fi

echo "════════════════════════════════════════════════════════════════════════════"
