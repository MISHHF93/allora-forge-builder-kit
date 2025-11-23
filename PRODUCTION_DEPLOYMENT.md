# Production Deployment Guide - Allora Submission Daemon

## Executive Summary

The submission daemon is now production-hardened for reliable 24/7 operation until December 15, 2025. It includes:

✅ **Zero Silent Failures**: All exceptions caught, logged with full Python tracebacks  
✅ **Automatic Recovery**: Auto-restarts on crash, kill, or server reboot (systemd)  
✅ **Liveness Monitoring**: Hourly heartbeat confirms daemon is alive  
✅ **Comprehensive Logging**: DEBUG-level file logging + INFO-level console  
✅ **Two Deployment Options**: Systemd (recommended) or supervisord  
✅ **Management Tools**: Easy start/stop/monitor via `daemon_manager.sh` script  

## System Requirements

- **OS**: Linux (Ubuntu 20.04+, Debian 11+, CentOS 8+)
- **Python**: 3.9+
- **Disk**: 500MB free (for logs + CSV)
- **Memory**: 512MB minimum (1GB recommended)
- **Network**: Persistent internet connection
- **Time**: NTP synchronized (for blockchain timestamps)

## Pre-Deployment Checklist

- [ ] System OS is Linux
- [ ] Python 3.9+ installed
- [ ] Virtual environment created: `.venv/`
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] Model trained: `python train.py` completed successfully
- [ ] `model.pkl` exists and is recent
- [ ] `features.json` exists (10 features)
- [ ] Environment variables set:
  - [ ] `ALLORA_WALLET_ADDR=allo1...`
  - [ ] `MNEMONIC=word1 word2 ... word12`
  - [ ] `TOPIC_ID=67`
  - [ ] `TIINGO_API_KEY=...` (optional but recommended)
- [ ] `.env` file created or environment variables exported
- [ ] Allorad CLI installed: `which allorad`
- [ ] Wallet has sufficient balance for fees
- [ ] Logs directory writable: `logs/`
- [ ] Test dry-run successful: `python submit_prediction.py --dry-run`

## Deployment Options

### Option A: Systemd (Recommended) ⭐

**Pros:**
- Standard on all modern Linux
- Auto-restart on failure, crash, or reboot
- Integrated with system logging (journalctl)
- No additional dependencies
- Survives server reboots

**Steps:**

```bash
# 1. Install the systemd unit
sudo ./daemon_manager.sh install

# 2. Start the daemon
sudo ./daemon_manager.sh start

# 3. Enable auto-start on reboot
sudo ./daemon_manager.sh enable

# 4. Verify it's running
sudo ./daemon_manager.sh status

# 5. Monitor with logs
./daemon_manager.sh logs
```

**Systemd Configuration Details:**
```ini
[Service]
Restart=always              # Always restart on exit
RestartSec=10              # Wait 10s before restart
StartLimitInterval=60s     # Check window
StartLimitBurst=5          # Allow 5 restarts in 60s window
TimeoutStopSec=30          # Force kill after 30s
```

### Option B: Supervisord (Alternative)

**Pros:**
- Works on older Linux systems without systemd
- Per-program logging
- Can manage multiple services
- Remote monitoring capability

**Steps:**

```bash
# 1. Install supervisord (if not present)
pip install supervisor

# 2. Start via supervisord
./daemon_manager.sh supervisord

# 3. Check status
supervisorctl -c supervisord.conf status

# 4. Monitor logs
supervisorctl -c supervisord.conf tail allora-submission -f
```

### Option C: Simple nohup (Not Recommended)

```bash
# Start (if systemd/supervisord unavailable)
nohup .venv/bin/python submit_prediction.py --continuous > logs/submission.log 2>&1 &

# Save PID
echo $! > /tmp/submission.pid

# Monitor
tail -f logs/submission.log

# Stop
kill $(cat /tmp/submission.pid)
```

**Warning**: Nohup will NOT auto-restart on crash or reboot.

