# Allora Forge Builder Kit - Usage Guide

**Single Entry Point:** `train.py`

All functionality has been consolidated into `train.py`. No shell scripts required.

---

## 🚀 Quick Start

### Continuous Mode (Recommended)
Run hourly training and submission in a continuous loop:

```bash
python3 train.py --loop --submit
```

This will:
- ✅ Train XGBoost model every hour
- ✅ Submit predictions to blockchain
- ✅ Handle duplicate prevention automatically
- ✅ Log all activities
- ✅ Run indefinitely (until stopped with Ctrl+C)

---

## 📋 Common Commands

### 1. Continuous Submission (Production)
```bash
python3 train.py --loop --submit
```

### 2. Single Training + Submission
```bash
python3 train.py --submit
```

### 3. Training Only (No Submission)
```bash
python3 train.py
```

### 4. Backfill Historical Hours
```bash
python3 train.py --submit --start-utc "2025-11-01T00:00:00Z" --end-utc "2025-11-07T00:00:00Z"
```

### 5. Force Submission (Skip Guards)
```bash
python3 train.py --loop --submit --force-submit
```

---

## ⚙️ Command-Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--loop` | Run continuously (hourly) | `--loop` |
| `--submit` | Submit predictions to blockchain | `--submit` |
| `--force-submit` | Bypass duplicate/validation guards | `--force-submit` |
| `--start-utc` | Start datetime for backfill | `--start-utc "2025-11-01T00:00:00Z"` |
| `--end-utc` | End datetime for backfill | `--end-utc "2025-11-07T00:00:00Z"` |
| `--as-of-now` | Use current time for inference | `--as-of-now` |
| `--timeout` | Loop runtime limit (seconds, 0=infinite) | `--timeout 3600` |
| `--submit-timeout` | Submission timeout (seconds) | `--submit-timeout 30` |
| `--submit-retries` | Number of submission retries | `--submit-retries 3` |
| `--cadence` | Submission frequency | `--cadence 1h` |

---

## 🔍 Monitoring

### Check if Running
```bash
ps aux | grep "python3 train.py" | grep -v grep
```

### View Logs
```bash
tail -f data/artifacts/logs/submission_log.csv
```

### View Last 50 Submissions
```bash
tail -50 data/artifacts/logs/submission_log.csv | column -t -s ','
```

### Filter for Successful Submissions
```bash
grep ",true," data/artifacts/logs/submission_log.csv | tail -20
```

---

## 🛑 Stopping the Pipeline

### Graceful Stop (Ctrl+C in terminal)
If running in foreground, press `Ctrl+C`

### Kill Process
```bash
# Find PID
ps aux | grep "python3 train.py --loop" | grep -v grep | awk '{print $2}'

# Kill it (replace PID)
kill <PID>

# Force kill if needed
kill -9 <PID>
```

### Kill All Instances
```bash
pkill -9 -f "python.*train.py"
```

---

## 📊 Architecture

### Components

1. **train.py** (Single Entry Point)
   - Data fetching (Allora Market Data API)
   - Feature engineering
   - XGBoost model training
   - Blockchain submission (direct RPC via `_submit_with_client_xgb`)
   - Duplicate prevention
   - Logging and monitoring
   - Continuous loop mode

2. **simple_submit.py** (Helper Module)
   - Direct RPC submission using proto messages
   - Bypasses AlloraWorker SDK issues
   - Used internally by train.py

3. **config/pipeline.yaml** (Configuration)
   - Data settings
   - Schedule configuration
   - Topic parameters

---

## 🔧 Configuration

### Environment Variables
Required in `.env` file:

```bash
ALLORA_API_KEY=your_api_key_here
ALLORA_WALLET_ADDR=allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
ALLORA_WALLET_SEED_PHRASE=your 24-word seed phrase here
```

### Topic Configuration
- **Topic ID**: 67
- **Market**: BTC/USD
- **Prediction**: 7-day log-return
- **Competition**: Sep 16 - Dec 15, 2025
- **Cadence**: Hourly submissions

---

## 📈 Model Details

### XGBoost Parameters
```python
XGBRegressor(
    tree_method='hist',
    random_state=42,
    n_estimators=100,
    learning_rate=0.1,
    max_depth=6,
    min_child_weight=1,
    subsample=0.8,
    colsample_bytree=0.8
)
```

### Training Window
- **Training Data**: 14 days (336 hours)
- **Validation Data**: 7 days (168 hours)
- **Target Horizon**: 7 days (168 hours)
- **History Buffer**: 2 days (48 hours)

---

## 🚨 Troubleshooting

### "Another pipeline instance detected"
**Solution:** Only one instance can run at a time. Kill existing instance first:
```bash
pkill -f "python.*train.py"
```

### "Submission failed: already submitted"
**Solution:** This is expected behavior - duplicate prevention is working correctly.

### "No data available for inference hour"
**Solution:** Ensure the Allora Market Data API is accessible and returning data.

### gRPC proto errors
**Status:** Non-blocking. These are expected due to SDK/endpoint protobuf version mismatch. Submissions still work.

---

## 📝 Examples

### Run Continuous Pipeline in Background
```bash
nohup python3 train.py --loop --submit > logs/pipeline.log 2>&1 &
```

### Monitor Live
```bash
tail -f logs/pipeline.log | grep -E "Training|Prediction|Submitting|✅|❌"
```

### Check Success Rate
```bash
TOTAL=$(tail -100 data/artifacts/logs/submission_log.csv | grep -v "^timestamp" | wc -l)
SUCCESS=$(tail -100 data/artifacts/logs/submission_log.csv | grep ",true," | wc -l)
echo "Success rate: $SUCCESS/$TOTAL"
```

---

## 🎯 Production Deployment

### Recommended Command
```bash
python3 train.py --loop --submit
```

### With Logging
```bash
python3 train.py --loop --submit 2>&1 | tee -a logs/production.log
```

### In Docker/Container
```bash
docker run -d \
  --name allora-pipeline \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  your-image \
  python3 train.py --loop --submit
```

---

## ✅ Verification Checklist

Before running in production:

- [ ] Environment variables set in `.env`
- [ ] Wallet has sufficient balance
- [ ] Topic 67 is active and funded
- [ ] Network endpoints are accessible
- [ ] Submission log directory exists
- [ ] No other pipeline instances running

---

## 📞 Support

For issues or questions:
1. Check submission logs: `data/artifacts/logs/submission_log.csv`
2. Review error messages in console output
3. Verify wallet balance and topic status
4. Check competition dates (Sep 16 - Dec 15, 2025)

---

**Last Updated:** November 7, 2025  
**Version:** Consolidated Single-File Architecture
