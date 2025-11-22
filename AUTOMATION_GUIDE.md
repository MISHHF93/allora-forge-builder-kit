# Allora Competition Automation & Productionization Guide

## Overview

This guide covers the complete automation setup for the Allora competition submission system using cron-based scheduling, log rotation, health checks, and prediction validation.

---

## 📋 Components

### 1. **competition_submission.py** - Entry Point
A wrapper script that handles:
- Environment validation
- Prediction validation before submission
- Cron-compatible execution (--once mode)
- Health check reporting
- Error handling and logging

**Usage:**
```bash
# Validate environment only
python3 competition_submission.py --validate-only

# Run single submission cycle (for cron)
python3 competition_submission.py --once

# Run continuous loop (not recommended for cron)
python3 competition_submission.py --loop

# Check submission health
python3 competition_submission.py --check-health

# Training only (no submission)
python3 competition_submission.py --once --no-submit
```

### 2. **logs/rotate_logs.sh** - Log Rotation
Rotates and compresses logs every hour to prevent unbounded disk usage.

**Features:**
- Copies active log to timestamped archive
- Compresses with gzip
- Clears original log file
- Auto-deletes logs older than 30 days

**Cron entry:**
```bash
5 * * * * /workspaces/allora-forge-builder-kit/logs/rotate_logs.sh >> /workspaces/allora-forge-builder-kit/logs/pipeline_run.log 2>&1
```

### 3. **logs/healthcheck.sh** - Health Monitoring
Checks recent submission attempts and logs status.

**Checks:**
- Recent submission activity (last 30 min)
- Successful submissions
- Skipped submissions (still operational)
- Failed submissions

**Cron entry:**
```bash
10 * * * * /workspaces/allora-forge-builder-kit/logs/healthcheck.sh
```

### 4. **setup_cron.sh** - Cron Configuration Helper
Displays setup instructions and makes scripts executable.

**Run once:**
```bash
chmod +x setup_cron.sh
./setup_cron.sh
```

---

## 🚀 Quick Setup

### Step 1: Verify Virtual Environment
```bash
cd /workspaces/allora-forge-builder-kit
ls -la .venv/bin/python
```

### Step 2: Test Scripts
```bash
# Test competition_submission.py
python3 competition_submission.py --validate-only

# Test log rotation
./logs/rotate_logs.sh

# Test healthcheck
./logs/healthcheck.sh
```

### Step 3: Configure Crontab
```bash
crontab -e
```

Add these lines (all times UTC):
```bash
# Allora competition submissions - every hour at HH:00:00 UTC
0 * * * * cd /workspaces/allora-forge-builder-kit && ./.venv/bin/python competition_submission.py --once >> logs/pipeline_run.log 2>&1

# Log rotation - every hour at HH:05:00 UTC
5 * * * * /workspaces/allora-forge-builder-kit/logs/rotate_logs.sh >> /workspaces/allora-forge-builder-kit/logs/pipeline_run.log 2>&1

# Health check - every hour at HH:10:00 UTC
10 * * * * /workspaces/allora-forge-builder-kit/logs/healthcheck.sh
```

### Step 4: Verify Cron Setup
```bash
crontab -l  # View installed cron jobs
```

---

## 🔍 Prediction Validation

The pipeline now includes automatic prediction validation before submission.

### Validation Checks

1. **Type Check**: Predictions must be list, numpy array, or pandas Series
2. **NaN Check**: No missing values allowed
3. **Infinity Check**: No infinite values allowed
4. **Range Check**: Warns if outside [-10, 10] (typical BTC log-return range)

### Example Log Output
```
✅ Predictions valid: shape=(100,), mean=0.000123, std=0.045234, min=-0.234, max=0.189
```

### How It Works

In `train.py`, before submission:
```python
try:
    validate_predictions(y_pred_series)
except ValueError as e:
    logging.warning(f"Prediction validation warning: {e} - continuing with submission attempt")
```

The validation is **non-blocking** - warnings are logged but submission continues.

---

## 📊 Log Management

### Log File Structure
```
/workspaces/allora-forge-builder-kit/
├── logs/
│   ├── pipeline_run.log              # Active log (rotated hourly)
│   ├── pipeline_20251122_001000.log.gz  # Compressed archive
│   └── healthcheck_status.log        # Health check history
├── competition_submissions.csv       # Submission log (by train.py)
└── submission_log.csv               # Submission history
```

### Log Rotation Schedule
- **00:05** - Rotate logs
- **00:10** - Run health check
- **01:00** - Next submission + rotation cycle

### Viewing Logs
```bash
# Current active log
tail -f logs/pipeline_run.log

# Recent submissions
tail -20 submission_log.csv

# Health check history
tail -20 logs/healthcheck_status.log

# Archived logs
ls -lh logs/*.log.gz
gunzip logs/pipeline_*.log.gz  # Decompress if needed
```

---

## ⏰ Cron Schedule Details

| Time | Job | Purpose |
|------|-----|---------|
| HH:00:00 UTC | competition_submission.py | Train + Submit |
| HH:05:00 UTC | rotate_logs.sh | Rotate logs |
| HH:10:00 UTC | healthcheck.sh | Check health |

**All times in UTC. Competition runs Sep 16 - Dec 15, 2025.**