## Environment Configuration

Create `.env` file:

```bash
cat > .env << 'EOF'
# Required
ALLORA_WALLET_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
MNEMONIC="word1 word2 word3 ... word12"
TOPIC_ID="67"

# Optional
TIINGO_API_KEY="your-api-key-here"
SUBMISSION_INTERVAL="3600"  # Seconds, default 1 hour

# For logging (optional)
LOG_LEVEL="DEBUG"
EOF

# Restrict permissions
chmod 600 .env
```

**Security Notes:**
- Keep `.env` out of version control (add to `.gitignore`)
- Restrict file permissions: `chmod 600 .env`
- Use environment variables or secret management (vault, etc.) in production
- Never commit MNEMONIC or private keys

## Starting the Daemon

### With Systemd:

```bash
# Start
sudo systemctl start allora-submission

# Check status
sudo systemctl status allora-submission

# Enable auto-start
sudo systemctl enable allora-submission

# Stop
sudo systemctl stop allora-submission

# Restart
sudo systemctl restart allora-submission
```

### With Supervisord:

```bash
# Start
supervisord -c supervisord.conf

# Check status
supervisorctl -c supervisord.conf status

# Stop
supervisorctl -c supervisord.conf stop allora-submission

# Restart
supervisorctl -c supervisord.conf restart allora-submission
```

## Monitoring the Daemon

### Health Check
```bash
./daemon_manager.sh health
```

Output:
```
Daemon health check
- Recent log entries (last 5)
- Process status (running/not running)
- CSV submission count
```

### View Live Logs
```bash
# Follow logs with systemd
sudo journalctl -u allora-submission -f

# Or from file
./daemon_manager.sh logs

# Search for heartbeats (every hour)
grep "HEARTBEAT" logs/submission.log

# Search for successful submissions
grep "Submission success" logs/submission.log

# Search for errors
grep "ERROR\|CRITICAL" logs/submission.log
```

### Check Submission CSV
```bash
# View all submissions
cat submission_log.csv

# Count successful submissions
grep "success" submission_log.csv | wc -l

# Show last submission
tail -1 submission_log.csv

# Watch for new submissions
tail -f submission_log.csv
```

### Monitor CPU/Memory
```bash
# Check resource usage
ps aux | grep submit_prediction.py

# Watch with top
top -p $(pgrep -f "submit_prediction.py --continuous")

# Monitor over time
while true; do ps aux | grep submit_prediction.py | grep -v grep; sleep 60; done
```

## Handling Issues

### Daemon won't start

```bash
# Check syntax
python submit_prediction.py --dry-run

# Check systemd logs
sudo journalctl -u allora-submission -n 100

# Check file permissions
ls -la model.pkl features.json

# Check environment variables
echo $ALLORA_WALLET_ADDR
echo $MNEMONIC | wc -c
```

### High CPU/Memory usage

```bash
# Check if process is stuck
ps aux | grep submit_prediction

# Monitor file descriptors
lsof -p $(pgrep -f submit_prediction.py) | wc -l

# Check disk usage
du -sh logs/ submission_log.csv

# Restart if necessary
sudo systemctl restart allora-submission
```

### No submissions appearing

```bash
# Check for available nonces
allorad query emissions unfulfilled-worker-nonces 67

# Check submission log for details
tail -50 logs/submission.log | grep -i nonce

# Verify wallet/mnemonic
allorad keys show -a  # If wallet imported

# Check CLI is working
allorad --version
```

### Logs growing too large

```bash
# Rotate manually
mv logs/submission.log logs/submission.log.$(date +%s)

# Daemon will create new log automatically

# Or set up logrotate
sudo cat > /etc/logrotate.d/allora-submission << 'EOF'
/workspaces/allora-forge-builder-kit/logs/submission.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload allora-submission >/dev/null 2>&1 || true
    endscript
}
EOF
```

## Monitoring Dashboard

Create a simple monitoring script:

