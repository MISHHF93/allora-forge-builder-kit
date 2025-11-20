# AWS Deployment Guide - Allora Forge Builder Kit

## Quick Start Prompt for AWS Instance

```bash
# Copy this entire block and paste into your AWS EC2 instance terminal

# ============================================================================
# ALLORA FORGE - AWS PRODUCTION DEPLOYMENT
# Topic 67: 7-Day BTC/USD Log-Return Prediction
# Competition: Sep 16 - Dec 15, 2025 (Hourly Submissions)
# ============================================================================

# 1. CLONE REPOSITORY
cd ~
git clone https://github.com/MISHHF93/allora-forge-builder-kit.git
cd allora-forge-builder-kit

# 2. INSTALL DEPENDENCIES
# Ensure Python 3.8+ is installed
python3 --version

# Install required packages
pip install -r requirements.txt

# Install allorad CLI (if not already installed)
# Follow: https://docs.allora.network/devs/get-started/setup-wallet

# 3. CONFIGURE WALLET & API KEY
# Set your Allora wallet mnemonic (CRITICAL - keep secure!)
echo "your 24-word mnemonic phrase here" > .allora_key
chmod 600 .allora_key

# Set your Allora API key for data fetching (optional but recommended)
export ALLORA_API_KEY="your_api_key_here"
echo 'export ALLORA_API_KEY="your_api_key_here"' >> ~/.bashrc

# Set your wallet address for submissions
export ALLORA_WALLET_ADDR="allo1your_wallet_address_ending_in_6vma"
echo 'export ALLORA_WALLET_ADDR="allo1your_wallet_address_ending_in_6vma"' >> ~/.bashrc

# 4. VERIFY CONFIGURATION
python3 tools/print_wallet_address.py  # Should match your wallet address
python3 -c "import train; print('✅ train.py imports successfully')"

# 5. TEST SINGLE RUN (Optional - verify before loop)
python3 train.py --once --submit

# 6. START PRODUCTION WORKER
./start_worker.sh

# 7. MONITOR WORKER
./monitor.sh                  # Quick status snapshot
./watch_live.sh               # Live monitoring (Ctrl+C to exit)
tail -f pipeline_run.log      # Follow logs in real-time

# 8. VERIFY SUBMISSIONS
tail submission_log.csv       # Check submission history

# ============================================================================
# PRODUCTION WORKER NOW RUNNING
# - Training every hour with 28-day BTC/USD history
# - Submitting predictions at HH:00:00 UTC when window opens
# - Automatic operation through December 15, 2025
# ============================================================================
```

---

## Detailed Setup Instructions

### Prerequisites

#### 1. AWS EC2 Instance Requirements
- **Instance Type**: t3.medium or larger (minimum 2 vCPU, 4GB RAM)
- **OS**: Ubuntu 22.04 LTS or Amazon Linux 2023
- **Storage**: 20GB+ EBS volume
- **Security Group**: 
  - Outbound: Allow all (for API calls to Allora network)
  - Inbound: SSH (port 22) only from your IP

#### 2. System Packages
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.10+
sudo apt install -y python3 python3-pip python3-venv

# Install Git
sudo apt install -y git

# Install system dependencies
sudo apt install -y build-essential libssl-dev libffi-dev python3-dev
```

#### 3. Install Allorad CLI
```bash
# Download and install allorad (Allora blockchain CLI)
# Follow official docs: https://docs.allora.network/devs/get-started/setup-wallet

# Verify installation
allorad version
```

---

### Configuration Files

#### 1. Wallet Configuration (`.allora_key`)
```bash
# Create wallet file with your 24-word mnemonic
cat > .allora_key << 'EOF'
word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12 word13 word14 word15 word16 word17 word18 word19 word20 word21 word22 word23 word24
EOF

chmod 600 .allora_key
```

#### 2. Environment Variables
```bash
# Add to ~/.bashrc for persistence
cat >> ~/.bashrc << 'EOF'

# Allora Configuration
export ALLORA_API_KEY="your_api_key_from_allora_dashboard"
export ALLORA_WALLET_ADDR="allo1xxxxxxxxxxxxxxxxxxxxxxxxxx6vma"
export ALLORA_RPC_URL="https://allora-testnet-rpc.polkachu.com:443"
export ALLORA_REST_URL="https://testnet-rest.lavenderfive.com:443/allora/"

EOF

source ~/.bashrc
```

#### 3. Verify Configuration
```bash
# Check Python imports
python3 -c "import train; print('✅ Configuration valid')"

# Print wallet address
python3 tools/print_wallet_address.py

