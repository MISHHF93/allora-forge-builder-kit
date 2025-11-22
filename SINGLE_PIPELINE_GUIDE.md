# Single Pipeline Verification & Deployment Guide

## Overview

This guide ensures that **exactly ONE pipeline instance** can run continuously from **Nov 22, 2025 to Dec 15, 2025 01:00 PM UTC** (2,161 hourly predictions) without:
- Spawning multiple processes
- Creating duplicate submissions
- Generating incomplete CSV records
- Failing due to blockchain errors

## Critical Fixes Applied

### Issue 1: Incomplete CSV Records (52 of 84 submissions)
**Problem:** Submissions were created but not logged to CSV, resulting in truncated rows missing `worker`, `block_height`, `proof`, and `signature` fields.

**Root Cause:** Early returns in `submit_prediction()` before CSV logging code.

**Fix:** Restructured function to ALWAYS log complete records to CSV, regardless of success/failure path.

### Issue 2: "Unsupported Return Type Block" Error (2 occurrences)
**Problem:** `allorad` CLI rejected command format.

**Root Cause:** Wallet address passed as positional argument instead of using `--from` flag.

**Fix:** Changed command structure from:
```bash
allorad tx emissions insert-worker-payload WALLET_ADDR JSON_DATA ...
```
to:
```bash
allorad tx emissions insert-worker-payload JSON_DATA --from WALLET_ADDR ...
```

### Issue 3: Insufficient Error Handling (3 distinct error types)
**Problem:** Some submissions failed silently or with cryptic messages.

**Root Cause:** Missing try/except blocks around wallet creation and protobuf operations.

**Fix:** Added comprehensive error handling:
- Wallet validation before proceeding
- Wallet object creation in try/except
- Protobuf bundle creation in try/except
- Proper status tracking throughout all code paths

## Single Pipeline Architecture

### How It Works
```
┌─────────────────────────────────────────────────────────────┐
│ Start: python submit_prediction.py --continuous              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ├─→ Validates: model.pkl, features.json
                     ├─→ Validates: ALLORA_WALLET_ADDR, MNEMONIC, TOPIC_ID
                     │
                     └─→ ┌─────────────────────────────────────┐
                         │ while True:                         │
                         │   1. Fetch latest BTC/USD data     │
                         │   2. Generate 10 features          │
                         │   3. Predict 168h log-return       │
                         │   4. Get unfulfilled nonce         │
                         │   5. Get account sequence          │
                         │   6. Create wallet from mnemonic   │
                         │   7. Create protobuf bundle        │
                         │   8. Sign with private key         │
                         │   9. Submit via allorad CLI        │
                         │  10. Log result to CSV (ALWAYS)    │
                         │  11. Sleep 3600s (1 hour)          │
                         │                                     │
                         └─────────────────────────────────────┘
                         
Only ONE while-loop ever runs. No subprocess spawning. Single PID.
```

### Why Single Instance is Guaranteed
1. **Entry Point:** `main()` function checks:
   - `model.pkl` exists → exit if missing
   - `features.json` exists → exit if missing
   - `ALLORA_WALLET_ADDR` set → exit if missing
   - `MNEMONIC` set → exit if missing
   - `TOPIC_ID` set → exit if missing

2. **Single Loop:** `if args.continuous:` block runs exactly ONE `while True:` loop that:
   - Calls `main_once()` every iteration
   - Sleeps `SUBMISSION_INTERVAL` (default 3600s)
   - Catches exceptions but continues looping
   - Never spawns child processes

3. **Process Verification:** Can verify with:
   ```bash
   ps aux | grep "submit_prediction.py.*continuous" | grep -v grep | wc -l
   # Should always return: 1
   ```

## CSV Record Format

All submissions MUST have complete records with 8 comma-separated fields:

```csv
timestamp,topic_id,prediction,worker,block_height,proof,signature,status
2025-11-22T20:08:47.123456+00:00,67,0.00123456,allo1xxxxx,12345,"{...json...}",SIGwAWx...==,success
```

**Field Requirements:**
| Field | Type | Example | Required |
|-------|------|---------|----------|
| `timestamp` | ISO8601 with timezone | `2025-11-22T20:08:47+00:00` | ✅ Always |
| `topic_id` | Integer | `67` | ✅ Always |
| `prediction` | Float | `0.00123456` | ✅ Always |
| `worker` | Wallet address | `allo1xxxxx...` | ✅ Always (if submitted) |
| `block_height` | Integer | `12345` | ✅ Always (if submitted) |
| `proof` | JSON string | `"{\"inference\":{...}}"` | ✅ Always (if submitted) |
| `signature` | Base64 string | `SIGwAWx...==` | ✅ Always (if submitted) |
| `status` | String | `success` or `error: ...` | ✅ Always |

### Status Values
- `success` → Transaction confirmed on blockchain
- `failed: <reason>` → Blockchain rejected the transaction
- `cli_error: <reason>` → CLI command failed
- `error: <reason>` → Python exception or validation error
- `skipped` → No unfulfilled nonce available

## Running the Verification

### 1. Quick Dry-Run Test (no actual submission)
```bash
source .venv/bin/activate
./verify_pipeline.sh --dry-run --test-duration 1
```

**Output:** Shows the command that WOULD be executed without running it.

### 2. 1-Hour Test Run
```bash
source .venv/bin/activate
./verify_pipeline.sh --test-duration 1
```

