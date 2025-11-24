# AWS Instance Setup: Quick Reference

## Your Current Issues & Solutions

### Issue 1: "Failed to create wallet from mnemonic: Invalid mnemonic length"

**Your mnemonic in .env:**
```
tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random
```

**Check:**
```bash
# Count words (should be 24)
echo "tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random" | wc -w
# Output: 24 ✅ Correct

# Verify format in .env
cat .env | grep MNEMONIC
# Should show: MNEMONIC=tiger salmon health...
# NOT: MNEMONIC="tiger salmon health..."  (no quotes!)
```

**Fix if needed:**
```bash
# Edit .env and ensure NO QUOTES around mnemonic
nano .env

# Should look like:
# MNEMONIC=tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random
# ^^^^^^^  No quotes, no spaces around =
```

---

### Issue 2: "Query failed and lookup allora-testnet-rpc.allthatnode.com: no such host"

**This is a DNS/network issue, not a code issue.**

**Quick test:**
```bash
# Test DNS resolution
nslookup allora-testnet-rpc.allthatnode.com

# Test network connectivity
curl -I https://allora-rpc.testnet.allora.network/

# Check if internet is working
ping -c 3 8.8.8.8
```

**AWS Security Group Fix (if needed):**
```bash
# Check current security group rules
aws ec2 describe-security-groups --query 'SecurityGroups[0]' --region us-east-1

# Should allow:
# - Outbound HTTPS (443) to any
# - Outbound DNS (53) to any
```

**The daemon HANDLES this automatically!**
- If AllThatNode fails → tries ChandraStation
- If all fail → skips submission gracefully
- No action needed—the code already retries

---

### Issue 3: RPC Endpoints & Failover Strategy

**Your three endpoints (already configured):**
1. `https://allora-rpc.testnet.allora.network/` (Primary)
2. `https://allora-testnet-rpc.allthatnode.com:1317/` (Fallback 1)
3. `https://allora.api.chandrastation.com/` (Fallback 2)

**The daemon does this automatically:**
1. Tries Primary
2. On failure: Tries Fallback 1
3. On failure: Tries Fallback 2
4. On failure: Logs warning, skips submission, retries next cycle
5. Never crashes

**You don't need to configure anything—it's already built in.**

---

## Quick Start: Step-by-Step for AWS

### Step 1: Verify .env Format
```bash
cd ~/allora-forge-builder-kit

# Show .env contents
cat .env

# Verify MNEMONIC line (no quotes!)
grep "^MNEMONIC=" .env

# Verify WALLET line
grep "^ALLORA_WALLET_ADDR=" .env
```

### Step 2: Run Diagnostic
```bash
# This validates everything
python3 diagnose_env_wallet.py

# Output should show:
# ✅ .env file found
# ✅ MNEMONIC has 24 words
# ✅ All words are ASCII
# ✅ Wallet address starts with 'allo1'
# ✅ All required env vars set
```

### Step 3: Install allorad Binary
```bash
# Download correct binary for AWS (x86_64)
mkdir -p ~/.local/bin
curl -L https://github.com/allora-network/allora-chain/releases/download/v0.14.0/allora-chain_0.14.0_linux_amd64 \
  -o ~/.local/bin/allorad
chmod +x ~/.local/bin/allorad

# Verify
allorad version
```

### Step 4: Create Logs Directory
```bash
mkdir -p logs
touch logs/submission.log
```

### Step 5: Start the Daemon
```bash
# Kill any existing daemon
pkill -9 -f "submit_prediction.py --daemon" 2>/dev/null

# Start fresh daemon
nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &

# Verify it's running
ps aux | grep "submit_prediction.*--daemon" | grep -v grep
```

### Step 6: Monitor Logs
```bash
# Watch real-time logs
tail -f logs/submission.log

# Or just check latest entries
tail -20 logs/submission.log

# Check submission status
cat latest_submission.json | jq '.'

# Check CSV audit trail
tail -5 submission_log.csv
```

---

## What to Expect in Logs

