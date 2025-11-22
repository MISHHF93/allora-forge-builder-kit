# Production Deployment Guide - Allora Competition Pipeline

## Overview

This guide covers three production deployment methods for the Allora competition submission pipeline:

1. **Cron-based scheduling** (recommended for Linux/EC2)
2. **Docker containerization** (recommended for cloud environments)
3. **Systemd service** (alternative for Linux systems)

---

## Method 1: Cron-based Scheduling (Recommended for Linux)

### Prerequisites

- Pipeline installed at `/home/ubuntu/allora-forge-builder-kit/`
- Python virtual environment: `.venv/bin/python`
- Environment variables configured in `.env` file
- Both `rotate_logs.sh` and `healthcheck.sh` made executable

### Installation Steps

#### Step 1: Make Scripts Executable

```bash
chmod +x /home/ubuntu/allora-forge-builder-kit/logs/rotate_logs.sh
chmod +x /home/ubuntu/allora-forge-builder-kit/logs/healthcheck.sh
```

#### Step 2: Open Crontab Editor

```bash
crontab -e
```

#### Step 3: Add Three Cron Jobs

Add these three lines to your crontab:

```cron
# Run submission pipeline at top of every hour
0 * * * * /home/ubuntu/allora-forge-builder-kit/.venv/bin/python /home/ubuntu/allora-forge-builder-kit/competition_submission.py --once >> /home/ubuntu/allora-forge-builder-kit/logs/submission.log 2>&1

# Rotate logs at 5 minutes past every hour
5 * * * * /home/ubuntu/allora-forge-builder-kit/logs/rotate_logs.sh >> /home/ubuntu/allora-forge-builder-kit/logs/submission.log 2>&1

# Run health checks at 10 minutes past every hour
10 * * * * /home/ubuntu/allora-forge-builder-kit/logs/healthcheck.sh >> /home/ubuntu/allora-forge-builder-kit/logs/submission.log 2>&1
```

**Timing Breakdown:**
- **00:00, 01:00, 02:00...** - Submit prediction (0 minutes past each hour)
- **00:05, 01:05, 02:05...** - Rotate logs (5 minutes past each hour)
- **00:10, 01:10, 02:10...** - Health check (10 minutes past each hour)

#### Step 4: Save and Verify

1. Exit your editor (Ctrl+X in nano, :wq in vim)
2. Verify installation:

```bash
crontab -l
```

You should see all three jobs listed.

### Monitoring Cron Execution

#### View Logs

```bash
# Check recent logs
tail -100 /home/ubuntu/allora-forge-builder-kit/logs/submission.log

# Watch logs in real-time
tail -f /home/ubuntu/allora-forge-builder-kit/logs/submission.log

# Check health status
cat /home/ubuntu/allora-forge-builder-kit/logs/healthcheck_status.log

# Check alerts
cat /home/ubuntu/allora-forge-builder-kit/logs/healthcheck_alerts.log
```

#### Verify Cron Jobs Are Running

```bash
# Check system cron logs (Linux)
sudo grep -i cron /var/log/syslog | tail -20

# Or on newer systems:
sudo journalctl -u cron --no-pager | tail -20

# Or check the cron job runner directly
ps aux | grep python | grep competition_submission
```

#### Check Submission Success Rate

```bash
# Count successful submissions
grep -c "submission successful" /home/ubuntu/allora-forge-builder-kit/logs/submission.log

# Count failed submissions
grep -c "validation_failed\|CRITICAL" /home/ubuntu/allora-forge-builder-kit/logs/submission.log

# View latest submission status
tail -1 /home/ubuntu/allora-forge-builder-kit/logs/submission.log
```

### Troubleshooting Cron Issues

#### Issue: Cron jobs not running

1. **Verify crontab is installed:**
   ```bash
   which cron
   sudo systemctl status cron
   ```

2. **Check cron file permissions:**
   ```bash
   crontab -l
   ```

3. **Check Python path:**
   ```bash
   /home/ubuntu/allora-forge-builder-kit/.venv/bin/python --version
   ```

4. **Check .env file exists and has correct path:**
   ```bash
   ls -la /home/ubuntu/allora-forge-builder-kit/.env
   cat /home/ubuntu/allora-forge-builder-kit/.env | head -5
   ```

#### Issue: Submissions failing

1. **Check for validation errors:**
   ```bash
   grep "validation_failed\|ValueError" /home/ubuntu/allora-forge-builder-kit/logs/submission.log
   ```

2. **Check wallet balance:**
   ```bash
   grep "balance:" /home/ubuntu/allora-forge-builder-kit/logs/submission.log | tail -5
   ```

3. **Check RPC connectivity:**
   ```bash
   grep "RPC\|endpoint" /home/ubuntu/allora-forge-builder-kit/logs/submission.log | tail -10
   ```

#### Issue: Logs growing too large

1. **Check log size:**
   ```bash
   du -sh /home/ubuntu/allora-forge-builder-kit/logs/
   ```

2. **Verify rotation is working:**
   ```bash
   ls -lh /home/ubuntu/allora-forge-builder-kit/logs/ | grep submission
   ```

