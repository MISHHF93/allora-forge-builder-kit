# Allora Submission Daemon - Deployment & Operation Guide

## Overview

The updated `submit_prediction.py` now supports **daemon mode** for reliable long-lived operation until December 15, 2025.

### Key Features

✅ **Never Silently Fails** - Catches ALL exceptions, logs full tracebacks  
✅ **Hourly Heartbeat** - Confirms daemon is alive every hour  
✅ **Model Validation** - Validates model on every submission cycle  
✅ **Rotating Logs** - Auto-rotates logs at 50MB (keeps 5 backups)  
✅ **Graceful Shutdown** - Handles SIGTERM/SIGINT cleanly  
✅ **Auto-Restart Ready** - Works with systemd and supervisord  
✅ **Competition Aware** - Automatically stops at competition end date  

---

## Quick Start (3 options)

### Option 1: Manual Daemon (for testing)
```bash
cd /workspaces/allora-forge-builder-kit
nohup .venv/bin/python submit_prediction.py --daemon > logs/daemon.log 2>&1 &
```

Monitor with:
```bash
tail -f logs/submission.log
```

Kill with:
```bash
pkill -f "submit_prediction.py --daemon"
```

---

### Option 2: systemd (Recommended for production)

**Installation:**
```bash
# Copy systemd unit file
sudo cp allora-submission.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable allora-submission

# Start the daemon
sudo systemctl start allora-submission

# Check status
sudo systemctl status allora-submission
```

**Management Commands:**
```bash
# View status
sudo systemctl status allora-submission

# View logs
sudo journalctl -u allora-submission -f          # Follow in real-time
sudo journalctl -u allora-submission --since 1h  # Last hour

# Control
sudo systemctl start allora-submission
sudo systemctl stop allora-submission
sudo systemctl restart allora-submission

# Disable auto-start
sudo systemctl disable allora-submission
```

**View Daemon Activity:**
```bash
# Real-time logs (with color)
sudo journalctl -u allora-submission -f -o short-iso

# All logs from today
sudo journalctl -u allora-submission --since today

# Last 100 lines
sudo journalctl -u allora-submission -n 100
```

---

### Option 3: supervisord (Alternative for production)

**Installation:**
```bash
# Install supervisord if not present
sudo apt-get install supervisor

# Copy configuration
sudo cp supervisord-allora-submission.conf /etc/supervisor/conf.d/allora-submission.conf

# Reread configuration
sudo supervisorctl reread

# Update supervisor
sudo supervisorctl update

# Check status
sudo supervisorctl status allora-submission
```

**Management Commands:**
```bash
# View status
sudo supervisorctl status allora-submission

# Control
sudo supervisorctl start allora-submission
sudo supervisorctl stop allora-submission
sudo supervisorctl restart allora-submission

# View logs
tail -f /workspaces/allora-forge-builder-kit/logs/supervisord-stdout.log
tail -f /workspaces/allora-forge-builder-kit/logs/supervisord-stderr.log

# Interactive shell
sudo supervisorctl
```

---

## Monitoring & Verification

### Check Daemon Health

**Verify it's running:**
```bash
# Option 1: Check process
ps aux | grep "submit_prediction.py --daemon" | grep -v grep

# Option 2: Check systemd (if using systemd)
sudo systemctl is-active allora-submission

# Option 3: Check supervisord (if using supervisord)
sudo supervisorctl status allora-submission
```

**Check Recent Activity:**
```bash
# Last 50 lines
tail -50 logs/submission.log

# Find heartbeat messages
grep "HEARTBEAT" logs/submission.log | tail -10

# Find errors
grep "ERROR\|❌" logs/submission.log | tail -20

# Find successful submissions
grep "SUCCESS\|✅" logs/submission.log | tail -10
```

**Monitor Realtime:**
```bash
# Live tail (follow)
tail -f logs/submission.log

# With grep filter
tail -f logs/submission.log | grep "HEARTBEAT\|SUCCESS\|ERROR"

# With systemd
sudo journalctl -u allora-submission -f
```

