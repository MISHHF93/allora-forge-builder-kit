# 🔍 Why Your Submissions Aren't Showing on the Leaderboard

## Executive Summary

Your submissions **are reaching the blockchain** (transaction hashes confirm this), but they're **not appearing on the leaderboard** because one or more of these requirements aren't being met:

### ⚠️ **CRITICAL REQUIREMENT** 
**Submissions can ONLY appear on leaderboards when submitted to UNFULFILLED NONCES.**

If there are no unfulfilled nonces available for the topic, your submission:
- ✅ Will be accepted by the network
- ✅ Will get a transaction hash
- ✅ Will be recorded on-chain
- ❌ **Will NOT appear on the leaderboard**
- ❌ **Will NOT generate rewards**

---

## Root Cause Analysis

### Why This Happens: The Nonce System

Allora Network uses a **nonce-based validation system** for topic submissions:

```
┌─ EPOCH (1 hour)
│
├─ Worker submits prediction → claims NONCE
├─ Reputers observe nonce and prepare scores
├─ At epoch end → reputers submit scores
├─ Nonce becomes FULFILLED (used/scored)
│
└─ Next epoch starts → NEW NONCES created
```

**Key Insight:** A submission must attach to an **unfulfilled nonce** to:
1. Be recognized by reputers
2. Get scored
3. Appear on leaderboard
4. Generate rewards

### Scenarios Where Submissions Won't Appear

#### **Scenario 1: No Unfulfilled Nonces (Most Common)**
```
Problem:
- Topic created but no nonce requests were made
- All available nonces already used by other workers
- Topic quota for submissions reached
- Epoch just ended, new nonces not created yet

Result: Your transaction succeeds, but has nothing to attach to
```

**Evidence in Your Logs:**
```
2025-11-21T04:43:41.921986 → TX Hash: 76A4C138... ✅ (on-chain)
2025-11-21T10:49:30.000138 → TX Hash: 81A46022... ✅ (on-chain)
2025-11-21T12:29:04.595648 → TX Hash: 0A642E1C... ✅ (on-chain)
2025-11-21T13:14:10.236459 → TX Hash: 239BCAAF... ✅ (on-chain)

BUT: Check leaderboard → 🔴 NOT VISIBLE
```

#### **Scenario 2: Outside Submission Window**
```
Problem:
- Submissions can only happen in the last ~10 minutes of each epoch
- You're submitting at the beginning/middle of an epoch
- Submission window hasn't opened yet or already closed

Result: Submission accepted but not eligible for that epoch
```

#### **Scenario 3: No Active Reputers**
```
Problem:
- Topic exists but no reputers are running
- Without reputers, there's no one to validate/score submissions
- Submissions can be made, but won't be processed

Result: Submission recorded but won't be scored or appear
```

#### **Scenario 4: Insufficient Wallet Balance**
```
Problem:
- Out of gas (ALLO token balance too low)
- Transaction fails on-chain (but may still report partial success)

Result: Failed submission reports error or timeout
```

---

## Diagnosis: How to Check Your Specific Problem

### **Step 1: Check if Unfulfilled Nonces Exist**

```bash
# This is the PRIMARY check - if empty, submissions won't appear
allorad q emissions unfulfilled-worker-nonces 67 --chain-id allora-testnet-1

# Expected output (GOOD):
# nonces:
# - nonce: "123456"
#   block_height: 5000000
# - nonce: "123457"
#   block_height: 5000010

# Expected output (BAD - THIS IS YOUR ISSUE):
# nonces: []  # Empty list = no available nonces
```

If the result is empty (`nonces: []`), **this is why your submissions don't appear**.

### **Step 2: Check if Topic is Active**

```bash
allorad q emissions is-topic-active 67 --chain-id allora-testnet-1

# Expected:
# active: true
```

If `active: false`, topic isn't accepting submissions.

### **Step 3: Check if Reputers are Present**

```bash
allorad q emissions active-reputers 67 --chain-id allora-testnet-1

# Expected:
# reputers:
# - "allora1xxxxxx..."
# - "allora1yyyyyy..."

# Bad:
# reputers: []  # No one to score submissions
```

### **Step 4: Check Your Wallet Balance**

```bash
allorad q bank balances allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma \
  --chain-id allora-testnet-1

# Expected (GOOD):
# balances:
# - amount: "251000000000000000000"  # 251 ALLO
#   denom: uallo

# Bad:
# balances: []  # No ALLO for gas
```

### **Step 5: Check Submission Window Timing**