3. **If rotation failing, manually rotate:**
   ```bash
   /home/ubuntu/allora-forge-builder-kit/logs/rotate_logs.sh
   ```

---

## Method 2: Docker Containerization (Recommended for Cloud)

### Prerequisites

- Docker installed and running
- Docker Compose installed (v2.0+)
- `.env` file with credentials in project root

### Installation Steps

#### Step 1: Build Docker Image

```bash
cd /path/to/allora-forge-builder-kit
docker build -t allora-pipeline:latest .
```

Expected output:
```
[+] Building 45.3s (13/13) FINISHED
 => Successfully built a1b2c3d4e5f6
 => Tagging as allora-pipeline:latest
```

#### Step 2: Verify Image

```bash
docker images | grep allora
# Output: allora-pipeline    latest    a1b2c3d4e5f6   2 minutes ago   850MB
```

#### Step 3: Create Logs Directory

```bash
mkdir -p /path/to/allora-forge-builder-kit/logs
chmod 755 /path/to/allora-forge-builder-kit/logs
```

#### Step 4: Start with Docker Compose

```bash
cd /path/to/allora-forge-builder-kit
docker-compose up -d
```

Output:
```
[+] Running 3/3
 ✓ Network allora-net Created
 ✓ Container allora-competition-pipeline Created
 ✓ Container allora-log-rotator Created
 ✓ Container allora-health-monitor Created
```

#### Step 5: Verify Containers

```bash
docker ps

# Should show three containers:
# - allora-competition-pipeline (submission)
# - allora-log-rotator (log management)
# - allora-health-monitor (health checks)
```

### Monitoring Docker Containers

#### View Logs

```bash
# Pipeline logs
docker logs -f allora-competition-pipeline

# Log rotator logs
docker logs allora-log-rotator

# Health monitor logs
docker logs allora-health-monitor

# Last 100 lines of pipeline
docker logs --tail 100 allora-competition-pipeline
```

#### Check Container Status

```bash
# Get detailed status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check health status
docker inspect allora-competition-pipeline --format '{{.State.Health.Status}}'
```

#### View Persistent Logs

```bash
# Host filesystem (if using bind mounts)
tail -100 ./logs/submission.log
tail -f ./logs/submission.log

# Inside container
docker exec allora-competition-pipeline tail -100 /app/logs/submission.log
```

### Managing Docker Containers

#### Stop Containers

```bash
docker-compose stop
```

#### Restart Containers

```bash
docker-compose restart
```

#### Remove Containers

```bash
docker-compose down

# Also remove volumes (warning: deletes persistent data)
docker-compose down -v
```

#### View Container Resource Usage

```bash
docker stats allora-competition-pipeline
```

#### Execute Commands in Container

```bash
# Check logs inside container
docker exec allora-competition-pipeline tail -100 /app/logs/submission.log

# Run diagnostic
docker exec allora-competition-pipeline python -c "
import os
print(f'TOPIC_ID: {os.getenv(\"TOPIC_ID\")}')
print(f'WALLET: {os.getenv(\"ALLORA_WALLET_ADDR\")[:10]}...')
"
```

### Troubleshooting Docker Issues

#### Issue: Container keeps restarting

1. **Check container logs:**
   ```bash
   docker logs allora-competition-pipeline | tail -50
   ```

2. **Check exit code:**
   ```bash
   docker inspect allora-competition-pipeline --format '{{.State.ExitCode}}'
   ```

3. **Run interactive session for debugging:**
   ```bash
   docker run -it --env-file .env --mount type=bind,source=$(pwd)/logs,target=/app/logs allora-pipeline:latest bash
   ```

#### Issue: No logs being written

1. **Check volume mounts:**
   ```bash
   docker inspect allora-competition-pipeline --format '{{json .Mounts}}' | jq
   ```

2. **Verify logs directory exists:**
   ```bash
   docker exec allora-competition-pipeline ls -la /app/logs
   ```

3. **Check file permissions:**
   ```bash
   ls -la /path/to/allora-forge-builder-kit/logs/
   ```

#### Issue: .env not being loaded

1. **Verify .env file exists:**
   ```bash
   ls -la /path/to/allora-forge-builder-kit/.env
   ```

2. **Check .env content:**
   ```bash
   docker exec allora-competition-pipeline env | grep ALLORA
   ```

3. **Verify .env path in docker-compose.yml:**
   ```bash
   grep "env_file:" docker-compose.yml
   ```

---

## Method 3: Systemd Service (Alternative)

### Create Service File

```bash
sudo nano /etc/systemd/system/allora-pipeline.service
```

Add the following content:

```ini
[Unit]
Description=Allora Competition Submission Pipeline
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/allora-forge-builder-kit
EnvironmentFile=/home/ubuntu/allora-forge-builder-kit/.env
ExecStart=/home/ubuntu/allora-forge-builder-kit/.venv/bin/python -u competition_submission.py
Restart=always
RestartSec=300
StandardOutput=append:/home/ubuntu/allora-forge-builder-kit/logs/submission.log
StandardError=append:/home/ubuntu/allora-forge-builder-kit/logs/submission.log

[Install]
WantedBy=multi-user.target
```

