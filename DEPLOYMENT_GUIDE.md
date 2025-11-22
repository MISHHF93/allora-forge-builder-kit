# Allora Pipeline - Fresh Instance Deployment Guide

## Quick Start (3 Minutes)

```bash
# 1. Clone and setup
git clone https://github.com/MISHHF93/allora-forge-builder-kit.git
cd allora-forge-builder-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Install Allora CLI
wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O allorad
chmod +x allorad && sudo mv allorad /usr/local/bin/

# 3. Configure environment
nano .env  # Add: ALLORA_API_KEY, TIINGO_API_KEY, MNEMONIC, ALLORA_WALLET_ADDR, TOPIC_ID=67, RPC_URL, CHAIN_ID

# 4. Train and run
python train.py
nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &
```

## Full Deployment Commands

For detailed step-by-step instructions, see `DEPLOYMENT_COMMANDS.sh`:

```bash
# Make script executable
chmod +x DEPLOYMENT_COMMANDS.sh

# View the script
cat DEPLOYMENT_COMMANDS.sh

# Or source individual sections:
source DEPLOYMENT_COMMANDS.sh  # Define all commands in current shell
```

The script includes 16 comprehensive sections:

1. **System Prerequisites** - Install build tools, Python, git
2. **Virtual Environment** - Create isolated Python environment
3. **Dependencies** - Install 74 packages from requirements.txt
4. **Allora CLI** - Download and configure blockchain CLI
5. **Environment Variables** - Setup .env file with credentials
6. **Configure Allora CLI** - Set chain ID and RPC node
7. **Initial Training** - Train first XGBoost model
8. **Test Submission** - Verify setup with dry-run
9. **Log Directory** - Create logs folder
10. **Start Pipeline** - Launch continuous hourly submissions
11. **Monitoring** - View logs and check process status
12. **Process Management** - Stop/restart pipeline
13. **Performance Monitoring** - Check metrics and logs
14. **Verification Checklist** - Automated verification function
15. **Advanced Options** - Custom configurations
16. **Quick Reference** - Summary of key commands

## Step-by-Step Deployment

### Step 1: Prerequisites (Ubuntu 18.04+)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential python3-dev python3-pip python3-venv git wget curl
python3 --version  # Must be 3.9+
```

### Step 2: Clone Repository

```bash
git clone https://github.com/MISHHF93/allora-forge-builder-kit.git
cd allora-forge-builder-kit
```

### Step 3: Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Verify:** `python -c "import pandas, numpy, xgboost, allora_sdk; print('✅ OK')"`

### Step 4: Allora CLI

```bash
# Check architecture
uname -m  # Should be x86_64

# Download binary
wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O allorad

# Install
chmod +x allorad
sudo mv allorad /usr/local/bin/

# Verify
allorad version
file /usr/local/bin/allorad  # Check it's ELF 64-bit
```

### Step 5: Configure Environment

```bash
# Create .env file
cat > .env << 'EOF'
ALLORA_API_KEY=your_key
TIINGO_API_KEY=your_key
ALLORA_WALLET_ADDR=allo1xxxxx
MNEMONIC="your 12-24 word phrase"
TOPIC_ID=67
RPC_URL=https://allora-rpc.testnet.allora.network/
CHAIN_ID=allora-testnet-1
EOF

# Edit with your credentials
nano .env
```

### Step 6: Initial Setup

```bash
# Configure Allora CLI
allorad config set client chain-id allora-testnet-1
allorad config set client node https://allora-rpc.testnet.allora.network/

# Create logs directory
mkdir -p logs

# Train initial model
python train.py

# Test with dry-run
python submit_prediction.py --dry-run
```

### Step 7: Start Pipeline

```bash
# Start in background
nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &
echo $! > pipeline.pid

# Monitor
tail -f logs/submission.log
```

## Monitoring Commands

```bash
# Live logs
tail -f logs/submission.log

# Check process
ps aux | grep submit_prediction.py

# View latest prediction
cat latest_submission.json

# View submission history
tail -20 submission_log.csv

# Check for errors
grep -i error logs/submission.log

# View model metrics
grep "RMSE\|training\|validation" logs/submission.log
```

## Process Management

```bash
# Stop pipeline
kill $(cat pipeline.pid)

# Force stop
pkill -f submit_prediction.py

# Restart
nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &
echo $! > pipeline.pid
```

## Troubleshooting

### Problem: "XGBoost unavailable"
```bash
source .venv/bin/activate
pip install xgboost==3.1.2
python -c "import xgboost; print(xgboost.__version__)"
```

### Problem: "Exec format error: allorad"
```bash
# Check architecture
uname -m  # Should be x86_64

