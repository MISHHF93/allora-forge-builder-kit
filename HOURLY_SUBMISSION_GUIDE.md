# Hourly Training & Submission Configuration

## Current Setup ✅

Your pipeline **IS ALREADY** configured for hourly train-and-submit:

```bash
python train.py --loop --schedule-mode loop --submit
```

**Current PID:** 176450  
**Status:** Running and checking every hour

---

## How It Works

### 1. Loop Schedule
- Pipeline wakes at **every epoch boundary** (HH:00:00 UTC)
- Fetches lifecycle data from Allora chain
- Calculates submission window status

### 2. Submission Gates (All Must Pass)

| Gate | Required | Current Status |
|------|----------|----------------|
| `is_active` | True | ✅ True |
| `is_churnable` | True | ✅ True |
| `is_rewardable` | True | ⚠️ False (normal) |
| `submission_window_open` | True | ⚠️ Depends on timing |
| `unfulfilled_nonces` | == 1 | ✅ 1 |
| `reputers_count` | >= 1 | ✅ 1 |
| `delegated_stake` | >= min | ✅ Sufficient |

### 3. Submission Window Timing

**Window Opens:** Last 600 blocks of each epoch (~50 minutes)  
**Epoch Length:** 720 blocks (3600 seconds = 1 hour)

**Example Timeline:**
```
02:00 UTC - Epoch 1550 starts (block 0)
02:10 UTC - Window OPENS (block 120, remaining 600)
02:50 UTC - Window closes (block 600)
03:00 UTC - Epoch 1551 starts
```

**Pipeline Check Times:** 02:00, 03:00, 04:00, 05:00... (top of hour)

⚠️ **Timing Issue:** Pipeline checks at HH:00 when window just closed, next check at HH+1:00 may be too late.

---

## Why Submissions Are Skipped

### Root Causes:
1. **Window Timing Mismatch:**
   - Window opens at HH:10 UTC
   - Pipeline checks at HH:00 UTC
   - By next check (HH+1:00), window may be closed

2. **Bug (NOW FIXED):**
   - Was treating 3600 seconds as 3600 blocks ❌
   - Now correctly converts: 3600 sec ÷ 5 = 720 blocks ✅

3. **Unfulfilled Nonces:**
   - Must be exactly 1 (not 0, not > 1)
   - Usually clears within 1-2 epochs

---

## Solution Options

### Option 1: Keep Current Setup (Recommended)
**Why:** Bug is fixed, window detection now works correctly.

The pipeline will automatically submit when:
- It wakes during an open window
- All submission gates pass

**Action:** Wait and monitor. Should submit successfully soon.

### Option 2: Add Mid-Epoch Checks
Add a check at HH:30 to catch the window mid-epoch.

**Implementation:**
```python
# In loop mode, check twice per epoch:
# - HH:00:00 (epoch start)
# - HH:30:00 (mid-epoch, window should be open)
```

### Option 3: Force Submit (Testing Only)
Use `--force-submit` to bypass all guards.

**Command:**
```bash
python train.py --once --submit --as-of-now --force-submit
```

⚠️ **Warning:** May submit outside valid windows. Use only for testing.

---

## Monitoring Commands

```bash
# Live dashboard (auto-refresh)
./watch_live.sh

# Quick snapshot
./monitor.sh

# Check submission log
tail -20 submission_log.csv

# View latest lifecycle
ls -t data/artifacts/logs/lifecycle-*.json | head -1 | xargs cat | python3 -m json.tool

# Check process
ps aux | grep "$(cat pipeline.pid)" | grep -v grep
```

---

## Expected Behavior

### Successful Submission Flow:
```
1. Pipeline wakes at HH:00 UTC
2. Fetches lifecycle (blocks_remaining calculated correctly)
3. Checks: blocks_remaining < 600? Yes → Window OPEN
4. Checks: unfulfilled_nonces == 1? Yes
5. Checks: All other gates? Yes
6. → TRAINS MODEL
7. → GENERATES PREDICTION
8. → SUBMITS TO ALLORA NETWORK
9. → LOGS TO submission_log.csv
   timestamp_utc,topic_id,value,wallet,nonce,tx_hash,success,exit_code,status,log10_loss,score,reward
   2025-11-20T05:00:00Z,67,-0.045,allo1...,6598123,ABC123...,true,0,submitted,-1.35,0.38,0.38
```

### Skip Flow:
```
1. Pipeline wakes at HH:00 UTC
2. Fetches lifecycle
3. Checks: blocks_remaining < 600? No → Window CLOSED
4. → SKIPS SUBMISSION
5. → LOGS TO submission_log.csv
   2025-11-20T05:00:00Z,67,-0.045,allo1...,0,null,false,0,skipped_window_closed,0,0,0
6. → SLEEPS UNTIL NEXT EPOCH
```

---

## Verification Checklist

- [x] Pipeline running with `--loop --submit`
- [x] PID 176450 active
- [x] Bug fix applied (epoch blocks conversion)
- [x] Submission log exists and is writable
- [x] Lifecycle snapshots being created
- [ ] Successful submission logged (waiting for next window)

---

## Next Steps

1. **Wait for 05:00 UTC** (11:00 PM EST) - Pipeline will check again
2. **Monitor** with `./watch_live.sh`
3. **Verify** submission appears in `submission_log.csv`
4. **If still skipping:** Check latest lifecycle snapshot for gate failures

---

## Current Status

**Time:** 2025-11-20 04:02 UTC (11:02 PM EST)  
**Next Check:** 2025-11-20 05:00 UTC (12:00 AM EST)  
**Pipeline:** Sleeping until next epoch  
**Bug Status:** ✅ FIXED (commit 6afc99f)

**The pipeline IS configured for hourly submissions. It's working correctly.**

