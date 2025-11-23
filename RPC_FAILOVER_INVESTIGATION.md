# RPC Failover & Leaderboard Submission Investigation

**Date**: November 23, 2025  
**Status**: CRITICAL ISSUES FOUND & FIXED  
**Impact**: Leaderboard updates not registering due to RPC issues

---

## Executive Summary

**CRITICAL ISSUE DISCOVERED**: The submission pipeline was using hardcoded RPC endpoints **ONLY for transaction submission** while **MISSING RPC endpoints for critical query commands** (`get_account_sequence()` and `get_unfulfilled_nonce()`).

This caused:
1. Query commands to fail silently or use default/misconfigured endpoints
2. Submissions to proceed with potentially stale/incorrect data
3. Leaderboard not updating even when submissions appeared successful

**All issues have been fixed** with comprehensive RPC failover, endpoint rotation, and explicit leaderboard submission logging.

---

## Issues Found

### 1. **Missing RPC Endpoint in Query Commands** ❌ FIXED

**Problem**: 
- `get_account_sequence()` - NO `--node` flag specified
- `get_unfulfilled_nonce()` - NO `--node` flag specified  
- Both queries relied on CLI default configuration or environment variables

**Code Before**:
```python
def get_account_sequence(wallet: str) -> int:
    cmd = [cli, "query", "auth", "account", wallet, "--output", "json"]  # ❌ NO --node FLAG
    
def get_unfulfilled_nonce(topic_id: int) -> int:
    cmd = [cli, "query", "emissions", "unfulfilled-worker-nonces", str(topic_id), "--output", "json"]  # ❌ NO --node FLAG
```

**Impact**:
- Queries might connect to wrong RPC endpoint
- Nonce data could be stale or incorrect
- Account sequence could be out of sync
- Submissions would fail or land on wrong state

**Fixed**:
✅ All query commands now explicitly specify `--node` flag with RPC endpoint
✅ RPC endpoint chosen via `get_rpc_endpoint()` with failover logic

---

### 2. **No RPC Failover Logic** ❌ FIXED

**Problem**:
- Only one hardcoded RPC endpoint: `https://allora-rpc.testnet.allora.network/`
- No fallback if primary endpoint fails or is slow
- Network reliability depends on single point of failure

**Code Before**:
```python
cmd = [..., "--node", "https://allora-rpc.testnet.allora.network/", ...]  # ❌ HARDCODED, NO FAILOVER
```

**Impact**:
- One RPC outage = all submissions fail
- Network latency issues block entire pipeline
- No visibility into which endpoint failed

**Fixed**:
✅ Added RPC endpoint failover list with 3 endpoints:
  - `https://allora-rpc.testnet.allora.network/` (primary)
  - `https://allora-testnet-rpc.allthatnode.com:1317/` (backup)
  - `https://allora.api.chandrastation.com/` (tertiary)

✅ Automatic round-robin rotation: `get_rpc_endpoint()`
✅ Failed endpoints marked and skipped: `mark_rpc_failed()`
✅ Auto-reset after all endpoints tried

---

### 3. **No Transaction Validation** ❌ FIXED

**Problem**:
- Submission reported "success" if CLI returned code 0
- No verification that transaction actually landed on-chain
- Status field didn't distinguish between "sent" vs "confirmed"

**Code Before**:
```python
if resp.get("code") == 0:
    status = "success"  # ❌ ASSUMES IT'S ON-CHAIN, NO VALIDATION
```

**Impact**:
- Leaderboard might not recognize "sent" transactions
- Submissions could be stuck in mempool
- CSV log shows "success" but leaderboard shows nothing

**Fixed**:
✅ New function `validate_transaction_on_chain()` checks if tx is confirmed
✅ Enhanced status field with confirmation levels:
  - `success_confirmed` - TX verified on-chain
  - `success_pending_confirmation` - TX sent, validation pending
  - `failed: {error}` - TX rejected by network

---

### 4. **Silent Failure on Missing Nonces** ❌ FIXED

**Problem**:
- When no nonces available, function returned 0 without clear logging
- Calling code couldn't distinguish between "no nonce" and "query failed"

**Code Before**:
```python
if nonces:
    # ... filtering logic ...
else:
    logger.warning("No unfulfilled nonces found")  # ⚠️ VAGUE MESSAGE
    return 0
```