### Expected Log Patterns

**Healthy daemon (every hour):**
```
2025-11-23 02:00:00Z - INFO - 💓 HEARTBEAT - Daemon alive at 2025-11-23T02:00:00+00:00
...
2025-11-23 03:00:00Z - INFO - 💓 HEARTBEAT - Daemon alive at 2025-11-23T03:00:00+00:00
```

**Successful submission:**
```
2025-11-23 01:59:35Z - INFO - Submitting prediction -0.03813570 for topic 67 at block 6643675
2025-11-23 01:59:36Z - INFO - ✅ Submission success
2025-11-23 01:59:36Z - INFO - Transaction hash: 7EA6D6EC8940C620F42077F4F35D04ACAE9331FA4761FFA76F03A4250D2E60AF
2025-11-23 01:59:36Z - INFO - ✅ Submission cycle completed successfully
```

**Skipped (no unfulfilled nonce):**
```
2025-11-23 01:59:40Z - WARNING - All unfulfilled nonces already submitted by this worker
2025-11-23 01:59:40Z - WARNING - No unfulfilled nonce available, skipping submission
2025-11-23 01:59:40Z - INFO - ⚠️  Submission cycle completed without successful submission
```

**Error (but continues):**
```
2025-11-23 01:59:40Z - ERROR - ❌ Failed to fetch BTC/USD data: Connection timeout
2025-11-23 01:59:40Z - ERROR -    Retrying in next cycle
2025-11-23 01:59:40Z - INFO - Sleeping for 3600s until next submission cycle...
```

---

## Auto-Restart Behavior

### systemd Restart Policy
- **Restart on crash:** Yes (always)
- **Wait before restart:** 30 seconds
- **Max restarts:** 5 within 300 seconds
- **On 5+ failures:** systemd will stop auto-restarting; manual intervention needed

**Check restart history:**
```bash
sudo systemctl status allora-submission
sudo journalctl -u allora-submission | grep -i restart
```

### supervisord Restart Policy
- **Auto-start on boot:** Yes (autostart=true)
- **Auto-restart on exit:** Yes (autorestart=true)
- **Wait before restart:** 10 seconds
- **No failure limit** - will keep restarting forever

---

## Logs Location & Rotation

**Log files:**
```
logs/submission.log          # Main daemon log (auto-rotates at 50MB)
logs/submission.log.1        # Backup 1
logs/submission.log.2        # Backup 2
logs/submission.log.3        # Backup 3
logs/submission.log.4        # Backup 4
logs/submission.log.5        # Backup 5 (oldest)

logs/supervisord-stdout.log  # If using supervisord
logs/supervisord-stderr.log  # If using supervisord
```

**Rotation settings:**
- **Max file size:** 50 MB
- **Backup files:** 5 (keeps ~250 MB total)
- **Auto-cleanup:** Oldest files deleted when limit exceeded

**View log stats:**
```bash
ls -lh logs/submission.log*
du -sh logs/
```

---

## Graceful Shutdown & Restarts

### Systemd
```bash
# Graceful stop (gives 30 seconds to shutdown cleanly)
sudo systemctl stop allora-submission

# Restart
sudo systemctl restart allora-submission

# Reread and update config
sudo systemctl daemon-reload
sudo systemctl restart allora-submission
```

### supervisord
```bash
# Graceful stop
sudo supervisorctl stop allora-submission

# Restart
sudo supervisorctl restart allora-submission
```

### Manual Process
```bash
# Kill gracefully (allows 30 second shutdown)
kill -SIGTERM $(pgrep -f "submit_prediction.py --daemon")

# Kill forcefully (if needed)
pkill -9 -f "submit_prediction.py --daemon"
```

---

## Troubleshooting

### Daemon won't start

**Check logs:**
```bash
# systemd
sudo journalctl -u allora-submission -n 50

# supervisord
tail -50 /workspaces/allora-forge-builder-kit/logs/supervisord-stderr.log
```

