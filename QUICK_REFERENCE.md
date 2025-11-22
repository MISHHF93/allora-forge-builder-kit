# ALLORA PIPELINE - INSTANT DEPLOYMENT REFERENCE

## 3-Minute Quick Start

```bash
# 1. Setup (1 minute)
git clone https://github.com/MISHHF93/allora-forge-builder-kit.git && cd allora-forge-builder-kit
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Allora CLI (1 minute)
wget https://github.com/allora-network/allora-chain/releases/download/v0.3.0/allorad-linux-amd64 -O allorad
chmod +x allorad && sudo mv allorad /usr/local/bin/

# 3. Configure & Run (1 minute)
nano .env  # Set: ALLORA_API_KEY, TIINGO_API_KEY, MNEMONIC, ALLORA_WALLET_ADDR, TOPIC_ID=67, RPC_URL, CHAIN_ID
python train.py
nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 & echo $! > pipeline.pid
tail -f logs/submission.log
```

---

## 5 Essential Commands

| Command | Purpose |
|---------|---------|
| `source .venv/bin/activate` | Activate virtual environment |
| `python train.py` | Train XGBoost model (90-day window) |
| `python submit_prediction.py --continuous` | Start hourly predictions |
| `tail -f logs/submission.log` | Monitor live submissions |
| `kill $(cat pipeline.pid)` | Stop pipeline gracefully |

---

## Configuration (.env File)

```bash
ALLORA_API_KEY=your_api_key
TIINGO_API_KEY=your_tiingo_key
ALLORA_WALLET_ADDR=allo1your_address
MNEMONIC="your seed phrase (12-24 words)"
TOPIC_ID=67
RPC_URL=https://allora-rpc.testnet.allora.network/
CHAIN_ID=allora-testnet-1
```

---

## Key Files

| File | Size | Purpose |
|------|------|---------|
| `train.py` | 17 KB | Model training (XGBoost) |
| `submit_prediction.py` | 17 KB | Continuous submission loop |
| `requirements.txt` | 1.3 KB | 74 Python packages |
| `model.pkl` | 750 KB | Trained model (after first train.py) |
| `features.json` | 134 B | 10 feature definitions |
| `logs/submission.log` | Varies | Live submission activity |

---

## Monitoring

```bash
tail -f logs/submission.log           # Live logs
ps aux | grep submit_prediction.py    # Check process running
cat latest_submission.json            # Latest prediction
tail -20 submission_log.csv           # Submission history
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Python 3 not found | `sudo apt install python3-venv` |
| XGBoost error | `pip install xgboost==3.1.2` |
| allorad exec format | Re-download for correct arch: `uname -m` |
| CHAIN_ID missing | Add to .env: `CHAIN_ID=allora-testnet-1` |
| Model not fitted | Delete `model.pkl` and run `python train.py` |
| Dependency missing | Run `pip install -r requirements.txt` |

---

## Deployment Checklist

```bash
# Run this to verify everything:
python3 -c "
import pandas, numpy, sklearn, xgboost, requests, allora_sdk
print('✅ All imports OK')
"
[ -f .env ] && echo "✅ .env exists" || echo "❌ Create .env"
[ -f model.pkl ] && echo "✅ Model exists" || echo "⚠️  Run: python train.py"
allorad version && echo "✅ Allora CLI OK" || echo "❌ Install allorad"
pgrep -f submit_prediction.py > /dev/null && echo "✅ Pipeline running" || echo "⚠️  Start pipeline"
```

---

## System Requirements

- OS: Ubuntu 18.04+ (or any Linux with Python 3.9+)
- Python: 3.9, 3.10, 3.11, 3.12 (tested on 3.12.1)
- Disk: 1 GB free (including 750 MB for venv)
- RAM: 2 GB minimum (4+ GB recommended)
- Network: Active internet (for Tiingo API & Allora RPC)

---

## Execution Timeline

| Phase | Duration | Action |
|-------|----------|--------|
| Setup | 5 min | Clone, venv, pip install, allorad |
| Initial Train | 2-5 sec | First model training |
| Test Run | 30 sec | Dry-run submission |
| Production | 90 days | 2,161 hourly predictions |
| Timeline | Nov 22 - Dec 15 | Autonomous execution |

---

## Expected Output

After `python train.py`:
```
Fetched 21,600 hourly BTC/USD candles
Generated 10 features
Training samples: 21,432
Trained XGBoost model
RMSE: 0.003449
Model saved: model.pkl (750 KB)
Features saved: features.json
```

After `python submit_prediction.py --continuous`:
```
Hourly log:
- Fetch latest 168h data ✅
- Generate 10 features ✅
- Predict 7-day log-return ✅
- Get unfulfilled nonce ✅
- Query account sequence ✅
- Submit prediction ✅
- Save latest_submission.json ✅
- Wait 3600s for next submission
```

---

## Dependency Overview

**Core ML:** pandas, numpy, xgboost, scikit-learn, scipy, joblib  
**Blockchain:** allora_sdk, cosmpy, grpcio, protobuf  
**API:** requests, python-dotenv, aiohttp  
**Crypto:** pycryptodome, PyNaCl, mnemonic, ecdsa, bcrypt  
**Plus 50+ supporting packages** (matplotlib, lightgbm, etc.)

**Total:** 74 packages, all pinned to exact versions in `requirements.txt`

---

## Detailed Documentation

- **DEPLOYMENT_COMMANDS.sh** - Full 16-section deployment script with all commands
- **DEPLOYMENT_GUIDE.md** - Step-by-step guide, troubleshooting, commands
- **INSTANCE_SETUP.md** - Setup guide with error fixes
- **INSTALLATION_CHECKLIST.md** - Verification of all 74 packages installed
- **DEPLOYMENT_STATUS.md** - Production readiness verification
- **README.md** - Project overview and architecture

---

## Need Help?

1. **Check logs:** `tail -100 logs/submission.log`
2. **Read docs:** See files above (in order listed)
3. **Verify setup:** Run checklist commands above
4. **GitHub:** https://github.com/MISHHF93/allora-forge-builder-kit

---

**Status:** ✅ Production Ready | **Last Updated:** Nov 22, 2025 | **Tested:** All sections verified