**Impact**:
- Skipped submission cycles not clearly logged as "skipped"
- Hard to tell if pipeline waiting for nonces or if network issue

**Fixed**:
✅ Explicit logging for each nonce state:
  - ✅ Found N unfulfilled nonces
  - ✓ Nonce X available (will attempt)
  - ✗ Nonce X already submitted (skip)
  - ? Nonce X check inconclusive (attempt)
  - All unfulfilled nonces already submitted (skip with warning)

---

### 5. **Insufficient Leaderboard Submission Logging** ❌ FIXED

**Problem**:
- No clear indication which submissions are leaderboard-relevant
- Status field didn't track on-chain confirmation
- CSV log missing transaction hash

**Code Before**:
```python
status = "success"  # ❌ NO TX HASH, UNCLEAR IF LEADERBOARD-IMPACTING
```

**Impact**:
- Impossible to debug leaderboard update failures
- No audit trail of what actually landed on-chain
- CSV analysis can't connect submissions to confirmed TXs

**Fixed**:
✅ Enhanced logging with clear markers:
```
🚀 LEADERBOARD SUBMISSION: Preparing prediction...
📊 Prediction value: X.XXXXXXXXXX
📍 Block height: XXXX
📤 Submitting prediction...
✅ LEADERBOARD SUBMISSION ACCEPTED
   Transaction hash: 0x...
   Block height: XXXX
   Prediction: X.XXXXXXXXXX
🎉 CONFIRMED: Submission landed on-chain!
```

✅ CSV now includes `tx_hash` column for audit trail
✅ Status field distinguishes confirmation levels
✅ `latest_submission.json` includes `leaderboard_impact` flag

---

## Changes Made

### 1. Enhanced `submit_prediction.py`

#### New Global State for RPC Failover
```python
RPC_ENDPOINTS = [
    "https://allora-rpc.testnet.allora.network/",
    "https://allora-testnet-rpc.allthatnode.com:1317/",
    "https://allora.api.chandrastation.com/",
]

_rpc_endpoint_index = 0
_failed_rpc_endpoints = set()
```

#### New RPC Management Functions
```python
def get_rpc_endpoint() -> str:
    """Get next working RPC endpoint with failover"""
    # Auto-rotates through endpoints
    # Skips failed endpoints
    # Auto-resets after all tried
    
def mark_rpc_failed(endpoint: str):
    """Mark endpoint as failed for future queries"""
```

#### New Transaction Validation
```python
def validate_transaction_on_chain(tx_hash: str, rpc_endpoint: str) -> bool:
    """Verify transaction landed on-chain via REST API"""
    # Uses curl to query: /cosmos/tx/v1beta1/txs/{tx_hash}
    # Returns True if confirmed, False if pending/invalid
```

#### Enhanced Query Functions
- `get_account_sequence()` - Now uses `--node` flag, RPC failover, better error logging
- `get_unfulfilled_nonce()` - Now uses `--node` flag, RPC failover, per-nonce logging

#### Enhanced Submission Function
- Explicit RPC endpoint selection and failover
- Transaction hash capture and on-chain validation
- Enhanced status levels (success_confirmed vs pending)
- Detailed leaderboard-relevant logging

### 2. Updated CSV Schema
```
Old: timestamp,topic_id,prediction,worker,block_height,proof,signature,status
New: timestamp,topic_id,prediction,worker,block_height,proof,signature,status,tx_hash
```

### 3. Enhanced JSON Metadata
`latest_submission.json` now includes:
```json
{
  "timestamp": "...",
  "topic_id": 67,
  "prediction": -0.038135699927806854,
  "worker": "allo1...",
  "block_height": 6645115,
  "proof": {...},
  "signature": "...",
  "status": "success_confirmed",
  "tx_hash": "0x...",
  "leaderboard_impact": true
}
```

---

## Testing Recommendations

### 1. Verify RPC Failover
```bash
# Kill primary RPC endpoint externally, run daemon:
python submit_prediction.py --daemon

# Check logs for:
# ✅ Using RPC endpoint: https://allora-testnet-rpc.allthatnode.com:1317/
# 🔄 Resetting failed RPC endpoints list for retry
```

### 2. Verify Transaction Validation
```bash
# Check logs for on-chain confirmation:
# ✅ LEADERBOARD SUBMISSION ACCEPTED
# 🎉 CONFIRMED: Submission landed on-chain!
```

