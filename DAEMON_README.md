# 🛠️ Allora Forge Kit: Permanent Daemon

**Version:** Numbered Reference Format (Clean & Focused)  
**Purpose:** Run an automated loop to train and submit predictions for Topic 67 every hour until Dec 15, 2025.

## 🚀 Quick Start

```bash
# Start the daemon
./manage_daemon.sh start

# Check status
./manage_daemon.sh status

# Stop the daemon
./manage_daemon.sh stop

# Restart the daemon
./manage_daemon.sh restart
```

## ⏳ Scheduling Details

- **Cycle Interval:** Every 60 minutes (exactly)
- **Cycle Content:** Train model → Submit prediction
- **End Date:** 2025-12-15 13:00:00 UTC
- **Timezone:** All timing uses UTC internally

## 📁 File Structure

```
.
├── daemon.py              # Main daemon script
├── manage_daemon.sh       # Daemon management utility
├── train.py              # Model training script
├── submit_prediction.py  # Prediction submission script
├── artifacts/            # Model and data storage
│   └── model_bundle.joblib
├── logs/                 # Log files
│   ├── daemon.log        # Daemon activity log
│   └── submit.log        # Submission details
└── daemon.pid            # Process ID file (auto-managed)
```

## 🔧 Environment Variables

Set these in your `.env` file:

```bash
ALLORA_WALLET_ADDR=your_wallet_address
TOPIC_ID=67
ALLORA_API_KEY=your_api_key
```

## 📊 Monitoring

### Check Daemon Status
```bash
./manage_daemon.sh status
```

### View Recent Logs
```bash
tail -f logs/daemon.log
```

### View Submission History
```bash
tail -f logs/submit.log
```

## 🔄 Daemon Behavior

### Normal Operation
- Runs hourly cycles until competition end
- Each cycle: training (20min timeout) → submission (10min timeout)
- Logs all activity to `logs/daemon.log`
- Handles transient errors gracefully
- Respects rate limits and API constraints

### Error Handling
- **Training failures:** Continue with existing model
- **Submission failures:** Log error and continue to next cycle
- **Rate limiting:** Automatic backoff and retry
- **Network issues:** Failover to alternative endpoints

### Shutdown
- **Graceful:** Responds to SIGTERM/SIGINT
- **Automatic:** Stops at competition deadline
- **Forced:** Use `./manage_daemon.sh stop` for immediate shutdown

## 🛑 Emergency Stop

If you need to stop the daemon immediately:

```bash
# Graceful stop (recommended)
./manage_daemon.sh stop

# Force kill (if unresponsive)
pkill -f daemon.py
rm -f daemon.pid
```

## 📈 Expected Runtime

- **Start Date:** Now (December 6, 2025)
- **End Date:** December 15, 2025, 13:00 UTC
- **Total Cycles:** ~227 cycles
- **Total Runtime:** ~9.5 days

## 🔍 Troubleshooting

### Daemon Won't Start
```bash
# Check environment variables
python -c "import os; print('WALLET:', os.getenv('ALLORA_WALLET_ADDR')); print('TOPIC:', os.getenv('TOPIC_ID'))"

# Check required files exist
ls -la train.py submit_prediction.py

# Check logs for errors
tail -20 logs/daemon.log
```

### Training/Submission Failures
```bash
# Check detailed logs
tail -50 logs/submit.log

# Test individual components
python train.py
python submit_prediction.py --once
```

### High CPU/Memory Usage
- The daemon runs training every hour (resource intensive)
- Monitor system resources during peak hours
- Consider running on a machine with sufficient resources

## 🎯 Success Criteria

✅ **Daemon runs continuously** until Dec 15, 2025  
✅ **Hourly cycles complete** (training + submission)  
✅ **Rate limits respected** (no API bans)  
✅ **Errors logged** (not silently ignored)  
✅ **Graceful shutdown** (clean process termination)

## 📞 Support

- **Logs:** Check `logs/daemon.log` for detailed information
- **Status:** Use `./manage_daemon.sh status` for quick overview
- **Process:** Use `ps aux | grep daemon.py` to verify running
- **Resources:** Monitor with `top` or `htop` during training cycles