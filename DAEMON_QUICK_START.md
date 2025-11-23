# Daemon Quick Reference

## Start Daemon

### Option 1: Manual (for testing)
```bash
cd /workspaces/allora-forge-builder-kit
nohup .venv/bin/python submit_prediction.py --daemon &
tail -f logs/submission.log
```

### Option 2: systemd (production)
```bash
sudo systemctl start allora-submission
sudo systemctl status allora-submission
sudo journalctl -u allora-submission -f
```

### Option 3: supervisord
```bash
sudo supervisorctl start allora-submission
sudo supervisorctl status allora-submission
tail -f logs/supervisord-stdout.log
```

---

## Monitor Daemon

```bash
# Check if running
ps aux | grep "submit_prediction.py --daemon"

# View recent logs
tail -50 logs/submission.log

# Watch in real-time
tail -f logs/submission.log

# Find successful submissions
grep "SUCCESS\|✅ Submission" logs/submission.log

# Find errors
grep "ERROR\|❌" logs/submission.log

# Count cycles completed
grep "SUBMISSION CYCLE #" logs/submission.log | wc -l

# Check heartbeats
grep "HEARTBEAT" logs/submission.log | tail -10
```

---

## Stop Daemon

```bash
# Graceful stop (30 sec timeout)
pkill -SIGTERM -f "submit_prediction.py --daemon"

# Or with systemd
sudo systemctl stop allora-submission

# Or with supervisord
sudo supervisorctl stop allora-submission

# Force kill (if needed)
pkill -9 -f "submit_prediction.py --daemon"
```

---

## Restart Daemon

```bash
# Kill all instances
pkill -f "submit_prediction.py --daemon"

# Restart
cd /workspaces/allora-forge-builder-kit
nohup .venv/bin/python submit_prediction.py --daemon &

# Or with systemd
sudo systemctl restart allora-submission
```

---

## Log Files

```
logs/submission.log           # Main daemon log (auto-rotating)
logs/submission.log.1         # Backup 1
logs/submission.log.2         # Backup 2
...
logs/submission.log.5         # Backup 5 (oldest)
logs/supervisord-*.log        # If using supervisord
```

**Rotation:** Auto at 50MB, keeps 5 backups (~250MB total)

---

## Expected Log Messages

### Startup (appears once)
```
🚀 DAEMON MODE STARTED
   Model: model.pkl
   Features: features.json
   Competition End: 2025-12-15T00:00:00+00:00
```

### Hourly
```
💓 HEARTBEAT - Daemon alive at 2025-11-23T14:00:00+00:00
```

### Every submission cycle
```
SUBMISSION CYCLE #123 - 2025-11-23T14:00:00+00:00
✅ Loaded 10 feature columns
✅ Model loaded from model.pkl
Fetching latest 168h BTC/USD data from Tiingo...
Fetched 84 latest rows from Tiingo
Predicted 168h log-return: -0.03813570
```

### Successful submission
```
✅ Submission success
Transaction hash: 7EA6D6EC8940C620...
✅ Submission cycle completed successfully
```

### No unfulfilled nonce (normal skip)
```
WARNING - No unfulfilled nonce available, skipping submission
⚠️  Submission cycle completed without successful submission
```

### Error (continues to next cycle)
```
❌ Failed to fetch BTC/USD data: Connection timeout
   Retrying in next cycle
Sleeping for 3600s until next submission cycle...
```

### Shutdown (at Dec 15, 2025)
```
⏰ Competition end date (2025-12-15T00:00:00+00:00) reached. Shutting down.
🛑 DAEMON SHUTDOWN COMPLETE
   Total Cycles: 2880
```

---

## Troubleshooting

### Daemon not running
```bash
# Check if process exists
ps aux | grep "submit_prediction.py --daemon" | grep -v grep

# Check logs for startup error
head -50 logs/submission.log

# Check dependencies
.venv/bin/python -c "import xgboost; print('OK')"
```

### High CPU/Memory
```bash
# Check resource usage
ps aux | grep "submit_prediction.py --daemon"
top -p $(pgrep -f "submit_prediction.py --daemon")
```

### Logs not appearing
```bash
# Check if log file exists
ls -la logs/submission.log

# Check file permissions
stat logs/submission.log

# Check daemon is actually running
ps aux | grep daemon
```

### Model validation failed
```bash
# Retrain model
python train.py

# Verify model exists
ls -la model.pkl features.json

# Restart daemon
pkill -f "submit_prediction.py --daemon"
nohup .venv/bin/python submit_prediction.py --daemon &
```

---

## Key Features

✅ **Never silently fails** - all exceptions logged with full tracebacks  
✅ **Hourly heartbeat** - confirms daemon is alive  
✅ **Model validated every cycle** - catches corruption mid-operation  
✅ **Auto-rotating logs** - keeps 5 backups, 50MB each  
✅ **Graceful shutdown** - exits cleanly on signals  
✅ **Auto-restart ready** - works with systemd/supervisord  
✅ **Competition aware** - stops automatically at Dec 15, 2025  

---

## Full Documentation

See `DAEMON_DEPLOYMENT.md` for:
- Systemd setup & management
- supervisord setup & management
- Monitoring strategies
- Log rotation details
- Production checklist
- Troubleshooting guide
