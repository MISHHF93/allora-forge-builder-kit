# 🎯 ALLORA SETUP MASTER CHECKLIST: AWS INSTANCE

Use this checklist to set up your Allora BTC/USD prediction pipeline on AWS.

---

## ✅ PRE-FLIGHT CHECKS (5 minutes)

- [ ] **SSH into AWS instance**
  ```bash
  ssh -i your-key.pem ubuntu@your-instance-ip
  ```

- [ ] **Navigate to repository**
  ```bash
  cd ~/allora-forge-builder-kit
  pwd  # Should show: /home/ubuntu/allora-forge-builder-kit
  ```

- [ ] **Confirm .env file exists**
  ```bash
  cat .env | head -6
  # Should show: ALLORA_API_KEY, TIINGO_API_KEY, etc.
  ```

- [ ] **Check Python 3 installed**
  ```bash
  python3 --version  # Should be 3.10+
  ```

- [ ] **Confirm virtual environment activated**
  ```bash
  which python3  # Should show: /home/ubuntu/allora-forge-builder-kit/.venv/bin/python3
  ```

---

## 📋 VALIDATE .env FORMAT (10 minutes)

- [ ] **Open .env file**
  ```bash
  nano .env
  ```

- [ ] **Check each line format:**
  - [ ] No quotes around any values
  - [ ] No spaces around `=` sign
  - [ ] MNEMONIC line has 24 words (count them!)
  - [ ] ALLORA_WALLET_ADDR starts with `allo1`
  - [ ] No trailing spaces on lines

- [ ] **Correct format (no changes needed if like this):**
  ```
  ALLORA_API_KEY=UP-7f3bc941663748fa84f38dc6
  TIINGO_API_KEY=101fdad53607e7fc6a2cba726b01afe21a241134
  ALLORA_WALLET_ADDR=allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
  TOPIC_ID=67
  MNEMONIC=tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random
  RPC_URL=https://allora-rpc.testnet.allora.network/
  ```

- [ ] **Save and exit** (Ctrl+X, Y, Enter if using nano)

---

## 🔐 RUN DIAGNOSTIC (10 minutes)

- [ ] **Run comprehensive diagnostic**
  ```bash
  python3 diagnose_env_wallet.py
  ```

- [ ] **Check output for:**
  - [ ] ✅ .env file found
  - [ ] ✅ MNEMONIC has 24 words
  - [ ] ✅ All words are ASCII
  - [ ] ✅ Wallet address starts with 'allo1'
  - [ ] ✅ All required env vars set
  - [ ] ✅ At least 1 RPC endpoint responsive

- [ ] **If diagnostic fails:**
  - [ ] Re-read error messages carefully
  - [ ] Check .env format again
  - [ ] See ENV_WALLET_TROUBLESHOOTING.md for help

---

## 🚀 INSTALL ALLORAD BINARY (5 minutes)

- [ ] **Run installation script**
  ```bash
  bash install_allorad.sh
  ```

- [ ] **Verify installation**
  ```bash
  allorad version
  # Should print version information without error
  ```

- [ ] **Add to PATH if needed**
  ```bash
  export PATH="$HOME/.local/bin:$PATH"
  # Or add permanently to ~/.bashrc
  ```

---

## 📁 CREATE REQUIRED DIRECTORIES (2 minutes)

- [ ] **Create logs directory**
  ```bash
  mkdir -p logs
  ```

- [ ] **Create log file**
  ```bash
  touch logs/submission.log
  ```

- [ ] **Verify**
  ```bash
  ls -la logs/submission.log
  # Should show: -rw-r--r-- ubuntu ubuntu logs/submission.log
  ```

---

## 🔄 KILL EXISTING PROCESSES (3 minutes)

- [ ] **Kill any old daemon instances**
  ```bash
  pkill -9 -f "submit_prediction.py" 2>/dev/null
  sleep 2
  ```

- [ ] **Verify nothing running**
  ```bash
  ps aux | grep "submit_prediction" | grep -v grep
  # Should show nothing (empty output)
  ```

---

## 🎬 START DAEMON (5 minutes)

