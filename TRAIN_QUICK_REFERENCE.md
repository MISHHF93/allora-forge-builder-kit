# train.py Quick Reference Card

## 🚀 Most Common Commands

```bash
# Single submission with force flag
python3 train.py --submit --force-submit

# Continuous operation (production)
python3 train.py --loop --submit --force-submit --submit-timeout 300

# Refresh scores/rewards (after 24-48 hours)
python3 train.py --refresh-scores --refresh-tail 20

# Quick status check
python3 train.py --inspect-log --inspect-tail 3

# Show wallet address
python3 train.py --print-wallet
```

## 📊 Submission Commands

| Command | Description |
|---------|-------------|
| `--submit` | Submit prediction after training |
| `--force-submit` | Bypass quality control filters |
| `--submit-timeout 300` | Increase timeout to 5 minutes |
| `--submit-retries 5` | Retry failed submissions 5 times |

## 🔄 Loop Commands

| Command | Description |
|---------|-------------|
| `--loop` | Continuous operation (1h cadence) |
| `--cadence 30m` | Run every 30 minutes |
| `--timeout 3600` | Stop after 1 hour |
| `--once` | Force single iteration |

## 🛠️ Utility Commands

| Command | Description |
|---------|-------------|
| `--refresh-scores` | Update score/reward from blockchain |
| `--refresh-tail 20` | Refresh last 20 submissions |
| `--print-wallet` | Show SDK wallet address |
| `--inspect-log` | Validate CSV schema & show rows |
| `--inspect-tail 5` | Show last 5 log entries |

## 📅 Time Control

| Command | Description |
|---------|-------------|
| `--as-of-now` | Use current UTC time |
| `--as-of "2025-11-16T12:00:00Z"` | Use specific timestamp |
| `--start-utc "2025-11-01T00:00:00Z"` | Training data start |
| `--end-utc "2025-11-16T00:00:00Z"` | Training data end |
| `--from-month "2025-01"` | Start from specific month |

## 🔍 Diagnostic Commands

```bash
# Full system check
python3 train.py --inspect-log --inspect-tail 10

# Verify wallet configuration
python3 train.py --print-wallet

# Check recent submissions
python3 train.py --inspect-log --inspect-tail 5

# Manual score refresh
python3 train.py --refresh-scores --refresh-tail 50
```

## 🏭 Production Setup

### EC2 Background Operation
```bash
# Start persistent background process
nohup python3 train.py --loop --submit --force-submit --submit-timeout 300 > pipeline.log 2>&1 &

# Save process ID
echo $! > train.pid

# Check status
tail -f pipeline.log

# Stop process
kill $(cat train.pid)
```

### Docker/Container
```bash
# Foreground (for container logs)
python3 train.py --loop --submit --force-submit --submit-timeout 300

# With timeout (exit after 24 hours)
python3 train.py --loop --submit --force-submit --timeout 86400
```

## ⚡ Common Workflows

### First Time Setup
```bash
# 1. Check wallet
python3 train.py --print-wallet

# 2. Test single submission
python3 train.py --submit --force-submit --once

# 3. Verify logged
python3 train.py --inspect-log --inspect-tail 1

# 4. Start continuous operation
python3 train.py --loop --submit --force-submit
```

### Daily Monitoring
```bash
# Check recent submissions
python3 train.py --inspect-log --inspect-tail 24

# Refresh scores (after 24-48h)
python3 train.py --refresh-scores --refresh-tail 50

# Verify wallet balance
python3 train.py --print-wallet
```

### Troubleshooting
```bash
# Force single submission
python3 train.py --submit --force-submit --once

# Increase timeout
python3 train.py --submit --force-submit --submit-timeout 600

# Check submission log
python3 train.py --inspect-log --inspect-tail 10

# Manual score refresh
python3 train.py --refresh-scores --refresh-tail 100
```

## 🔐 Environment Variables Required

```bash
ALLORA_API_KEY=your_api_key_here
ALLORA_WALLET_ADDR=allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
ALLORA_RPC_URL=https://testnet-rpc.lavenderfive.com:443/allora/
```

## 📁 Output Files

| File | Description |
|------|-------------|
| `submission_log.csv` | All submissions with nonce/tx_hash/scores |
| `pipeline_run.log` | Timestamped pipeline execution logs |
| `pipeline.log` | Background process output (nohup) |
| `data/artifacts/live_forecast.json` | Latest prediction |
| `data/artifacts/predictions.json` | Training predictions |
| `data/artifacts/model.joblib` | Trained XGBoost model |
| `data/artifacts/metrics.json` | Model performance metrics |
| `data/artifacts/logs/*.json` | Lifecycle snapshots |

## ⏱️ Expected Timing

- **Training**: 30-60 seconds
- **Submission**: 5-30 seconds
- **Score refresh**: 10-20 seconds per tx
- **Score availability**: 24-48 hours after submission
- **Loop cadence**: 1 hour (default)

## 🎯 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration/API error |
| 2 | SDK/wallet error |
| Other | Submission or training failure |

## 📞 Quick Help

```bash
# Show all options
python3 train.py --help

# Version and environment info
python3 -c "import sys; print(f'Python {sys.version}')"

# Check dependencies
python3 -c "import allora_sdk; print(f'SDK version: {allora_sdk.__version__}')"
```

---

**Pro Tip**: Always use `--force-submit` when you want to guarantee submission regardless of quality filters. The high-loss filter at line 4081 is bypassed by this flag.

**Note**: Scores and rewards take 24-48 hours to populate in `submission_log.csv` after on-chain computation completes. Use `--refresh-scores` to backfill when data becomes available.