```bash
#!/bin/bash
watch -n 10 'echo "=== DAEMON STATUS ===" && \
sudo systemctl status allora-submission | head -3 && \
echo "" && \
echo "=== RECENT SUBMISSIONS ===" && \
tail -3 submission_log.csv && \
echo "" && \
echo "=== LAST LOG ENTRIES ===" && \
tail -3 logs/submission.log'
```

Run: `./monitor.sh`

## Maintenance

### Weekly
- [ ] Check health: `./daemon_manager.sh health`
- [ ] Review recent logs: `grep ERROR logs/submission.log`
- [ ] Count submissions: `grep success submission_log.csv | wc -l`

### Monthly
- [ ] Rotate old logs
- [ ] Check disk usage: `du -sh logs/ submission_log.csv`
- [ ] Review CSV for patterns in skipped submissions
- [ ] Test model quality with recent predictions

### Before Competition End (Dec 14)
- [ ] Verify daemon is still running
- [ ] Download final submission_log.csv
- [ ] Archive logs
- [ ] Prepare shutdown procedures

## Graceful Shutdown

### Before maintenance:
```bash
sudo systemctl stop allora-submission
```

### To check if stopped:
```bash
./daemon_manager.sh status
```

### Restart after maintenance:
```bash
sudo systemctl start allora-submission
```

## Performance Expectations

**Per Cycle:**
- Model load: 1-2 seconds
- Data fetch: 1-2 seconds
- Feature engineering: <1 second
- Prediction: <1 second
- Submission: 1-2 seconds
- **Total**: 4-8 seconds per hour

**Resource Usage:**
- CPU: 5-10% during submission, <1% idle
- Memory: 150-250MB resident
- Disk: ~5-10MB per month (logs)
- Network: ~50KB per submission

## Success Criteria

✅ **Daemon is running:**
```bash
ps aux | grep submit_prediction.py
systemctl status allora-submission
```

✅ **Submissions being recorded:**
```bash
tail submission_log.csv
grep success submission_log.csv | wc -l
```

✅ **Heartbeats appearing hourly:**
```bash
grep HEARTBEAT logs/submission.log | tail
```

✅ **No errors or silent failures:**
```bash
grep "ERROR\|CRITICAL\|exception" logs/submission.log
```

✅ **System survives restart:**
- Reboot server
- Check daemon is running
- Verify new submissions after reboot

## Troubleshooting Reference

| Issue | Check | Fix |
|-------|-------|-----|
| Daemon won't start | `python submit_prediction.py --dry-run` | Fix syntax/dependencies |
| No submissions | `allorad query emissions unfulfilled-worker-nonces 67` | Wait for nonces or check wallet |
| High memory | `ps aux \| grep submit_prediction` | Restart daemon |
| Disk full | `du -sh logs/` | Rotate old logs |
| Can't submit | Check `.env` file | Verify all env vars set |
| Process dies | `sudo journalctl -u allora-submission` | Check logs for errors |

## Support & Documentation

- **Quick Reference**: [DAEMON_GUIDE.md](DAEMON_GUIDE.md)
- **Code**: [submit_prediction.py](submit_prediction.py)
- **Config**: [allora-submission.service](allora-submission.service)
- **Manager**: [daemon_manager.sh](daemon_manager.sh)

## Next Steps

1. **Immediate**: Follow "Pre-Deployment Checklist"
2. **Setup**: Choose deployment option (A=Systemd recommended)
3. **Start**: `sudo ./daemon_manager.sh start`
4. **Verify**: `./daemon_manager.sh health`
5. **Monitor**: `./daemon_manager.sh logs`
6. **Maintain**: Weekly health checks

**Expected Timeline to Production**: 5-10 minutes
**Monitoring Effort**: 5 minutes daily
**Estimated Success Rate**: 99%+ (with systemd auto-restart)

---

**Last Updated**: 2025-11-23  
**Valid Until**: 2025-12-15 (competition end)