- [ ] **Start the daemon in background**
  ```bash
  nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &
  ```

- [ ] **Verify it started**
  ```bash
  sleep 2
  ps aux | grep "submit_prediction.*--daemon" | grep -v grep
  # Should show: python3 submit_prediction.py --daemon
  ```

- [ ] **Check PID is created**
  ```bash
  ps aux | grep submit_prediction | grep daemon | awk '{print $2}'
  # Should show a number (e.g., 12345)
  ```

---

## 📊 MONITOR INITIAL RUN (10 minutes)

- [ ] **Watch logs in real-time**
  ```bash
  tail -f logs/submission.log
  # Press Ctrl+C after 30 seconds to exit
  ```

- [ ] **Look for these success indicators:**
  - [ ] "✅ Loaded 10 feature columns"
  - [ ] "✅ Model deserialized successfully"
  - [ ] "✅ Model validation PASSED"
  - [ ] "Fetched 84 latest rows from Tiingo"
  - [ ] "Predicted 168h log-return: -0.xxx"
  - [ ] "Sleeping for Xs until next hourly boundary"

- [ ] **Expected warning (NOT an error):**
  - [ ] "⚠️ No unfulfilled nonce available, skipping submission"

- [ ] **If you see these errors:**
  - [ ] ❌ "Failed to create wallet from mnemonic" → .env MNEMONIC wrong
  - [ ] ❌ "MNEMONIC not set" → .env missing MNEMONIC line
  - [ ] ❌ "Model validation failed" → Run: python3 train.py

---

## 📋 VERIFY SUBMISSION FILES (5 minutes)

- [ ] **Check JSON status file**
  ```bash
  cat latest_submission.json | jq '.'
  ```
  Should show:
  ```json
  {
    "timestamp": "2025-11-24T...",
    "topic_id": 67,
    "prediction": -0.xxx,
    "status": "skipped_no_nonce",
    ...
  }
  ```

- [ ] **Check CSV audit trail**
  ```bash
  tail -3 submission_log.csv
  ```
  Should show entries with timestamp, topic, prediction, status

- [ ] **Verify timestamps are recent**
  ```bash
  cat latest_submission.json | jq '.timestamp'
  # Should show current time, not old time
  ```

---

## 🎯 CONFIGURE FOR CONTINUOUS MONITORING (10 minutes)

- [ ] **Add to crontab for auto-restart (optional but recommended)**
  ```bash
  crontab -e
  
  # Add this line (checks every 5 minutes):
  */5 * * * * ps aux | grep -q "submit_prediction.*--daemon" || \
    (cd /home/ubuntu/allora-forge-builder-kit && \
     nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &)
  ```

- [ ] **Create monitoring script (optional)**
  ```bash
  cat > monitor.sh << 'EOF'
  #!/bin/bash
  echo "=== Daemon Status ==="
  ps aux | grep "submit_prediction.*--daemon" | grep -v grep || echo "Not running"
  echo ""
  echo "=== Latest Submission ==="
  cat latest_submission.json | jq '.timestamp, .status'
  echo ""
  echo "=== Recent Errors ==="
  tail -20 logs/submission.log | grep -i error || echo "No errors"
  EOF
  chmod +x monitor.sh
  ```

- [ ] **Test monitoring script**
  ```bash
  ./monitor.sh
  ```

---

## 🔔 SCHEDULE PERIODIC CHECKS (5 minutes)

- [ ] **Daily check command (bookmark this):**
  ```bash
  tail -50 logs/submission.log | tail -20
  ```

- [ ] **Weekly CSV review:**
  ```bash
  tail -100 submission_log.csv | grep -c "success"
  # Shows count of successful submissions
  ```

- [ ] **Check daemon health:**
  ```bash
  ps aux | grep "submit_prediction.*--daemon" | grep -v grep && \
    echo "✅ Daemon running" || echo "❌ Daemon stopped - restart with: nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &"
  ```

---

## 📝 DOCUMENT YOUR SETUP