# Test topic query
allorad q emissions topic 67 --node https://allora-testnet-rpc.polkachu.com:443
```

---

### Deployment

#### Option 1: Quick Start (Recommended)
```bash
cd ~/allora-forge-builder-kit
./start_worker.sh
```

**What this does:**
- Cleans any stale PIDs
- Verifies configuration
- Checks for critical bug fixes
- Starts worker in loop mode
- Saves PID to `pipeline.pid`
- Logs to `pipeline_run.log`

#### Option 2: Manual Start
```bash
cd ~/allora-forge-builder-kit

# Start worker in background with nohup
nohup python3 train.py --loop --schedule-mode loop --submit > pipeline_run.log 2>&1 &

# Save PID
echo $! > pipeline.pid

# Verify running
ps -p $(cat pipeline.pid)
```

#### Option 3: Systemd Service (Production)
```bash
# Create systemd service file
sudo tee /etc/systemd/system/allora-worker.service > /dev/null << 'EOF'
[Unit]
Description=Allora Forge Worker - Topic 67
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/allora-forge-builder-kit
Environment="ALLORA_API_KEY=your_api_key_here"
Environment="ALLORA_WALLET_ADDR=allo1xxxxxxxxx6vma"
ExecStart=/usr/bin/python3 train.py --loop --schedule-mode loop --submit
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/allora-forge-builder-kit/pipeline_run.log
StandardError=append:/home/ubuntu/allora-forge-builder-kit/pipeline_run.log

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable allora-worker.service
sudo systemctl start allora-worker.service

# Check status
sudo systemctl status allora-worker.service

# View logs
sudo journalctl -u allora-worker.service -f
```

---

### Monitoring

#### Real-Time Monitoring
```bash
# Live dashboard (refreshes every 5 seconds)
./watch_live.sh

# Quick status snapshot
./monitor.sh

# Follow logs
tail -f pipeline_run.log

# Follow with 501 filtering
tail -f pipeline_run.log | grep -v "REST query non-200"
```

#### Check Submissions
```bash
# View recent submissions
tail -20 submission_log.csv

# Count successful submissions
grep "True" submission_log.csv | wc -l

# Check latest submission
tail -1 submission_log.csv
```

#### System Health
```bash
# Check worker process
ps aux | grep "python.*train"

# Check memory usage
free -h

# Check disk space
df -h

# Check network connectivity
ping -c 3 allora-testnet-rpc.polkachu.com
```

---

### Troubleshooting

#### Worker Not Starting
```bash
# Check for errors
cat pipeline_run.log | tail -50

# Verify Python dependencies
pip install -r requirements.txt

# Check wallet file
ls -la .allora_key
cat .allora_key  # Should show 24 words

# Verify environment variables
echo $ALLORA_API_KEY
echo $ALLORA_WALLET_ADDR
```

#### Submission Failures
```bash
# Check submission log
tail -20 submission_log.csv

# Common issues:
# 1. "skipped_window" - Submission window closed (wait for next hour)
# 2. "skipped_topic_not_ready" - Topic not active or insufficient stake
# 3. "filtered_high_loss" - Model loss too high (top 25% filter active)
# 4. "cooldown_600s" - Recent submission within 10 minutes

# Check lifecycle state
ls -lt data/artifacts/logs/lifecycle-*.json | head -1 | xargs cat | jq '.'
```

#### HTTP 501 Errors
```bash
# These are EXPECTED and handled gracefully
# Pipeline uses fallback values:
# - reputers_count=1
# - delegated_stake=0.0

# Verify fallback mode is working
tail -f pipeline_run.log | grep -E "(fallback|INFO.*endpoint not implemented)"
```

#### Restart Worker
```bash
# Stop current worker
pkill -f "python.*train"

# Clean PID file
rm -f pipeline.pid

# Restart
./start_worker.sh
```

---

### Maintenance

#### Update Code
```bash
cd ~/allora-forge-builder-kit

# Stop worker
pkill -f "python.*train"

# Pull latest changes
git pull origin main

# Reinstall dependencies (if updated)
pip install -r requirements.txt

# Restart worker
./start_worker.sh
```

#### Rotate Logs
```bash
# Archive old log
mv pipeline_run.log pipeline_run_$(date +%Y%m%d_%H%M%S).log

# Start fresh (worker will create new log)
./start_worker.sh
```

#### Backup Configuration
```bash
# Backup wallet and logs
tar -czf allora_backup_$(date +%Y%m%d).tar.gz \
  .allora_key \
  submission_log.csv \
  pipeline_run.log \
  data/artifacts/

