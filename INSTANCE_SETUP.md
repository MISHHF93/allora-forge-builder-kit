# Allora Pipeline - Instance Setup & Troubleshooting Guide

## Quick Start (Fresh Ubuntu Instance)

```bash
# 1. Clone repository
git clone https://github.com/MISHHF93/allora-forge-builder-kit.git
cd allora-forge-builder-kit

# 2. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Verify all dependencies installed successfully
python -c "
import xgboost, pandas, numpy, scikit_learn, requests, allora_sdk
print('✅ All core dependencies verified')
"

# 4. Install Allora CLI (CORRECT WAY)
# Download the correct binary for your architecture
# Check: uname -m (should be x86_64 for AWS instances)

# For x86_64 Linux:
wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O allorad
chmod +x allorad
sudo mv allorad /usr/local/bin/  # or ~/.local/bin/

# Verify installation
allorad version

# 5. Configure Allora CLI
allorad config set client chain-id allora-testnet-1
allorad config set client node https://allora-rpc.testnet.allora.network/

# 6. Create .env file with your credentials
cat > .env << EOF
ALLORA_API_KEY=your_key
TIINGO_API_KEY=your_key
ALLORA_WALLET_ADDR=allo1xxxxx
MNEMONIC="your 12-24 word phrase"
TOPIC_ID=67
RPC_URL=https://allora-rpc.testnet.allora.network/
CHAIN_ID=allora-testnet-1
EOF

# 7. Test training
python train.py

# 8. Verify model.pkl was created
ls -lh model.pkl features.json

# 9. Test submission (dry-run)
python submit_prediction.py --dry-run

# 10. Run continuous pipeline
nohup .venv/bin/python submit_prediction.py --continuous > logs/submission.log 2>&1 &
echo $! > pipeline.pid
tail -f logs/submission.log
```

## Common Issues & Fixes

### Issue 1: "XGBoost unavailable; using Ridge regression fallback"
**Cause**: XGBoost not installed or import failed
**Fix**:
```bash
pip install xgboost==2.0.3
python -c "import xgboost; print(f'✅ XGBoost {xgboost.__version__} installed')"
```

### Issue 2: "Exec format error: '/path/to/allorad'"
**Cause**: Binary downloaded for wrong architecture or corrupted
**Fix**:
```bash
# Check your architecture
uname -m  # Should output: x86_64

# Remove old binary
rm ~/.local/bin/allorad

# Re-download correct version
wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O ~/.local/bin/allorad
chmod +x ~/.local/bin/allorad

# Verify
file ~/.local/bin/allorad  # Should show: ELF 64-bit LSB executable, x86-64
allorad version
```

### Issue 3: "This LinearRegression instance is not fitted yet"
**Cause**: submit_prediction.py loaded an old/unfitted Ridge model from model.pkl
**Fix**:
```bash
# Delete old model
rm model.pkl features.json

# Retrain
python train.py

# Verify new model exists and is larger
ls -lh model.pkl
# Should be > 5 KB (XGBoost) not < 1 KB (Ridge)
```

### Issue 4: "CHAIN_ID is required" (SDK initialization)
**Cause**: Environment variable not set
**Fix**:
```bash
# Add to .env
echo "CHAIN_ID=allora-testnet-1" >> .env

# Or export before running
export CHAIN_ID=allora-testnet-1
python train.py
```

### Issue 5: Model training uses Ridge instead of XGBoost
**Cause**: XGBoost import failed silently
**Debug**:
```bash
python -c "
try:
    import xgboost as xgb
    print(f'✅ XGBoost {xgb.__version__} available')
except Exception as e:
    print(f'❌ XGBoost import failed: {e}')
"
```

## Monitoring the Pipeline

```bash
# View live logs
tail -f logs/submission.log

# Check if processes are running
ps aux | grep submit_prediction.py
ps aux | grep python

# View model file
ls -lh model.pkl
file model.pkl

# View submission history
tail -20 submission_log.csv
cat latest_submission.json

# Kill pipeline if needed
pkill -f submit_prediction.py
```

## Performance Check

```bash
# Check if model is training hourly
grep "Training samples" logs/submission.log | tail -5

# Check if predictions are being made
grep "Predicted 168h log-return" logs/submission.log | tail -5

# Check submission attempts
grep "Submission status" logs/submission.log | tail -5
```

## Environment Checklist

Before running the pipeline, verify:

- [ ] Python 3.9+ installed: `python --version`
- [ ] Virtual environment activated: `which python` (should show .venv)
- [ ] Dependencies installed: `pip list | grep -E "xgboost|pandas|numpy|allora-sdk"`
- [ ] Core imports work: `python -c "import xgboost, pandas, numpy, requests, allora_sdk; print('✅ All imports verified')"`
- [ ] XGBoost available: `python -c "import xgboost; print(xgboost.__version__)"`
- [ ] Allora CLI installed: `allorad version`
- [ ] Allora CLI is correct architecture: `file $(which allorad)`
- [ ] .env file exists with all keys: `cat .env`
- [ ] CHAIN_ID in environment: `echo $CHAIN_ID`
- [ ] model.pkl exists after training: `ls -lh model.pkl`
- [ ] model.pkl is > 5 KB (XGBoost, not Ridge): `ls -lh model.pkl`

## Requirements.txt

The `requirements.txt` contains all 81 dependencies including:

**Core ML Stack:**
- xgboost==3.1.2 (gradient boosting for predictions)
- scikit-learn==1.7.2 (feature scaling, model utilities)
- pandas==2.3.3 (data manipulation)
- numpy==2.3.5 (numerical computations)
- scipy==1.16.3 (statistical functions)

**API & HTTP:**
- requests==2.32.5 (Tiingo API calls)
- python-dotenv==1.2.1 (environment variables)
- joblib==1.5.2 (model serialization)

**Blockchain & Allora SDK:**
- allora_sdk==1.0.6 (prediction submission)
- cosmpy==0.11.2 (blockchain integration)
- grpcio==1.76.0, grpcio-tools==1.76.0 (protocol buffers)
- protobuf==5.29.5 (message serialization)

**Supporting Libraries:**
- matplotlib==3.10.7, lightgbm==4.6.0, pycryptodome==3.23.0, mnemonic==0.21, PyNaCl==1.6.0 (crypto & visualization)

To install all dependencies on a fresh Ubuntu instance:
```bash
pip install -r requirements.txt
```

## Running on Instance

```bash
# After setup, start the pipeline
cd ~/allora-forge-builder-kit
source .venv/bin/activate
nohup .venv/bin/python submit_prediction.py --continuous > logs/submission.log 2>&1 &
echo "Pipeline started. Check logs/submission.log"
```

The pipeline will run hourly, training on 90 days of data and submitting predictions for the 7-day log-return challenge until December 15, 2025.
