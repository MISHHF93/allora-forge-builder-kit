# Allora Pipeline - Quick Start & Operations Guide

## 🚀 Quick Start (60 seconds)

### 1. Start the Pipeline
```bash
cd /workspaces/allora-forge-builder-kit
./start_pipeline.sh
```

**Expected Output**:
```
✅ Pipeline started successfully
   PID: <process-id>
   Log file: /workspaces/allora-forge-builder-kit/logs/submission.log
```

### 2. Monitor in Real-Time
```bash
tail -f logs/submission.log
```

**Watch for**:
- ✅ "Wallet initialized from LocalWallet"
- ✅ "Submission successful!"
- ⏳ "Waiting 1 hour until next submission..."

### 3. Verify Submissions
```bash
tail -5 competition_submissions.csv
```

---

## 📊 System Status

### Current Pipeline Status
```bash
ps aux | grep competition_submission.py
```

### View Recent Logs (last 100 lines)
```bash
tail -100 logs/submission.log
```

### Check Submission History
```bash
wc -l competition_submissions.csv
```

---

## ⚙️ Configuration

### Environment Variables (.env)
```
MNEMONIC=tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random
ALLORA_WALLET_ADDR=allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
TOPIC_ID=67
ALLORA_API_KEY=UP-7f3bc94...
TIINGO_API_KEY=101fdad53607e7fc6a2cba726b01afe21a241134
```

### RPC Endpoints (Priority Order)
1. **Primary (gRPC)**: `grpc+https://allora-grpc.testnet.allora.network:443/`
2. **Secondary (Tendermint)**: `https://allora-rpc.testnet.allora.network`
3. **Tertiary (Ankr)**: `https://rpc.ankr.com/allora_testnet` (offline)

### Wallet Status
```
Address: allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
Balance: 0.2513 ALLO (non-zero ✅)
Status: Ready for submissions
```

---

## 📋 Operation Modes

### Mode 1: Continuous Submissions (Default)
```bash
./start_pipeline.sh
```
- Runs until deadline (2025-12-15 13:00 UTC)
- Submits every 1 hour
- Background process (nohup)
- Logs to: `logs/submission.log`

### Mode 2: Single Submission
```bash
cd /workspaces/allora-forge-builder-kit
python3 competition_submission.py --once
```
- One submission cycle only
- Foreground execution
- Useful for testing

### Mode 3: Dry-Run (No Submission)
```bash
cd /workspaces/allora-forge-builder-kit
python3 competition_submission.py --once --dry-run
```
- Tests pipeline without submitting
- Verifies RPC connectivity
- Confirms environment setup

---

## 🛑 Stop the Pipeline

### Option 1: Kill by Process Name
```bash
pkill -f 'competition_submission.py'
```

### Option 2: Kill by PID
```bash
kill $(cat logs/pipeline.pid)
```

### Option 3: Verify Stopped
```bash
ps aux | grep competition_submission.py
```

**Expected**: Process should disappear from output

---

## 🔍 Troubleshooting

### Issue: "Wallet credentials not set"
**Solution**: Ensure `.env` file has MNEMONIC and ALLORA_WALLET_ADDR
```bash
cat .env | grep -E 'MNEMONIC|ALLORA_WALLET_ADDR'
```

### Issue: "Unable to fetch data from configured RPC endpoints"
**Solution**: Check RPC connectivity (auto-fallback in place)
```bash
python3 -c "from allora_forge_builder_kit.rpc_utils import diagnose_rpc_connectivity; import pprint; pprint.pprint(diagnose_rpc_connectivity())"
```

### Issue: "Already submitted for this epoch"
**This is EXPECTED** - Topic 67 allows one submission per epoch per worker  
✅ Normal behavior - pipeline continues to next hour

### Issue: "Invalid mnemonic length"
**Solution**: Verify mnemonic is exactly 24 words
```bash
echo $MNEMONIC | wc -w
```

### Issue: Pipeline logs growing large
**Solution**: Rotate logs periodically
```bash
# Archive logs
tar -czf logs/submission.log.$(date +%Y%m%d).tar.gz logs/submission.log
# Start fresh
> logs/submission.log
```

---

## 📈 Monitoring Checklist

### Daily Health Check
```bash
#!/bin/bash
echo "=== Pipeline Status ==="
ps aux | grep competition_submission.py | grep -v grep
echo ""
echo "=== Latest Logs ==="
tail -5 logs/submission.log
echo ""
echo "=== Submissions Today ==="
grep "$(date +%Y-%m-%d)" competition_submissions.csv | wc -l
```