```bash
# Get topic epoch configuration
allorad q emissions topic 67 --chain-id allora-testnet-1

# Look for:
# epoch_length: 3600  # 1 hour in seconds
# worker_submission_window: 600  # Last 10 min of epoch

# Current block time:
allorad status --chain-id allora-testnet-1 | jq '.sync_info.latest_block_time'

# If current_time % 3600 >= (3600 - 600):
#   → You're in the submission window ✅
# Else:
#   → Wait for the submission window to start ⏳
```

---

## Automated Diagnostics: Use Our Tools

### **Quick Diagnosis**

```bash
# Run comprehensive diagnostics
python diagnose_leaderboard_visibility.py

# Set wallet (optional):
ALLORA_WALLET_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma" \
  python diagnose_leaderboard_visibility.py

# Output will tell you:
# ✅ Topic is active
# ❌ NO UNFULFILLED NONCES (likely cause!)
# ⚠️  Reputers status
# ✅ Wallet balance OK
# 🕐 Submission window status
```

### **Pre-Submission Validation**

```bash
# Validate before submitting
python -c "
import asyncio
from allora_forge_builder_kit.submission_validator import validate_before_submission

is_valid, issues = asyncio.run(
    validate_before_submission(
        topic_id=67,
        wallet_addr='allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma'
    )
)

if not is_valid:
    for issue in issues:
        print(f'❌ {issue}')
else:
    print('✅ Safe to submit!')
"
```

---

## Solutions & Action Items

### **If No Unfulfilled Nonces (Most Likely)**

**This means:** The topic doesn't have active nonce requests at this moment.

**Why it happens:**
- Topic may not be fully set up yet
- Nonce requests are created on-demand (not always available)
- All available nonces already used
- No active consumers/inferrers requesting predictions

**Solutions:**

1. **Check if topic is truly active:**
   ```bash
   allorad q emissions topic 67 --chain-id allora-testnet-1 | grep active
   ```

2. **Wait for nonces to be created:**
   - Nonces are typically created when topic needs predictions
   - May take a few minutes or require consumer demand
   - Try submitting again in 5-10 minutes

3. **Verify submission timing:**
   - Ensure you're submitting in the last 10 minutes of an hour
   - The submission window is: `59:00-59:59` of each hour (approximately)

4. **Contact Allora Support:**
   - Ask if topic 67 has active nonce requests
   - Verify reputers are running for the topic
   - Check if campaign is still active

### **If Topic Not Active**

```bash
# Check topic status
allorad q emissions topic 67 --chain-id allora-testnet-1

# Action: Contact Allora support, topic may need to be activated
```

### **If No Reputers**

```bash
# Check reputers
allorad q emissions active-reputers 67 --chain-id allora-testnet-1

# Action: Reputers must be running for topic to function
# Contact: Allora Network team
```

### **If Wallet Low on Balance**

```bash
# Request testnet ALLO faucet:
# https://faucet.allora.network/
# or contact support
```

---

## Updated Pipeline Code: Validation Before Submit

Your `competition_submission.py` should validate before each submission:

```python
# At the start of submission cycle:
from allora_forge_builder_kit.submission_validator import validate_before_submission

# Before submitting prediction:
is_valid, issues = await validate_before_submission(
    topic_id=COMPETITION_TOPIC_ID,
    wallet_addr=wallet_addr,
    strict=False  # Don't fail on warnings, only critical issues
)

if not is_valid:
    logger.error(f"❌ Submission validation failed: {issues}")
    logger.error("Skipping this submission cycle")
    return None, 1, "validation_failed"

# Continue with submission
```

### **Enhanced Submission Function**

```python
async def submit_prediction_sdk_with_validation(
    topic_id: int,
    prediction: float,
    wallet_name: str,
    root_dir: str,
    timeout_s: int = 30,
) -> Tuple[Optional[str], int, str]:
    """Submit prediction with pre-validation."""
    
    # Step 1: Validate submission eligibility
    logger.info("📋 Validating submission eligibility...")
    wallet_addr = os.getenv("ALLORA_WALLET_ADDR")
    
    from allora_forge_builder_kit.submission_validator import validate_before_submission
    
    is_valid, issues = await validate_before_submission(
        topic_id=topic_id,
        wallet_addr=wallet_addr,
        strict=False
    )
    
    if not is_valid:
        logger.error(f"❌ Validation failed:")
        for issue in issues:
            logger.error(f"   • {issue}")
        
        # Check if critical issue
        critical = [i for i in issues if i.startswith("CRITICAL")]
        if critical:
            logger.error("   🔴 Critical issues prevent submission")
            return None, 1, "validation_failed_critical"
        else:
            logger.warning("   ⚠️  Warnings only - proceeding with caution")
    
    # Step 2: Proceed with submission (existing code)
    return await submit_prediction_sdk(
        topic_id, prediction, wallet_name, root_dir, timeout_s
    )
```

