# Allora Competition - Quick Start Guide

## 🚀 Start Submitting (60 seconds)

```bash
cd /workspaces/allora-forge-builder-kit

# Set your mnemonic
export MNEMONIC="tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random"

# Run once to test
python competition_submission.py --once

# Or run continuously (every hour)
python competition_submission.py
```

## 📊 Competition Info

| Field | Value |
|-------|-------|
| **Topic** | 67 - 7 Day BTC/USD Log-Return |
| **Network** | Allora Testnet (allora-testnet-1) |
| **Update Frequency** | Every Hour |
| **Active Until** | December 15, 2025 |
| **Your Wallet** | allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma |
| **Balance** | 251+ Billion ALLO ✅ |

## ✅ Status Checks

```bash
# Check wallet
python setup_wallet.py --info

# Check balance
python setup_wallet.py --balance

# Check model metrics
cat data/artifacts/metrics.json

# View submission history
tail -10 competition_submissions.csv

# View live logs
tail -f competition_submissions.log
```

## 📁 Key Files

| File | Purpose |
|------|---------|
| `competition_submission.py` | Main pipeline |
| `setup_wallet.py` | Wallet management |
| `competition_submissions.csv` | Submission history |
| `.env` | Configuration |

## 🔧 Common Tasks

### Run Once (Test)
```bash
export MNEMONIC="..."
python competition_submission.py --once
```

### Run Every Hour (Production)
```bash
export MNEMONIC="..."
python competition_submission.py
```

### Run in Background
```bash
nohup python competition_submission.py > competition.log 2>&1 &
tail -f competition.log
```

### Monitor Submissions
```bash
# Live view
tail -f competition_submissions.log

# History
cat competition_submissions.csv

# Last 5 submissions
tail -5 competition_submissions.csv
```

## 📈 Model Performance

```
Algorithm: XGBoost
R² Score: 0.9594
MAE: 0.442
MSE: 0.494
```

## 🆘 Troubleshooting

### "No unfulfilled nonces"
✅ Normal - Topic has no pending requests. Pipeline continues.

### "Account not found"
```bash
python setup_wallet.py --faucet
```

### "Wallet not found"
```bash
python setup_wallet.py --create
```

## 📚 Full Documentation

- `PRODUCTION_READY_COMPETITION.md` - Complete status
- `COMPETITION_SUBMISSION_GUIDE.md` - Detailed guide
- `WALLET_SETUP.md` - Wallet configuration
- `ACCOUNT_NOT_FOUND_FIX.md` - Troubleshooting

## 🎯 Next Steps

1. Run pipeline: `python competition_submission.py`
2. Monitor logs: `tail -f competition_submissions.log`
3. Check leaderboard: https://dashboard.allora.network
4. View your submissions: Look for wallet `allo1cxvw0...`

---

**Status**: ✅ Production Ready 🚀