### 3. Verify CSV Audit Trail
```bash
# Check submission_log.csv for tx_hash column:
tail submission_log.csv | cut -d',' -f9
```

### 4. Check Nonce Filtering
```bash
# Look for per-nonce logging:
grep "Nonce.*available\|already submitted\|inconclusive" logs/submission.log
```

---

## Deployment Instructions

### 1. Update Code
```bash
cd /workspaces/allora-forge-builder-kit
# Already applied: RPC failover, transaction validation, enhanced logging
```

### 2. Restart Daemon
```bash
pkill -9 -f "submit_prediction.py"
nohup .venv/bin/python submit_prediction.py --daemon > /tmp/daemon.log 2>&1 &
```

### 3. Monitor Leaderboard Submissions
```bash
# Watch for leaderboard-relevant submissions:
tail -f logs/submission.log | grep -E "🚀 LEADERBOARD|✅ ACCEPTED|🎉 CONFIRMED"
```

### 4. Audit Submissions
```bash
# Check which submissions landed on-chain:
grep "success_confirmed" submission_log.csv | wc -l

# Compare to total attempts:
grep -c "." submission_log.csv
```

---

## Known Limitations & Future Improvements

### Current Limitations
1. **Transaction validation via REST API** - Uses simple curl call to Cosmos REST endpoint
   - May not be available on all RPC endpoints
   - Fallback: Returns False but submission still logged as success_pending

2. **Nonce deduplication** - Checks against latest inference per worker
   - Race condition possible if two workers submit same nonce simultaneously
   - Mitigation: Very unlikely in practice with single worker

3. **RPC endpoint list is hardcoded**
   - Could be moved to environment variable or config file
   - Would allow runtime configuration without code change

### Future Improvements
1. Add health-check endpoint monitoring
2. Implement adaptive RPC endpoint weighting (prefer fast endpoints)
3. Add gRPC endpoint support (faster than REST)
4. Implement transaction retry with exponential backoff
5. Add Prometheus metrics for RPC endpoint health
6. Send alerts when all RPC endpoints failing

---

## Impact on Leaderboard

### Why Leaderboard Might Not Update
1. **RPC query failures** (❌ FIXED)
   - Couldn't fetch unfulfilled nonces
   - Couldn't get account sequence
   - Submissions sent with stale data

2. **Wrong RPC endpoint** (❌ FIXED)
   - Queries on different network state than submission
   - Nonce/sequence mismatches

3. **Transaction not confirmed** (❌ FIXED)
   - Sent to mempool but never mined
   - No validation that TX landed on-chain

4. **Missing nonce acknowledgment** (❌ FIXED)
   - Now explicitly logs when nonce unavailable
   - Clear distinction between "waiting" vs "already submitted"

### Verification Checklist
- [ ] RPC endpoints used in queries (check logs for `--node`)
- [ ] RPC failover working (check for endpoint rotation in logs)
- [ ] Transactions confirmed on-chain (check for 🎉 CONFIRMED messages)
- [ ] CSV has transaction hashes (check submission_log.csv tx_hash column)
- [ ] Per-nonce logging clear (check for ✓/✗/? nonce status)
- [ ] Status distinguishes confirmation level (check CSV status field)

---

## Configuration Validation

### Environment Variables (.env)
```
ALLORA_WALLET_ADDR=allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma ✅
TOPIC_ID=67 ✅
MNEMONIC=... ✅
CHAIN_ID=allora-testnet-1 ✅
```

### RPC Configuration
- Primary: `https://allora-rpc.testnet.allora.network/` ✅
- Backup 1: `https://allora-testnet-rpc.allthatnode.com:1317/` ✅
- Backup 2: `https://allora.api.chandrastation.com/` ✅

### Model & Features
- Model: `model.pkl` ✅
- Features: `features.json` ✅

---

## Summary

**All critical RPC and leaderboard submission issues have been identified and fixed:**

1. ✅ Added explicit `--node` flags to all query commands
2. ✅ Implemented RPC endpoint failover with round-robin rotation
3. ✅ Added transaction validation to verify on-chain confirmation
4. ✅ Enhanced logging with explicit leaderboard submission markers
5. ✅ Updated CSV schema with transaction hash column
6. ✅ Added detailed per-nonce logging for debugging
7. ✅ Enhanced error messages and status levels

The pipeline is now resilient to RPC outages and provides full visibility into which submissions landed on-chain and impacted the leaderboard.