**Common issues:**
1. **Missing model.pkl or features.json** → Run `python train.py` first
2. **Missing environment variables** → Check `.env` file has ALLORA_WALLET_ADDR, MNEMONIC, TOPIC_ID
3. **Permission denied** → Check file ownership and permissions
4. **Port/lock conflicts** → Check no other instance is running

### Daemon keeps crashing

**Check for restart loops:**
```bash
# systemd
sudo journalctl -u allora-submission --since 1h | grep -i "restarted\|started\|stopped" | head -20
```

**Check max restart limit:**
```bash
sudo systemctl status allora-submission
# Look for "restart limit hit"
```

**Solution:** Manually restart and check logs for root cause:
```bash
sudo systemctl restart allora-submission
sleep 5
sudo journalctl -u allora-submission -n 100
```

### High CPU/Memory usage

**Check resource usage:**
```bash
ps aux | grep "submit_prediction.py --daemon"
top -p $(pgrep -f "submit_prediction.py --daemon")
```

**Limits in systemd:**
- MemoryLimit=2G (in allora-submission.service)
- CPUQuota=50%

**Adjust if needed** (edit service file and reload):
```bash
sudo systemctl daemon-reload
sudo systemctl restart allora-submission
```

---

## Production Checklist

- [ ] Model file exists: `model.pkl`
- [ ] Features file exists: `features.json`
- [ ] Environment variables set (ALLORA_WALLET_ADDR, MNEMONIC, TOPIC_ID)
- [ ] Logs directory writable: `logs/`
- [ ] Chose deployment method (systemd or supervisord)
- [ ] Configuration file deployed
- [ ] Daemon started and verified running
- [ ] Logs being written (check `tail -f logs/submission.log`)
- [ ] Hourly heartbeat appearing in logs
- [ ] Monitored for 24+ hours without crashes

---

## Upgrading the Daemon

**To update code while preserving daemon operation:**

```bash
# 1. Backup current logs
cp logs/submission.log logs/submission.log.backup.$(date +%s)

# 2. Stop daemon
sudo systemctl stop allora-submission  # or: supervisorctl stop allora-submission

# 3. Pull updates
cd /workspaces/allora-forge-builder-kit
git pull origin main

# 4. Restart daemon
sudo systemctl start allora-submission  # or: supervisorctl start allora-submission

# 5. Verify
sudo systemctl status allora-submission
tail -f logs/submission.log
```

---

## Competition End (December 15, 2025)

The daemon automatically:
1. Checks current time at start of each cycle
2. Compares to December 15, 2025 00:00:00 UTC
3. **Gracefully shuts down** when end date is reached
4. **Logs final shutdown message** with cycle count and timestamp

**Expected final log:**
```
2025-12-15 00:00:00Z - INFO - ⏰ Competition end date (2025-12-15T00:00:00+00:00) reached. Shutting down.
2025-12-15 00:00:00Z - INFO - ================================================================================
2025-12-15 00:00:00Z - INFO - 🛑 DAEMON SHUTDOWN COMPLETE
2025-12-15 00:00:00Z - INFO -    Total Cycles: 2880
2025-12-15 00:00:00Z - INFO -    Final Time: 2025-12-15T00:00:00+00:00
2025-12-15 00:00:00Z - INFO - ================================================================================
```

---

## Support & Debugging

**For detailed debugging, enable debug logging (edit submit_prediction.py):**
```python
# Change: logger.setLevel(logging.DEBUG)
# This captures more detailed information
```

**Collect debug info for support:**
```bash
# Last 1000 lines of log
tail -1000 logs/submission.log > debug-logs.txt

# System info
uname -a >> debug-logs.txt
python --version >> debug-logs.txt
.venv/bin/pip list >> debug-logs.txt

# Process info
ps aux | grep submit_prediction >> debug-logs.txt

# Systemd info (if using)
sudo systemctl status allora-submission >> debug-logs.txt
```

---

## Version History

- **v2.0** (Nov 23, 2025): Enhanced daemon mode with heartbeat, exception handling, log rotation
- **v1.0**: Initial submission pipeline
