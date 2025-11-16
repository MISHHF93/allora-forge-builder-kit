# EC2 Instance Fix Guide

## Issue Detected

Your EC2 instance at `ubuntu@ip-172-31-23-75` is showing:
1. ❌ `allorad CLI not found` - Missing Allora CLI
2. ❌ `topic_validation_failed` - Can't validate topic without allorad
3. ⚠️ Running outdated code with UnboundLocalError bug

## Solution: Update Code & Install Dependencies

### Step 1: SSH into your EC2 instance
```bash
ssh -i allora-keypair.pem ubuntu@44.249.158.207
cd ~/allora-forge-builder-kit
```

### Step 2: Pull latest code with fixes
```bash
git pull origin main
# Or if you have local changes:
git stash
git pull origin main
git stash pop
```

### Step 3: Install Allora CLI (allorad)

**Option A: Quick install (if available)**
```bash
# Check if allorad is in apt
sudo apt update
sudo apt install -y allorad

# Verify installation
which allorad
allorad version
```

**Option B: Build from source** (if not in apt)
```bash
# Install dependencies
sudo apt update
sudo apt install -y build-essential git curl

# Install Go (required for building)
wget https://go.dev/dl/go1.21.5.linux-amd64.tar.gz
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf go1.21.5.linux-amd64.tar.gz
echo 'export PATH=$PATH:/usr/local/go/bin' >> ~/.bashrc
source ~/.bashrc

# Clone and build allorad
git clone https://github.com/allora-network/allora-chain.git
cd allora-chain
git checkout v0.3.0  # Use latest stable version
make install

# Verify
which allorad
allorad version
```

**Option C: Use Docker (alternative)**
```bash
# If allorad is available as Docker image
docker pull alloranetwork/allorad:latest
alias allorad='docker run --rm -v ~/.allora:/root/.allora alloranetwork/allorad:latest'
```

### Step 4: Configure allorad
```bash
# Initialize config if needed
allorad config set client chain-id allora-testnet-1
allorad config set client node https://testnet-rpc.lavenderfive.com:443/allora/

# Test connection
allorad q bank total
```

### Step 5: Alternative - Run with --force-submit to bypass validation

If you can't install allorad immediately, use `--force-submit` to bypass some validation checks:

```bash
cd ~/allora-forge-builder-kit

# Single submission test
python3 train.py --submit --force-submit --submit-timeout 300

# Or continuous loop
nohup python3 train.py --loop --submit --force-submit --submit-timeout 300 > pipeline.log 2>&1 &
```

**What `--force-submit` does:**
- ✅ Bypasses topic validation checks
- ✅ Bypasses cooldown guards
- ✅ Bypasses duplicate detection
- ⚠️ Still requires topic to be funded and active
- ⚠️ May submit even if conditions aren't ideal

### Step 6: Verify everything works

```bash
# Test a single submission
python3 train.py --submit --force-submit --submit-timeout 300 --as-of-now

# Check submission log
tail -5 submission_log.csv

# If successful, start loop
nohup python3 train.py --loop --submit --force-submit --submit-timeout 300 > pipeline.log 2>&1 &
echo $! > train.pid

# Monitor
tail -f pipeline.log
```

## Quick Commands Reference

### Check if process is running
```bash
ps aux | grep train.py
```

### Stop running process
```bash
pkill -f "python3 train.py"
# Or if you saved PID
kill $(cat train.pid)
```

### View logs
```bash
tail -f pipeline.log                    # Live logs
grep ERROR pipeline.log                 # Check errors
tail -20 submission_log.csv             # Recent submissions
```

### Monitor status
```bash
./monitor_status.sh
```

## Recommended Configuration for EC2

**Production setup** (with allorad installed):
```bash
nohup python3 train.py --loop --submit --submit-timeout 300 > pipeline.log 2>&1 &
```

**Fallback setup** (without allorad):
```bash
nohup python3 train.py --loop --submit --force-submit --submit-timeout 300 > pipeline.log 2>&1 &
```

## Troubleshooting

### If submissions still fail:

1. **Check wallet balance:**
```bash
allorad q bank balances allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
```

2. **Check topic status:**
```bash
allorad q emissions topic 67
```

3. **Verify .allora_key exists:**
```bash
ls -la ~/.allora_key
# Or in project directory
ls -la .allora_key
```

4. **Check API key in .env:**
```bash
grep ALLORA_API_KEY .env
```

5. **View detailed error logs:**
```bash
grep -A 10 "ERROR\|failed\|exception" pipeline.log | tail -50
```

## Success Indicators

✅ No "allorad CLI not found" warnings
✅ "Topic 67 validation: OK and funded" message
✅ "✅ Successfully submitted: topic=67 nonce=XXXXX"
✅ submission_log.csv shows success=true

## Need Help?

If issues persist:
1. Share the output of: `tail -100 pipeline.log`
2. Share recent submissions: `tail -10 submission_log.csv`
3. Check connectivity: `curl -s https://api.allora.network/v2/health`