# Download to local machine
scp -i your-key.pem ubuntu@your-ec2-ip:~/allora_backup_*.tar.gz .
```

---

### Production Checklist

Before leaving worker unattended:

- [ ] Worker PID saved in `pipeline.pid`
- [ ] Worker process visible in `ps aux | grep train`
- [ ] `pipeline_run.log` showing iteration messages
- [ ] `submission_log.csv` being updated
- [ ] Wallet address matches in `tools/print_wallet_address.py`
- [ ] Environment variables set in `~/.bashrc`
- [ ] `.allora_key` file exists and is readable (chmod 600)
- [ ] Latest commits include:
  - [ ] Window detection fix (blocks not seconds)
  - [ ] HTTP 501 graceful handling
  - [ ] Scheduling visibility improvements
- [ ] No error messages in recent logs (last 50 lines)
- [ ] Monitoring tools working (`./monitor.sh`, `./watch_live.sh`)

---

### Key Files Reference

| File | Purpose |
|------|---------|
| `train.py` | Main pipeline script (4900+ lines) |
| `start_worker.sh` | Worker startup script with health checks |
| `monitor.sh` | Quick status snapshot |
| `watch_live.sh` | Live monitoring dashboard |
| `pipeline.pid` | Current worker process ID |
| `pipeline_run.log` | Main execution log |
| `submission_log.csv` | All submission attempts with results |
| `.allora_key` | Wallet mnemonic (24 words) - KEEP SECURE |
| `config/pipeline.yaml` | Competition schedule configuration |
| `data/artifacts/logs/` | Lifecycle JSON files for debugging |
| `requirements.txt` | Python dependencies |

---

### Expected Behavior

#### Normal Operation
```
2025-11-20 08:00:00Z - INFO - [loop] iteration=12 start at 2025-11-20T08:00:00Z
2025-11-20 08:00:01Z - INFO - REST endpoint not implemented (rest_topic_status): status=501 (using fallback)
2025-11-20 08:00:02Z - INFO - REST API fallback mode: 4 endpoint(s) not implemented (501)...
2025-11-20 08:00:03Z - INFO - Topic 67: Fallback reputers_count=1 (topic exists but no reputer data)
2025-11-20 08:00:03Z - INFO - Topic 67: Using fallback delegated_stake=0.0 (REST endpoints unavailable)
... [training and prediction] ...
2025-11-20 08:02:45Z - INFO - [loop] iteration=12 completed with rc=0 in 165.3s
2025-11-20 08:02:45Z - INFO - 💤 Sleeping 57.2 minutes until next cycle at 09:00:00 UTC...
```

#### Successful Submission
```
✅ Iteration 12 completed (rc=0, duration=165.3s)
📝 Logged submission attempt: status=success, value=0.0234567890, loss=-1.234567
Transaction hash: 1234ABCD5678EF90...
```

#### Graceful Skips
```
⏸️  SKIPPED: Submission skipped: topic not ready for submission due to: submission_window_closed(remaining=850)
💡 TIP: Submission window opens in ~20.8 minutes. Use --loop mode to auto-retry.
```

---

## Competition Details

- **Topic ID**: 67
- **Task**: 7-Day BTC/USD Log-Return Prediction
- **Competition Period**: September 16, 2025 13:00 UTC → December 15, 2025 13:00 UTC
- **Cadence**: Hourly (submissions at HH:00:00 UTC)
- **Submission Window**: Last 600 blocks of each 720-block epoch (~50 minutes)
- **Training Data**: 28-day rolling window of BTC/USD OHLCV
- **Model**: XGBoost with histogram gradient boosting
- **Features**: ~331 unique features (content-based deduplication)

---

## Critical Configuration Flags

The worker runs with these flags (handled by `start_worker.sh`):

```bash
python3 train.py --loop --schedule-mode loop --submit
```

- `--loop`: Continuous execution mode (runs until interrupted)
- `--schedule-mode loop`: Use schedule from `config/pipeline.yaml`
- `--submit`: Enable automatic submission of predictions

**DO NOT use `--force-submit` in production** - it bypasses safety guards.

---

## Success Criteria

Your deployment is successful when:

1. ✅ Worker process running continuously (`ps aux | grep train`)
2. ✅ Log shows hourly iteration messages at HH:00:00 UTC
3. ✅ `submission_log.csv` being updated every hour
4. ✅ No crash errors in `pipeline_run.log`
5. ✅ Fallback mode handling REST 501s gracefully
6. ✅ Submission attempts showing valid statuses (success/skipped/filtered)

---

## Support

- **Documentation**: See `README.md`, `PIPELINE_READY.md`, `HTTP_501_HANDLING.md`
- **Logs**: `pipeline_run.log` (main), `data/artifacts/logs/lifecycle-*.json` (debug)
- **Status Tools**: `./monitor.sh`, `./watch_live.sh`

---

**Last Updated**: November 20, 2025  
**Version**: Production Ready (commits: 8154c00, ae2ead3, 6afc99f)  
**Status**: ✅ Deployed and tested in dev container, ready for AWS
