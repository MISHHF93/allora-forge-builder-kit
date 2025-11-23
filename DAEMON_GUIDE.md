# Allora Submission Daemon - Long-Lived Operation Guide

## Overview

The submission daemon (`submit_prediction.py --continuous`) is now hardened for reliable long-lived operation until December 15, 2025. It includes:

- **Comprehensive exception handling**: All errors logged with full tracebacks
- **Hourly heartbeat**: Confirms daemon liveness every hour
- **Cycle tracking**: Shows which submission cycle is running
- **Auto-restart capabilities**: Via systemd (recommended) or supervisord
- **No silent failures**: All exceptions caught and logged
- **Enhanced logging**: Dual file + console output with DEBUG level

## Quick Start

### Option 1: Systemd (Recommended)

```bash
# 1. Check requirements
./daemon_manager.sh health

# 2. Install systemd unit file (requires sudo)
sudo ./daemon_manager.sh install

# 3. Start the daemon
sudo ./daemon_manager.sh start

# 4. Enable auto-start on reboot
sudo ./daemon_manager.sh enable

# 5. Monitor
./daemon_manager.sh logs
./daemon_manager.sh health
```

### Option 2: Supervisord (Alternative)

```bash
# Install supervisord if not present
pip install supervisor

# Start daemon via supervisord
./daemon_manager.sh supervisord

# Check status
supervisorctl -c supervisord.conf status

# Monitor
tail -f logs/supervisord_submission.log
```

### Option 3: Manual nohup (Simple)

```bash
# Start (if systemd not available)
nohup .venv/bin/python submit_prediction.py --continuous > logs/submission.log 2>&1 &

# Save PID for reference
echo $! > /tmp/submission.pid

# Follow logs
tail -f logs/submission.log

# Stop when needed
kill $(cat /tmp/submission.pid)
```

## Monitoring the Daemon

### Check Status
```bash
./daemon_manager.sh status        # Systemd status
./daemon_manager.sh health        # Quick health check
./daemon_manager.sh logs          # Follow live logs
```

### View Logs
```bash
# Live logs from journalctl (systemd)
sudo journalctl -u allora-submission -f

# Or from file
tail -f logs/submission.log

# Search for specific events
grep "HEARTBEAT" logs/submission.log
grep "Submission success" logs/submission.log
grep "ERROR\|CRITICAL" logs/submission.log
```

### Monitor Submission CSV
```bash
# Check recent submissions
tail -5 submission_log.csv

# Count successful submissions
grep ",success" submission_log.csv | wc -l

# Watch for new submissions
tail -f submission_log.csv
```

## Key Features

### 1. Hourly Heartbeat
The daemon logs a heartbeat every hour to confirm it's alive:
```
2025-11-23 02:04:36Z - INFO - 🔄 [HEARTBEAT] Daemon alive - cycle #42
```

### 2. Cycle Tracking
Each submission cycle is numbered and logged:
```
2025-11-23 02:03:40Z - INFO - --- Cycle #1 started at 2025-11-23T02:03:40.123456+00:00 ---
2025-11-23 02:04:36Z - INFO - Cycle #1 completed in 56.2s. Sleeping 3543.8s until next cycle...
```

### 3. Complete Exception Logging
All errors include full Python tracebacks:
```
2025-11-23 02:05:00Z - ERROR - Exception in fetch_latest_btcusd_hourly: ConnectionError: Connection refused
2025-11-23 02:05:00Z - ERROR - Full traceback:
2025-11-23 02:05:00Z - ERROR - Traceback (most recent call last):
  File "submit_prediction.py", line 125, in fetch_latest_btcusd_hourly
    r = requests.get(url, params=params, timeout=api_timeout)
...
```

### 4. Graceful Degradation
The daemon never silently fails:
- If Tiingo API fails → Uses synthetic data
- If nonce unavailable → Logs and retries next cycle
- If submission fails → Logs reason and continues

## Auto-Restart Behavior

### Systemd Configuration
```ini
[Service]
Restart=always              # Always restart on exit
RestartSec=10              # Wait 10 seconds before restart
StartLimitInterval=60s     # Time window for burst check
StartLimitBurst=5          # Allow 5 restarts in 60s before giving up
```