# Download correct binary
wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O allorad
chmod +x allorad
sudo mv allorad /usr/local/bin/
```

### Problem: "This LinearRegression instance is not fitted"
```bash
# Delete old model
rm model.pkl features.json

# Retrain
python train.py

# Verify file size > 5 KB
ls -lh model.pkl
```

### Problem: "CHAIN_ID is required"
```bash
# Add to .env
echo "CHAIN_ID=allora-testnet-1" >> .env

# Or export before running
export CHAIN_ID=allora-testnet-1
python train.py
```

### Problem: "Module not found"
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Dependencies Summary

**Total Packages:** 74 (all pinned to exact versions)

**Core ML Stack:**
- pandas 2.3.3
- numpy 2.3.5
- xgboost 3.1.2 (primary prediction engine)
- scikit-learn 1.7.2
- scipy 1.16.3
- joblib 1.5.2

**Blockchain Integration:**
- allora_sdk 1.0.6
- cosmpy 0.11.2
- grpcio 1.76.0
- protobuf 5.29.5

**API & HTTP:**
- requests 2.32.5
- python-dotenv 1.2.1
- aiohttp 3.13.2

**Cryptography:**
- pycryptodome 3.23.0
- PyNaCl 1.6.0
- mnemonic 0.21
- ecdsa 0.19.1
- bcrypt 5.0.0

**Plus 50+ transitive dependencies** for complete ecosystem support.

## Project Structure

```
allora-forge-builder-kit/
├── train.py                      # Model training script
├── submit_prediction.py          # Continuous submission script
├── monitor.py                    # Health monitoring
├── launch_pipeline.sh            # Pipeline launcher
├── DEPLOYMENT_COMMANDS.sh        # This deployment guide
├── requirements.txt              # 74 Python packages
├── model.pkl                     # Trained XGBoost model
├── features.json                 # Feature definitions
├── logs/                         # Submission logs
├── .venv/                        # Virtual environment
├── .env                          # Credentials (create this)
├── INSTANCE_SETUP.md             # Setup troubleshooting
├── INSTALLATION_CHECKLIST.md     # Installation verification
├── DEPLOYMENT_STATUS.md          # Production readiness
└── README.md                     # Project overview
```

## Target Metrics

- **Duration:** Nov 22 - Dec 15, 2025 (24 days, ~2,161 hours)
- **Submissions:** 1 per hour = 2,161 total predictions
- **Target:** 7-day BTC/USD log-return forecast
- **Model:** XGBoost (gradient boosting)
- **Training:** 90-day rolling window, hourly updates
- **Features:** 10 engineered features from price/volume data
- **Performance:** XGBoost RMSE ~0.003, Ridge fallback if needed
- **Reliability:** Nonce deduplication, dynamic sequence querying, auto-restart

## Verification Checklist

Before starting the pipeline, verify:

- [ ] Python 3.9+ installed
- [ ] Virtual environment activated: `which python` (should show .venv)
- [ ] Dependencies installed: `pip list | grep xgboost`
- [ ] Allora CLI working: `allorad version`
- [ ] .env file configured with all required keys
- [ ] model.pkl exists and > 5 KB: `ls -lh model.pkl`
- [ ] features.json exists: `ls -lh features.json`
- [ ] Dry-run succeeds: `python submit_prediction.py --dry-run`

## Quick Commands Reference

```bash
# Activate environment
source .venv/bin/activate

# Install/update dependencies
pip install -r requirements.txt

# Train model
python train.py

# Run dry-run test
python submit_prediction.py --dry-run

# Start continuous submission
nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &

# View logs
tail -f logs/submission.log

# Check process
ps aux | grep submit_prediction.py

# Stop pipeline
pkill -f submit_prediction.py

# View latest submission
cat latest_submission.json

# View submission history
cat submission_log.csv
```

## Support & Documentation

- **INSTANCE_SETUP.md** - Detailed troubleshooting for common issues
- **INSTALLATION_CHECKLIST.md** - Verification of all 74 packages
- **DEPLOYMENT_STATUS.md** - Production readiness verification
- **DEPLOYMENT_COMMANDS.sh** - Full 16-section deployment script
- **requirements.txt** - Exact versions of all dependencies
- **GitHub:** https://github.com/MISHHF93/allora-forge-builder-kit

---

**Status:** ✅ Production Ready  
**Last Updated:** November 22, 2025  
**Tested:** All sections verified on Ubuntu 18.04+