### First Cycle (normal output):
```
2025-11-24 05:00:00Z - btc_submit - INFO - ================================================================================
2025-11-24 05:00:00Z - btc_submit - INFO - SUBMISSION CYCLE #1 - 2025-11-24T05:00:00.000245+00:00
2025-11-24 05:00:00Z - btc_submit - INFO - ================================================================================
2025-11-24 05:00:00Z - btc_submit - INFO - ✅ Loaded 10 feature columns
2025-11-24 05:00:00Z - btc_submit - DEBUG - ✅ Model deserialized successfully from model.pkl
2025-11-24 05:00:00Z - btc_submit - INFO - ✅ Model validation PASSED
2025-11-24 05:00:00Z - btc_submit - INFO - Fetching latest 168h BTC/USD data from Tiingo...
2025-11-24 05:00:00Z - btc_submit - INFO - Fetched 84 latest rows from Tiingo
2025-11-24 05:00:00Z - btc_submit - DEBUG - Generated features for 13 records
2025-11-24 05:00:00Z - btc_submit - INFO - Predicted 168h log-return: -0.02522540
2025-11-24 05:00:00Z - btc_submit - INFO - 🚀 LEADERBOARD SUBMISSION: Preparing prediction for topic 67
2025-11-24 05:00:00Z - btc_submit - INFO - ⚠️  No unfulfilled nonce available, skipping submission
2025-11-24 05:00:00Z - btc_submit - INFO - 📝 Logged submission to CSV
2025-11-24 05:00:00Z - btc_submit - DEBUG - Updated latest_submission.json with status: skipped_no_nonce
2025-11-24 05:00:00Z - btc_submit - INFO - Sleeping for 934s until next hourly boundary (06:00 UTC)
```

### This is NORMAL! Explanation:
- ✅ Model loads
- ✅ Data fetches
- ✅ Prediction generates
- ⚠️ No nonces available (expected)
- 📝 Status logged to CSV and JSON
- 💤 Sleeps 1 hour

### Only these are ERRORS (will show ❌):
```
❌ Failed to create wallet from mnemonic
❌ MNEMONIC not set
❌ Model validation failed
❌ Failed to fetch BTC/USD data
```

If you see these, something is actually wrong.

---

## Verify Everything is Working

```bash
# Command to verify setup
bash -c '
echo "=== Checking daemon ==="
ps aux | grep "submit_prediction.*--daemon" | grep -v grep && echo "✅ Daemon running" || echo "❌ Daemon not running"

echo ""
echo "=== Checking JSON status ==="
cat latest_submission.json | jq ".timestamp, .status"

echo ""
echo "=== Checking latest CSV ==="
tail -1 submission_log.csv

echo ""
echo "=== Checking logs for errors ==="
tail -10 logs/submission.log | grep -E "ERROR|CRITICAL" || echo "✅ No errors in last 10 lines"
'
```

---

## Common Issues & Immediate Fixes

| Issue | Fix |
|-------|-----|
| Daemon not starting | `nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &` |
| allorad not found | `curl -L ... -o ~/.local/bin/allorad && chmod +x ~/.local/bin/allorad` |
| .env not found | `ls -la .env` or create it with nano |
| MNEMONIC has quotes | Edit .env, remove quotes around mnemonic |
| RPC timeout errors | Normal, daemon handles it, will retry next cycle |
| "No unfulfilled nonce" | Normal, all nonces already submitted, will retry next cycle |

---

## Contact Info for Issues

If you get errors not listed above:
1. Run: `python3 diagnose_env_wallet.py`
2. Check: `tail -30 logs/submission.log | grep ERROR`
3. Read: `ENV_WALLET_TROUBLESHOOTING.md`

The daemon is designed to handle all failures gracefully. If it stops, systemd/supervisor can auto-restart it.

---

## Timeline

- **Now**: Daemon should be running hourly submissions
- **Nov 24 - Dec 15**: Pipeline submits predictions every hour (nonces permitting)
- **Dec 15, 1:00 PM**: Daemon gracefully stops (built-in feature)
- **Competition ends**: No more submissions after Dec 15

Your setup is complete!