**Behavior:**
- Daemon crashes → Automatically restarts after 10 seconds
- Server reboots → Daemon starts automatically (if enabled)
- Too many rapid crashes → Stops trying (after 5 in 60s)

### Supervisord Configuration
- `autorestart=true`: Automatically restart if process exits
- `startsecs=10`: Wait 10 seconds before considering startup successful
- `stopasgroup=true`: Kill entire process group on stop

## Deployment Checklist

- [ ] Model trained: `python train.py`
- [ ] Features generated: Verify `features.json` exists
- [ ] Environment variables set: `ALLORA_WALLET_ADDR`, `MNEMONIC`, `TOPIC_ID`
- [ ] Tiingo API key configured (optional): `TIINGO_API_KEY`
- [ ] Systemd installed and running: `systemctl status`
- [ ] Daemon unit installed: `sudo ./daemon_manager.sh install`
- [ ] Daemon started: `sudo ./daemon_manager.sh start`
- [ ] Auto-boot enabled: `sudo ./daemon_manager.sh enable`
- [ ] Health check passing: `./daemon_manager.sh health`
- [ ] Logs verified: `./daemon_manager.sh logs`

## Troubleshooting

### Daemon won't start
```bash
# Check syntax errors
python submit_prediction.py --dry-run

# Check systemd logs
sudo journalctl -u allora-submission -n 50

# Check dependencies
python -c "import allora_sdk; import xgboost"
```

### High CPU/Memory usage
```bash
# Check if stuck in loop
ps aux | grep submit_prediction

# Monitor resource usage
top -p $(pgrep -f submit_prediction.py)

# Check for file descriptor leaks
lsof -p $(pgrep -f submit_prediction.py) | wc -l
```

### No submissions appearing
```bash
# Check for unfulfilled nonces
allorad query emissions unfulfilled-worker-nonces 67

# Check submission log
tail -20 logs/submission.log | grep -i "nonce\|submit"

# Verify wallet/mnemonic
echo $ALLORA_WALLET_ADDR
echo $MNEMONIC | wc -c  # Should be ~200+ chars
```

### Logs growing too large
```bash
# Rotate logs
mv logs/submission.log logs/submission.log.$(date +%s)
# Daemon will create new one automatically

# Or set up logrotate:
sudo cat > /etc/logrotate.d/allora-submission << 'EOF'
/workspaces/allora-forge-builder-kit/logs/submission.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
EOF
```

## Stopping the Daemon

```bash
# Stop via systemd
sudo systemctl stop allora-submission

# Or via supervisord
supervisorctl -c supervisord.conf stop allora-submission

# Or find and kill process
kill $(pgrep -f "submit_prediction.py --continuous")
```

## Running Until December 15, 2025

The daemon is designed to run continuously until competition end:

```bash
# Check days remaining
python3 -c "from datetime import datetime, timezone; \
end = datetime(2025, 12, 15, 23, 59, 59, tzinfo=timezone.utc); \
days = (end - datetime.now(timezone.utc)).days; \
print(f'Days until Dec 15: {days}')"
```

The daemon will:
1. Submit a prediction every hour (configurable via `SUBMISSION_INTERVAL` env var)
2. Log heartbeat every hour
3. Auto-restart if it crashes
4. Survive server reboots (if systemd enabled)
5. Write comprehensive logs to `logs/submission.log`
6. Record all submissions to `submission_log.csv`

## Environment Variables

Set in `.env` file or export before starting:

```bash
export ALLORA_WALLET_ADDR="allo1..."
export MNEMONIC="word1 word2 ... word12"
export TOPIC_ID="67"
export TIINGO_API_KEY="your-api-key"  # Optional
export SUBMISSION_INTERVAL="3600"      # Optional, defaults to 3600s (1 hour)
```

## Support

For issues:
1. Check logs: `./daemon_manager.sh logs`
2. Run health check: `./daemon_manager.sh health`
3. Review this guide for your use case
4. Check GitHub issues for known problems