### Enable and Start Service

```bash
# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable allora-pipeline.service

# Start the service
sudo systemctl start allora-pipeline.service

# Check status
sudo systemctl status allora-pipeline.service
```

### Monitor Systemd Service

```bash
# View service logs
sudo journalctl -u allora-pipeline.service -n 100

# Follow logs in real-time
sudo journalctl -u allora-pipeline.service -f

# Check service status
systemctl status allora-pipeline.service
```

---

## Comparison: Cron vs Docker vs Systemd

| Feature | Cron | Docker | Systemd |
|---------|------|--------|---------|
| Ease of Setup | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
| Cloud-Ready | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| Isolation | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| Portability | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ |
| Monitoring | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Log Management | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |

**Recommendation:**
- **Cron**: For existing Linux/EC2 instances with minimal overhead
- **Docker**: For cloud deployments, multiple environments, or Kubernetes
- **Systemd**: For permanent system services on modern Linux

---

## Production Checklist

### Before Going Live

- [ ] Environment variables configured (.env file)
- [ ] Wallet balance verified (non-zero ALLO tokens)
- [ ] RPC endpoints connectivity tested
- [ ] Model training verified with valid metrics
- [ ] Test submission successful (--once flag)
- [ ] Logs directory created and writable
- [ ] Log rotation script tested
- [ ] Health check script tested
- [ ] Prediction validation tested

### Cron Deployment

- [ ] Scripts made executable (chmod +x)
- [ ] Crontab entries added
- [ ] Cron jobs verified (crontab -l)
- [ ] Initial manual run successful
- [ ] Log output verified after first cycle
- [ ] Health monitoring configured

### Docker Deployment

- [ ] Docker image built successfully
- [ ] .env file in project root
- [ ] Logs directory permissions (755)
- [ ] docker-compose up -d successful
- [ ] All three containers running
- [ ] Volumes mounted correctly
- [ ] Logs being written to host

### Ongoing Operations

- [ ] Check logs daily for errors
- [ ] Monitor submission success rate
- [ ] Verify wallet balance remains sufficient
- [ ] Monitor disk space (logs can grow)
- [ ] Check for RPC connectivity issues
- [ ] Review health alerts weekly

---

## Performance Expectations

### Resource Usage (Single Cycle)

- **CPU**: 0.5-2 seconds per hour (~50ms of actual compute time)
- **Memory**: ~500MB peak during model training
- **Disk**: ~100KB per submission (CSV log entry + minimal I/O)
- **Network**: ~5-10KB per submission (RPC calls + submission)

### Disk Space Estimation

```
Base installation:      ~200 MB
Model artifacts:        ~50 MB
Logs per day:          ~100 KB (unrotated) → ~10 KB (compressed)
Logs per month:        ~3 MB (unrotated) → ~300 KB (compressed)
```

### Recommended Maintenance

- **Daily**: Check for errors in logs
- **Weekly**: Review health alerts and submission stats
- **Monthly**: Archive old logs, update code if needed
- **Quarterly**: Review model performance, consider retraining

---

## Emergency Procedures

### Pipeline Stopped

```bash
# Cron method
crontab -e  # Verify jobs are there

# Docker method
docker-compose restart

# Systemd method
sudo systemctl restart allora-pipeline.service
```

### High Error Rate

1. Check logs for specific errors:
   ```bash
   grep -i error /path/to/logs/submission.log | tail -20
   ```

2. Verify RPC connectivity:
   ```bash
   python diagnose_rpc_connectivity.py
   ```

3. Check wallet balance:
   ```bash
   python check_wallet.py
   ```

4. Test submission manually:
   ```bash
   python competition_submission.py --once
   ```

### Disk Space Critical

```bash
# Check space
df -h /home/ubuntu/allora-forge-builder-kit/logs

# Archive old logs
tar -czf logs_backup_$(date +%Y%m%d).tar.gz logs/submission*.log.gz

# Clean up (keep recent logs)
find logs/ -name "submission_*.log.gz" -mtime +30 -delete
```

---

## Support & Troubleshooting

For detailed diagnostics, run:

```bash
# Overall system check
python quick_health_check.py

# Detailed RPC diagnostics
python diagnose_rpc_connectivity.py

# Wallet check
python check_wallet.py

# Test API key flow
python test_api_key_flow.py
```

For more information, see:
- `QUICK_REFERENCE.md` - Common commands
- `README.md` - Project overview
- `LEADERBOARD_VISIBILITY_GUIDE.md` - Leaderboard configuration
- `RPC_CONFIGURATION_UPDATE.md` - RPC endpoint details

---

## Next Steps

1. **Choose your deployment method** (Cron, Docker, or Systemd)
2. **Follow the installation steps** for your chosen method
3. **Verify everything is working** using the monitoring commands
4. **Set up alerts** via health check logs or external monitoring
5. **Test thoroughly** before going to production with real wallet

Good luck with your Allora competition pipeline! 🚀