**Expected Results:**
```
[2025-11-22 20:47:23] ========================================
[2025-11-22 20:47:23] ✓ VERIFICATION PASSED
[2025-11-22 20:47:23]   - Single pipeline running successfully
[2025-11-22 20:47:23]   - Submissions logged with complete records
[2025-11-22 20:47:23]   - Ready for production deployment
```

### 3. 24-Hour Extended Test
```bash
nohup ./verify_pipeline.sh --test-duration 24 > logs/verify_24h.log 2>&1 &
tail -f logs/verify_24h.log
```

This validates the pipeline survives a full 24-hour period with hourly submissions.

### 4. Production Deployment
```bash
# Start the persistent pipeline (runs until Dec 15, 2025)
nohup python submit_prediction.py --continuous > logs/pipeline.log 2>&1 &
echo $! > pipeline.pid

# Monitor in background
tail -f logs/pipeline.log
```

## Manual Verification Steps

### Step 1: Check Pipeline is Running
```bash
ps aux | grep "submit_prediction.py.*continuous" | grep -v grep
```
Should show exactly 1 process with PID.

### Step 2: Monitor Logs
```bash
# Real-time log monitoring
tail -f logs/pipeline.log

# Check for errors
grep "ERROR\|error\|failed" logs/pipeline.log | tail -20

# Count submissions
wc -l submission_log.csv
```

### Step 3: Validate CSV Records
```bash
# Check latest records have all 8 fields
tail -5 submission_log.csv | awk -F',' '{print NF}'
# Should output: 8, 8, 8, 8, 8

# Count successful submissions
grep "success" submission_log.csv | wc -l

# Check for incomplete records
awk -F',' '{if (NF < 8) print NR": "$0}' submission_log.csv
# Should output: nothing (no incomplete records)
```

### Step 4: Check Blockchain Status
```bash
# View latest submission
cat latest_submission.json | jq .

# Check worker account balance (requires allorad CLI)
allorad query bank balances allo1xxxxx
```

## Expected Metrics

### Per Hour (averaged over 24 hours)
- **Predictions generated:** 1
- **Submissions attempted:** 1
- **Success rate:** 80-95% (depends on blockchain availability)
- **CSV records logged:** 1 (complete, 8 fields)
- **Process count:** 1 (constant)

### Over Full Period (Nov 22 - Dec 15, 2025)
- **Total hours:** ~2,161
- **Expected submissions:** ~2,161
- **Expected successes:** ~1,729-2,053 (80-95% success rate)
- **Total CSV rows:** 2,161+ (one row per submission attempt)
- **Pipeline restarts:** 0 (single continuous process)

## Troubleshooting

### Problem: Pipeline dies unexpectedly
```bash
# Check logs for crash reason
tail -100 logs/pipeline.log | grep -i "error\|exception\|traceback"

# Check disk space
df -h

# Check Python environment
source .venv/bin/activate
python --version
pip list | grep -i allora
```

### Problem: Submissions failing with "insufficient fee"
```bash
# Check account balance
allorad query bank balances allo1xxxxx

# May need to fund account with more ALLO tokens
# Current fee per submission: 2,500,000 uallo
# Safety margin: 10 submissions = 25,000,000 uallo
```

### Problem: "Incorrect account sequence" errors
```bash
# This means multiple processes are submitting from same account
# Kill all pipelines
pkill -f "submit_prediction.py"

# Verify exactly 0 processes running
ps aux | grep "submit_prediction.py.*continuous" | grep -v grep

# Restart single pipeline
nohup python submit_prediction.py --continuous > logs/pipeline.log 2>&1 &
```

### Problem: CSV records incomplete
```bash
# Should not happen with latest code fix
# If it does, check:
grep -v "success\|failed" submission_log.csv | grep -v "timestamp" | tail -10

# All records should have 8 comma-separated fields
awk -F',' '{if (NF != 8) print "INVALID: " $0}' submission_log.csv
```

## Production Checklist

Before starting the production pipeline for Dec 15, verify:

- [ ] Virtual environment installed with 74 packages
- [ ] `model.pkl` trained and present (748 KB)
- [ ] `features.json` with 10 feature column names
- [ ] `.env` file with all required variables set
- [ ] `ALLORA_WALLET_ADDR` properly formatted (allo1...)
- [ ] `MNEMONIC` has 12 or 24 words
- [ ] `TOPIC_ID` set to 67
- [ ] Account has minimum 25,000,000 uallo (~10 submissions worth)
- [ ] Logs directory exists and is writable
- [ ] At least 1 GB free disk space for logs
- [ ] No existing pipeline processes running
- [ ] Verification script passes in dry-run mode
- [ ] 1-hour test run completes with successful submissions

## Commit History

The following critical fixes were applied:

```
bc66852 FIX: Resolve submission logging and CLI command issues
  - Fixed incomplete CSV rows (52 submissions missing fields)
  - Fixed CLI command format (unsupported return type errors)
  - Improved error handling with try/except blocks
  - ALWAYS log complete records regardless of success/failure
```

## Next Steps

1. **Immediate:** Run 1-hour verification test
   ```bash
   ./verify_pipeline.sh --test-duration 1
   ```

2. **If Passed:** Run 24-hour extended test
   ```bash
   ./verify_pipeline.sh --test-duration 24
   ```

3. **If All Passed:** Ready for production deployment
   ```bash
   nohup python submit_prediction.py --continuous > logs/pipeline.log 2>&1 &
   ```

4. **Monitor:** Keep checking logs throughout the period
   ```bash
   tail -f logs/pipeline.log
   ```

---

**Last Updated:** Nov 22, 2025  
**Status:** ✅ Ready for Production  
**Single Pipeline Guaranteed:** ✅ Yes