---

## Checking Leaderboard Status

### **Manual Check: Query On-Chain Scores**

```bash
# Get your inferer score/EMA for the topic
allorad q emissions inferer-score-ema 67 \
  allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma \
  --chain-id allora-testnet-1

# Output:
# count: 4        # Number of submissions scored
# ema: 0.8234     # Your EMA score
# latest: 0.72    # Most recent prediction score

# If count > 0: ✅ Your submissions ARE being scored and visible
# If count = 0: ❌ No submissions have been scored (probably no nonces)
```

### **Web Check: Allora Dashboard**

Visit: `https://forge.allora.network`
- Go to Topic 67
- Check "Submissions" tab
- Look for your wallet address: `allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma`

---

## Complete Troubleshooting Flowchart

```
START
  ↓
Q: Do your transactions have hashes in competition_submissions.csv?
├─ NO: Check network/wallet errors
│ └─ Fix: Retry with valid wallet and gas
│
└─ YES (you're here)
  ↓
Q: allorad q emissions unfulfilled-worker-nonces 67 → returns anything?
├─ NO (empty list): 🔴 THIS IS YOUR ISSUE
│ └─ Nonces don't exist for submissions to attach to
│ └─ FIX: 
│    1. Verify topic 67 is active and has reputers
│    2. Check if you're in submission window (last 10 min of hour)
│    3. Wait for nonces to be created (may take time)
│    4. Contact Allora if topic isn't working
│
└─ YES: Nonces exist
  ↓
Q: allorad q emissions active-reputers 67 → returns reputers?
├─ NO (empty): 🟡 ISSUE: No one to score submissions
│ └─ FIX: Contact Allora, reputers must be active
│
└─ YES: Reputers exist
  ↓
Q: allorad q emissions inferer-score-ema 67 YOUR_WALLET → count > 0?
├─ YES: ✅ YOUR SUBMISSIONS ARE BEING SCORED AND ARE VISIBLE
│ └─ Allow 2-5 min for blockchain confirmation
│ └─ Allow another 1-2 min for reputers to score
│ └─ Should appear on leaderboard shortly
│
└─ NO: Count = 0
  ↓
Q: Did you submit during last 10 minutes of the hour?
├─ NO: 🟡 ISSUE: Outside submission window
│ └─ FIX: Only submit during last ~10 min of each hour
│
└─ YES (you're in window)
  ↓
Q: Is your wallet balance > 0.1 ALLO?
├─ NO: 🟡 ISSUE: Insufficient gas
│ └─ FIX: Get ALLO from faucet or request
│
└─ YES: Sufficient balance
  ↓
✅ CONTACT ALLORA SUPPORT
   Provide: TX hashes + this diagnostic output
   They'll investigate submission processing
```

---

## Summary: The Most Likely Problem

**Your submissions probably aren't appearing because:**

```
┌─────────────────────────────────────────────┐
│ NO UNFULFILLED NONCES ON TOPIC 67           │
├─────────────────────────────────────────────┤
│ Your TX submits fine, but has no nonce to   │
│ attach to, so it doesn't generate a score   │
│ or appear on the leaderboard.               │
│                                             │
│ Run this to confirm:                        │
│ allorad q emissions                         │
│   unfulfilled-worker-nonces 67              │
│   --chain-id allora-testnet-1               │
│                                             │
│ If empty → This is the problem              │
└─────────────────────────────────────────────┘
```

**Action:**
1. Run diagnostic tool
2. Check for unfulfilled nonces
3. If empty, contact Allora support to verify topic is properly set up
4. Otherwise, implement pre-submission validation before each cycle

---

## Files to Use

| File | Purpose |
|------|---------|
| `diagnose_leaderboard_visibility.py` | Quick one-command diagnostics |
| `allora_forge_builder_kit/submission_validator.py` | Pre-submission validation in code |
| This document | Understanding the root cause |

```bash
# Run diagnostics
python diagnose_leaderboard_visibility.py

# Or integrate validation into your pipeline:
from allora_forge_builder_kit.submission_validator import validate_before_submission
```

---

**Last Updated:** November 21, 2025  
**Topic:** 67 (7-day BTC/USD Log-Return Prediction)  
**Wallet:** `allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma`
