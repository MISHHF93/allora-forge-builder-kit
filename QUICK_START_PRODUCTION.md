# Quick Start - Production Deployment (5 Minutes)

Choose your deployment method below and follow the steps. Takes ~5 minutes to get running.

---

## 🚀 Option 1: Cron (Recommended for Linux/EC2)

### Time: 3 minutes

```bash
# Step 1: Make scripts executable
chmod +x /home/ubuntu/allora-forge-builder-kit/logs/rotate_logs.sh
chmod +x /home/ubuntu/allora-forge-builder-kit/logs/healthcheck.sh

# Step 2: Open crontab editor
crontab -e

# Step 3: Add these 3 lines (paste into editor):
0 * * * * /home/ubuntu/allora-forge-builder-kit/.venv/bin/python /home/ubuntu/allora-forge-builder-kit/competition_submission.py --once >> /home/ubuntu/allora-forge-builder-kit/logs/submission.log 2>&1
5 * * * * /home/ubuntu/allora-forge-builder-kit/logs/rotate_logs.sh >> /home/ubuntu/allora-forge-builder-kit/logs/submission.log 2>&1
10 * * * * /home/ubuntu/allora-forge-builder-kit/logs/healthcheck.sh >> /home/ubuntu/allora-forge-builder-kit/logs/submission.log 2>&1

# Step 4: Verify (exit editor first with Ctrl+X, then verify)
crontab -l

# Step 5: Test manually (optional, should run within 60 seconds from cron)
tail -f /home/ubuntu/allora-forge-builder-kit/logs/submission.log
```

### Verify It's Working

```bash
# Check logs
tail -20 /home/ubuntu/allora-forge-builder-kit/logs/submission.log

# See if it ran (after the next hour mark)
grep "submission successful" /home/ubuntu/allora-forge-builder-kit/logs/submission.log
```

---

## 🐳 Option 2: Docker (Recommended for Cloud)

### Time: 5 minutes

```bash
# Step 1: Build image
docker build -t allora-pipeline:latest .

# Step 2: Start services
docker-compose up -d

# Step 3: Wait 10 seconds for startup
sleep 10

# Step 4: Check status
docker ps
```

### Verify It's Working

```bash
# View logs
docker logs -f allora-competition-pipeline

# Check health
docker ps --format "table {{.Names}}\t{{.Status}}"

# See if it ran
docker logs allora-competition-pipeline | grep "submission successful"
```

### Useful Commands

```bash
# Stop all services
docker-compose stop

# Restart all services
docker-compose restart

# View all logs
docker-compose logs -f

# Remove everything
docker-compose down
```

---

## 🔧 Option 3: Systemd (Alternative for Linux)

### Time: 3 minutes

```bash
# Step 1: Create service file
sudo tee /etc/systemd/system/allora-pipeline.service > /dev/null << 'EOF'
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
EOF

# Step 2: Enable and start
sudo systemctl daemon-reload
sudo systemctl enable allora-pipeline.service
sudo systemctl start allora-pipeline.service

# Step 3: Check status
sudo systemctl status allora-pipeline.service
```

### Verify It's Working

```bash
# View logs
sudo journalctl -u allora-pipeline.service -f

# Check status
systemctl status allora-pipeline.service
```

---

## 📊 Monitoring (All Methods)

### Real-time Logs
```bash
# Cron or Systemd
tail -f /home/ubuntu/allora-forge-builder-kit/logs/submission.log

# Docker
docker logs -f allora-competition-pipeline
```

### Check Success Rate
```bash
# Count successes
grep -c "submission successful" /home/ubuntu/allora-forge-builder-kit/logs/submission.log

# Count failures
grep -c "failed\|error" /home/ubuntu/allora-forge-builder-kit/logs/submission.log
```

### View Metrics
```bash
# Latest status
cat /home/ubuntu/allora-forge-builder-kit/logs/healthcheck_status.log

# Alerts
cat /home/ubuntu/allora-forge-builder-kit/logs/healthcheck_alerts.log
```

---

## 🧪 Testing Before Production

### Test Manual Submission
```bash
# Cron/Systemd method
/home/ubuntu/allora-forge-builder-kit/.venv/bin/python /home/ubuntu/allora-forge-builder-kit/competition_submission.py --once

# Docker method
docker run --env-file .env -v $(pwd)/logs:/app/logs allora-pipeline:latest python competition_submission.py --once
```

### Verify Wallet
```bash
python check_wallet.py
```

### Test RPC Connectivity
```bash
python diagnose_rpc_connectivity.py
```

---

## ✅ Production Checklist

Before going live, verify:

- [ ] `.env` file has ALLORA_WALLET_ADDR and TOPIC_ID
- [ ] Wallet has non-zero ALLO balance
- [ ] Test submission successful (--once flag)
- [ ] Logs directory exists and is writable
- [ ] Cron jobs added and verified (if using Cron)
- [ ] Docker services running (if using Docker)
- [ ] Systemd service enabled and running (if using Systemd)

---

## 🚨 Troubleshooting

### No logs appearing?

```bash
# Check if script/service is running
ps aux | grep competition_submission

# Check .env file
cat /home/ubuntu/allora-forge-builder-kit/.env | head -3

# Test manually
/home/ubuntu/allora-forge-builder-kit/.venv/bin/python /home/ubuntu/allora-forge-builder-kit/competition_submission.py --once
```

### Low wallet balance?

```bash
# Check balance
python check_wallet.py

# Fund wallet with more ALLO tokens
# See: https://testnet.allora.network/
```

### Cron not running?

```bash
# Verify crontab
crontab -l

# Check cron logs
sudo grep cron /var/log/syslog | tail -20

# Verify scripts are executable
ls -l /home/ubuntu/allora-forge-builder-kit/logs/*.sh
```

### Docker containers failing?

```bash
# Check logs
docker logs allora-competition-pipeline

# Check if .env exists
ls -la .env

# Rebuild image
docker build --no-cache -t allora-pipeline:latest .

# Restart
docker-compose restart
```

---

## 📈 What to Expect

### Per Hour
- 1 submission to leaderboard
- ~100KB of logs (rotated and compressed)
- 50-100ms of CPU time
- 200-500MB of RAM peak

### Per Day
- 24 submissions (if running 24/7)
- ~2.4MB of uncompressed logs
- ~240KB of compressed logs
- 1.2-2.4 seconds of total compute time

### Per Month
- 720 submissions
- ~72MB of uncompressed logs
- ~7.2MB of compressed logs
- 30-60 seconds of total compute time

---

## 🔗 Important Links

- **Full Deployment Guide**: See `PRODUCTION_DEPLOYMENT_GUIDE.md`
- **Enhancement Summary**: See `PRODUCTION_ENHANCEMENT_SUMMARY.md`
- **Project README**: See `README.md`
- **RPC Configuration**: See `RPC_CONFIGURATION_UPDATE.md`
- **Leaderboard Help**: See `LEADERBOARD_VISIBILITY_GUIDE.md`

---

## 💡 Tips

1. **Start with Cron** if you're on Linux/EC2 (simplest)
2. **Use Docker** if you need portability or cloud deployment
3. **Use Systemd** if you want permanent system integration
4. **Monitor daily** for the first week
5. **Check wallet balance** weekly
6. **Review logs** for patterns and optimization opportunities

---

## ✨ Ready?

Pick your method above and follow the steps. Should take ~5 minutes to get running.

Questions? See `PRODUCTION_DEPLOYMENT_GUIDE.md` for detailed instructions.

Good luck! 🚀