- [ ] **Save these key values (keep secure!):**
  - [ ] AWS Instance IP: `___________________`
  - [ ] Wallet Address: `allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma`
  - [ ] Topic ID: `67`
  - [ ] Daemon Start Time: `___________________`
  - [ ] Expected Completion: `2025-12-15 13:00 UTC`

- [ ] **Document any customizations:**
  - [ ] Changed RPC endpoints? List them: `___________________`
  - [ ] Changed topic ID? New value: `___________________`
  - [ ] Custom alert email? Set up? `___________________`

---

## ✨ FINAL VERIFICATION (10 minutes)

- [ ] **Run complete health check:**
  ```bash
  bash << 'BASH_SCRIPT'
  echo "=== ALLORA PIPELINE HEALTH CHECK ==="
  echo ""
  echo "1. Daemon process:"
  ps aux | grep "submit_prediction.*--daemon" | grep -v grep && echo "   ✅ Running" || echo "   ❌ Not running"
  
  echo ""
  echo "2. allorad binary:"
  which allorad > /dev/null && echo "   ✅ Found" || echo "   ❌ Not in PATH"
  
  echo ""
  echo "3. Latest JSON timestamp:"
  cat latest_submission.json | jq '.timestamp'
  
  echo ""
  echo "4. Model file:"
  [ -f model.pkl ] && echo "   ✅ Exists" || echo "   ❌ Missing"
  
  echo ""
  echo "5. Features file:"
  [ -f features.json ] && echo "   ✅ Exists" || echo "   ❌ Missing"
  
  echo ""
  echo "6. Recent submissions (last 5):"
  tail -5 submission_log.csv | cut -d',' -f1,2,8
  
  BASH_SCRIPT
  ```

- [ ] **All checks passed?**
  - [ ] ✅ YES → Go to "SETUP COMPLETE"
  - [ ] ❌ NO → Check "Troubleshooting" section below

---

## 🎉 SETUP COMPLETE!

Your Allora BTC/USD prediction pipeline is now:
- ✅ Running on your AWS instance
- ✅ Submitting predictions hourly (nonces permitting)
- ✅ Logging all activity to CSV and JSON
- ✅ Automatically handling RPC failover
- ✅ Gracefully skipping when no nonces available

**The daemon will run until December 15, 2025 at 1:00 PM UTC**

---

## 🆘 TROUBLESHOOTING QUICK REFERENCE

**Daemon not starting?**
```bash
# Check for errors
python3 submit_prediction.py --once
# See what fails, fix it, then run daemon
```

**"Invalid mnemonic length" error?**
```bash
# Count words
echo "YOUR_MNEMONIC_HERE" | wc -w
# Should be 24
```

**RPC timeout errors?**
```bash
# Normal temporary issue, daemon handles it
# Check logs: tail -20 logs/submission.log | grep ERROR
```

**Daemon crashes?**
```bash
# Restart immediately
nohup python3 submit_prediction.py --daemon > logs/submission.log 2>&1 &
# Add to crontab for auto-restart (see checklist above)
```

**No submissions in CSV?**
```bash
# Check if nonces available (expected to skip sometimes)
tail -5 submission_log.csv | cut -d',' -f8
# Should show status (success or skipped_no_nonce)
```

**Lost SSH connection?**
```bash
# daemon keeps running (nohup protects it)
# Reconnect and check: ps aux | grep submit_prediction
```

---

## 📚 ADDITIONAL RESOURCES

If you need more help:
1. **ENV_WALLET_TROUBLESHOOTING.md** - Detailed troubleshooting
2. **AWS_QUICK_START.md** - Step-by-step AWS guide
3. **CODE_ANALYSIS_ENV_VALIDATION.md** - Technical details
4. **SETUP_COMPLETE_GUIDE.md** - Comprehensive overview

---

## 🎯 SUCCESS CRITERIA

You've completed setup when:
- ✅ Daemon process is running (check with ps)
- ✅ latest_submission.json has recent timestamp
- ✅ submission_log.csv has entries from today
- ✅ Logs show "Sleeping for Xs until next boundary" (not errors)
- ✅ Can SSH in and see daemon still running

**Estimated time to complete all steps: 1-2 hours**

---

Good luck with the Allora prediction competition! 🚀