---

## 🐛 Troubleshooting

### Check if Cron is Running
```bash
# View cron log
grep CRON /var/log/syslog | tail -20

# Check if cron daemon is running
pgrep cron
```

### Manual Test Execution
```bash
# Simulate cron environment
cd /workspaces/allora-forge-builder-kit
/workspaces/allora-forge-builder-kit/.venv/bin/python competition_submission.py --once
```

### Check Virtual Environment
```bash
which python3
ls -la /workspaces/allora-forge-builder-kit/.venv/bin/python
/workspaces/allora-forge-builder-kit/.venv/bin/python --version
```

### Verify Environment Variables
```bash
echo $ALLORA_API_KEY
echo $ALLORA_WALLET_ADDR
cat /workspaces/allora-forge-builder-kit/.env
```

### Check Disk Space
```bash
df -h /workspaces/
du -sh logs/
```

---

## 📈 Monitoring

### Real-Time Submission Tracking
```bash
# Watch for successful submissions
watch -n 5 'tail -5 submission_log.csv && echo "---" && tail -5 logs/healthcheck_status.log'
```

### Count Hourly Submissions
```bash
# Count submissions per day
grep "2025-11-22" submission_log.csv | wc -l

# See submission statuses
cut -d',' -f7 submission_log.csv | sort | uniq -c
```

### Check Last Submission
```bash
# Get timestamp and status of last attempt
tail -2 submission_log.csv | head -1
```

---

## 🔐 Security Considerations

1. **File Permissions**
   ```bash
   chmod 700 logs/                    # Only owner can access logs
   chmod 600 .env                     # Protect env file
   chmod 600 .allora_key              # Protect wallet key
   ```

2. **Log Retention**
   - Logs older than 30 days are auto-deleted
   - Sensitive data (keys) not logged
   - API responses sanitized

3. **Error Handling**
   - Failed submissions logged with status
   - No blockchain data exposure
   - Graceful fallback on API errors

---

## 🚨 Production Checklist

- [ ] Virtual environment created and activated
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] `.env` file configured with API keys
- [ ] `.allora_key` (mnemonic) in place
- [ ] `competition_submission.py --validate-only` passes
- [ ] Test run executed successfully: `competition_submission.py --once`
- [ ] Cron jobs installed and verified
- [ ] Log rotation tested
- [ ] Health check running
- [ ] Disk space adequate (>10GB recommended)
- [ ] Time synced (NTP running)

---

## 📝 Example Cron Output

### Successful Run
```
2025-11-22 08:00:05 - INFO - ALLORA COMPETITION SUBMISSION - 2025-11-22 08:00:05Z
2025-11-22 08:00:06 - INFO - Validating environment...
2025-11-22 08:00:06 - INFO - ✅ Environment validation complete
2025-11-22 08:00:07 - INFO - Starting training pipeline...
2025-11-22 08:00:07 - INFO - Running: python train.py --schedule-mode loop --once --submit --as-of-now
...
2025-11-22 08:03:42 - INFO - ✅ Predictions valid: shape=(168,), mean=0.000456, std=0.034
2025-11-22 08:03:50 - INFO - Submitted to blockchain with tx_hash=ABC123...
2025-11-22 08:03:51 - INFO - ✅ Pipeline execution complete
```

### Health Check Output
```
2025-11-22 08:10:15Z - ✅ Recent submission activity detected
```

---

## 📚 Integration with Existing Pipeline

### How It Works Together

1. **train.py** (core pipeline)
   - Trains model
   - Generates predictions
   - **NEW:** Validates predictions
   - Submits to blockchain

2. **competition_submission.py** (wrapper)
   - Calls train.py with arguments
   - Validates environment
   - Checks submission health
   - Logs results

3. **Cron** (scheduler)
   - Runs competition_submission.py hourly
   - Rotates logs
   - Monitors health

### Data Flow
```
Cron 00:00 UTC
    ↓
competition_submission.py --once
    ↓
train.py --once --submit
    ↓
AlloraMLWorkflow (train model)
    ↓
validate_predictions()
    ↓
_submit_via_external_helper()
    ↓
submission_log.csv (logged)
    ↓
logs/pipeline_run.log (rotated at 00:05)
    ↓
healthcheck.sh (verified at 00:10)
```

---

## 🎯 Next Steps

1. **Immediate**: Run `./setup_cron.sh` for setup verification
2. **Testing**: Execute `python3 competition_submission.py --once` manually
3. **Deployment**: Add cron entries from `setup_cron.sh` output
4. **Monitoring**: Watch `tail -f logs/pipeline_run.log` for first automated run
5. **Verification**: Confirm submissions in `submission_log.csv`

---

## 📞 Support

For issues:
1. Check logs: `tail -100 logs/pipeline_run.log`
2. Verify cron: `crontab -l && grep CRON /var/log/syslog`
3. Test manually: `python3 competition_submission.py --once`
4. Check health: `python3 competition_submission.py --check-health`

---

**Status**: ✅ Production Ready  
**Competition**: Topic 67 (7-Day BTC/USD Log-Return)  
**Period**: Sep 16 - Dec 15, 2025 (Hourly)  
**Last Updated**: 2025-11-22
