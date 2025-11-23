# Quick Reference: Enhanced RPC Failover System
## Deployment November 23, 2025 | Daemon PID: 263171

---

## ✅ What Was Fixed

### 1. RPC Endpoint Failover
**Before:** Single RPC → entire pipeline fails
**After:** 3 RPC endpoints with auto-rotation → survives endpoint outages

### 2. Invalid Response Detection  
**Before:** HTML error pages silently accepted
**After:** detect "<" character, JSON validation → log error, retry

### 3. Submission Tracking
**Before:** 9-column CSV, some failures not logged
**After:** 10-column CSV with rpc_endpoint column → complete audit trail

### 4. Retry Strategy
**Before:** One failed query = cycle lost
**After:** Up to 3 attempts with different RPC endpoints → recover automatically

### 5. RPC Endpoint Health
**Before:** Failed endpoint used forever
**After:** Failure counter (0-3), auto-reset after success → self-healing

---

## 📋 CSV Schema (10 Columns)

```
timestamp,topic_id,prediction,worker,block_height,proof,signature,status,tx_hash,rpc_endpoint
```

**New Column:** `rpc_endpoint` (10th)
- Values: Primary, AllThatNode, ChandraStation, all_failed

**Status Values:**
- `success_confirmed` - validated on-chain ✅
- `success_pending_confirmation` - submitted, awaiting validation ⏳
- `failed_no_sequence` - couldn't get account sequence
- `failed_invalid_response` - received HTML instead of JSON
- `skipped_no_nonce` - no available nonce
- `cli_error: <msg>` - CLI submission failed
- `error: <msg>` - other errors

---

## 🚀 Key Functions

### `validate_json_response(response_text, context="")`
Detects HTML error pages, validates JSON
- Returns: `(is_valid: bool, data: dict)`
- Used by: all RPC queries

### `get_rpc_endpoint() -> dict`
Returns next working RPC endpoint
- Filters out endpoints with 3+ failures
- Auto-resets if all fail
- Returns: `{"url": "...", "name": "Primary", "priority": 1}`

### `mark_rpc_failed(endpoint_url, error="")`
Increment failure counter for endpoint
- Counter goes 0→1→2→3 (then skipped)
- Logs failure count and error message

### `reset_rpc_endpoint(endpoint_url)`
Reset failure counter to 0 (after success)
- Called after successful queries
- Allows endpoint to be tried again

### `log_submission_to_csv(..., rpc_endpoint="")`
Centralized CSV logging
- Logs EVERY submission (success or failure)
- Creates header on first write
- Appends records automatically

---

## 🔍 Monitoring

### View CSV Latest
```bash
tail -5 submission_log.csv
```

### Count RPC Usage
```bash
cut -d, -f10 submission_log.csv | sort | uniq -c
# Shows: X Primary, Y AllThatNode, Z ChandraStation, W all_failed
```

### View Status Distribution
```bash
cut -d, -f8 submission_log.csv | grep -o '^[^,]*' | sort | uniq -c
```

### Monitor RPC Failover Live
```bash
tail -f logs/submission.log | grep -E "RPC endpoint|marked failed|Submission attempt"
```

### Find Errors
```bash
grep "❌\|ERROR\|invalid" logs/submission.log | tail -20
```

---

## 🎯 How It Works

### Normal Submission (Primary RPC Works)
```
Cycle #1
├─ Get RPC: Primary
├─ Query nonce: ✅ success (reset Primary counter to 0)
├─ Query sequence: ✅ success
├─ Submit TX: ✅ accepted
├─ Validate on-chain: ✅ confirmed
└─ CSV: success_confirmed, Primary
```

### Primary RPC Fails (AllThatNode Succeeds)
```
Cycle #2
├─ Attempt 1: Primary
│  ├─ Get RPC: Primary
│  ├─ Query nonce: ❌ timeout
│  └─ Mark Primary failed (1/3), try next
├─ Attempt 2: AllThatNode
│  ├─ Get RPC: AllThatNode
│  ├─ Query nonce: ✅ success (reset AllThatNode counter to 0)
│  ├─ Submit TX: ✅ accepted
│  └─ Validate on-chain: ✅ confirmed
└─ CSV: success_confirmed, AllThatNode
```

### All RPC Endpoints Fail
```
Cycle #3
├─ Attempt 1: Primary → ❌ fail (1/3)
├─ Attempt 2: AllThatNode → ❌ fail (1/3)
├─ Attempt 3: ChandraStation → ❌ fail (1/3)
└─ CSV: failed_no_sequence, all_failed
```

### RPC Recovers
```
Cycle #4 (1+ hour later)
├─ Primary: 1/3 failures → still skipped
├─ AllThatNode: 1/3 failures → still skipped
├─ ChandraStation: 1/3 failures → still skipped
├─ All reset (no working endpoints available)
├─ Try Primary again: ✅ success (reset to 0/3)
└─ CSV: success_confirmed, Primary
```

---

## 📊 Failure Counter Behavior

Each RPC endpoint has a counter: `0-3`

| Counter | Status | Action |
|---------|--------|--------|
| 0 | Healthy | Use normally |
| 1 | Warning | Still tried, tracked |
| 2 | Critical | Still tried, tracked |
| 3 | Failed | SKIPPED in get_rpc_endpoint() |
| Success | Recovery | Reset to 0 |
| All ≥ 3 | Exhausted | Reset all to 0 |

---

## 🔄 Retry Loop Logic

```python
for attempt in range(3):  # max 3 attempts
    rpc = get_rpc_endpoint()  # gets next working endpoint
    
    if submit_succeeds():
        log_to_csv("success_confirmed", rpc.name)
        break
    else:
        mark_rpc_failed(rpc.url, error)
        if attempt < 2:
            continue  # try next endpoint
        else:
            log_to_csv("failed_*", "all_failed")
            break
```

---

## 🚨 Error Handling

| Error | Detection | Action |
|-------|-----------|--------|
| HTML Response | Starts with `<` | mark_failed, retry |
| JSON Decode | json.JSONDecodeError | mark_failed, retry |
| DNS Timeout | subprocess output | mark_failed, retry |
| Submission Timeout | subprocess.TimeoutExpired | mark_failed, retry |
| No Nonce | API returns empty | log skipped_no_nonce |
| All Fail | attempt 3 complete | log all_failed |

---

## 📈 Performance Metrics

- **Endpoints:** 3 (Primary, AllThatNode, ChandraStation)
- **Max Retries:** 3 per submission cycle
- **Max Failures:** 3 per endpoint before skip
- **Reset Trigger:** Success or all exhausted
- **Query Timeout:** 30 seconds
- **Submission Timeout:** 120 seconds
- **CSV Columns:** 10 (includes rpc_endpoint)

---

## 🎯 Next Steps

The daemon continues running until December 15, 2025:
- Submits predictions hourly
- Logs to CSV every cycle (success or failure)
- Tracks which RPC endpoint was used
- Validates transactions on-chain
- Retries automatically on failure
- Recovers from transient RPC issues

**No manual intervention needed.** Monitor with:
```bash
tail -f logs/submission.log | grep -E "SUBMISSION|ACCEPTED|CONFIRMED"
```

---

## 📚 Full Documentation

See `RPC_ENHANCED_IMPROVEMENTS.md` for:
- Complete technical details
- Function signatures
- Failure tracking logic
- Monitoring commands
- Scenario analysis
- Production behavior expectations

---

**Status: 🟢 LIVE & OPERATIONAL**

Daemon PID: 263171 | Deployed: 2025-11-23T06:10:47 UTC | Git: d8c7d49