### Weekly Health Check
```bash
# Check total submissions
wc -l competition_submissions.csv

# Verify no errors (should be empty)
grep -i "error\|failed" logs/submission.log | tail -10

# Check wallet balance
tail -20 logs/submission.log | grep "balance"
```

---

## 📊 Submission Tracking

### View All Submissions
```bash
cat competition_submissions.csv
```

### CSV Format
```
Timestamp, Topic, Prediction, TX Hash, Notes, Status
2025-11-21T22:37:16.758598+00:00, 67, -2.9062538146972656, "", "", already_submitted
```

### Count Submissions by Status
```bash
echo "Success:"; grep "success" competition_submissions.csv | wc -l
echo "Already Submitted:"; grep "already_submitted" competition_submissions.csv | wc -l
echo "Validation Failed:"; grep "validation_failed" competition_submissions.csv | wc -l
```

---

## 🔐 Security Notes

### Best Practices
- ✅ Mnemonic stored in `.env` (not in code)
- ✅ Never commit `.env` to version control
- ✅ Wallet credentials passed via environment variables
- ✅ No hardcoded keys in logs
- ✅ Local wallet only (no remote key exposure)

### Secure Operations
```bash
# Never print mnemonic
# Instead, verify it's set:
test -n "$MNEMONIC" && echo "✅ Mnemonic is set"

# View only wallet address (public info)
echo "Wallet: $ALLORA_WALLET_ADDR"
```

---

## 📋 Schedule

### Submission Timing
- **Interval**: Every 1 hour
- **Start**: Immediately on pipeline startup
- **First**: Within 2 minutes of `./start_pipeline.sh`
- **Next**: Exactly 1 hour after first
- **Continue**: Every hour until deadline

### Competition Timeline
- **Start**: 2025-09-16 13:00 UTC
- **Deadline**: 2025-12-15 13:00 UTC
- **Total Duration**: 90 days
- **Current Status**: Active (23 days remaining)

### Auto-Shutdown
- Pipeline automatically stops after deadline
- No manual intervention needed
- Logged when shutdown occurs

---

## 🎯 Success Indicators

### Look for These in Logs
```
✅ "Wallet initialized from LocalWallet"
✅ "Topic 67 metadata fetched via gRPC"
✅ "Cycle X complete - submission successful!"
✅ "Waiting 1 hour until next submission..."
```

### Avoid These in Logs
```
❌ "ERROR - MNEMONIC environment variable not set"
❌ "Invalid mnemonic length"
❌ "Unable to fetch data from configured RPC endpoints"
❌ "Connection refused"
```

---

## 📞 Support Reference

### Log Locations
- Main log: `logs/submission.log`
- Process ID: `logs/pipeline.pid`
- Submissions: `competition_submissions.csv`
- Model: `data/artifacts/model.joblib`

### Quick Diagnostics
```bash
# Test RPC connectivity
python3 << 'EOF'
from allora_forge_builder_kit.rpc_utils import get_topic_metadata
print(get_topic_metadata(67))
EOF

# Test wallet format
grep ALLORA_WALLET_ADDR .env

# Verify mnemonic words
grep MNEMONIC .env | tr ' ' '\n' | wc -l
```

---

## 🚀 One-Command Operations

### Everything (Start + Monitor)
```bash
./start_pipeline.sh && sleep 5 && tail -f logs/submission.log
```

### Health Check
```bash
ps aux | grep -q "competition_submission.py" && echo "✅ Running" || echo "❌ Stopped"
```

### Recent Status
```bash
tail -20 logs/submission.log | tail -10
```

### Last 3 Submissions
```bash
tail -3 competition_submissions.csv
```

---

## ✅ Ready to Deploy?

- [x] System requirements verified (16 vCPUs, 62GB RAM, 106GB disk)
- [x] Environment configured (.env present with credentials)
- [x] RPC endpoints working (gRPC + Tendermint)
- [x] Wallet balance verified (0.2513 ALLO)
- [x] Pipeline tested (dry-run + full submission)
- [x] Logging configured and working
- [x] Monitoring tools available
- [x] Competition deadline confirmed (23 days remaining)

**Status**: ✅ **READY FOR DEPLOYMENT**

```bash
./start_pipeline.sh
```

---

**Last Updated**: 2025-11-21 22:37 UTC  
**Version**: Production Ready  
**Competition**: Topic 67 - 7-Day BTC/USD Log-Return Prediction  
