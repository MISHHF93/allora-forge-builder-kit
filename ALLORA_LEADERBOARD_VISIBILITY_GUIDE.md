# Allora Network Leaderboard Visibility & Submission Requirements

## Executive Summary

Based on analysis of the Allora SDK, network protocols, and production code patterns, this guide details what controls leaderboard visibility, submission acceptance, and when participants can earn rewards on the Allora Network.

---

## 1. Submission Visibility Requirements

### 1.1 Primary Requirement: Unfulfilled Nonces
**The core mechanism for submission visibility is the unfulfilled nonce system.**

- **What it is**: An unfulfilled nonce represents a pending prediction request from the network for a specific topic at a specific epoch
- **How it appears**: When `allorad q emissions unfulfilled-worker-nonces <topic_id>` returns a non-empty set
- **Submission requirement**: A submission can ONLY be made if an unfulfilled nonce exists
- **Visibility trigger**: Submitting to an unfulfilled nonce makes the submission visible and trackable on the leaderboard

**Implementation Pattern** (from `train.py`):
```python
unfulfilled_worker_nonces = _run_allorad_json(["q", "emissions", "unfulfilled-worker-nonces", topic_str])
if unfulfilled_worker_nonces and len(unfulfilled_worker_nonces) > 0:
    # Submission can proceed and will be visible
    worker.submit(prediction_value, nonce)
else:
    # No pending requests - submission will not be visible/recorded
    # Worker continues polling waiting for nonce to appear
```

### 1.2 Nonce Generation Frequency

**Nonces are created per epoch**, not per submission:
- Epoch length is topic-specific (e.g., 3600 seconds = 1 hour for many topics)
- Each epoch boundary, the network generates new unfulfilled nonces for active topics
- Query frequency: Continuous polling (typically every few seconds) to detect when nonces appear

**Example Timeline**:
```
11:00 UTC - Epoch begins, unfulfilled nonce generated (e.g., nonce 6619915)
11:00-12:00 - Workers submit to nonce 6619915 - submissions VISIBLE
12:00 UTC - Epoch ends, nonce fulfillment window closes
12:00+ - No more unfulfilled nonces until next epoch boundary
```

### 1.3 "Zero Unfulfilled Nonces" State

**Normal behavior** when `unfulfilled_worker_nonces = set()` or empty list:
- No pending prediction requests currently exist
- Submissions cannot be accepted at this time
- Workers enter waiting/polling mode
- This is **expected and not an error**

---

## 2. Topic Activity & Submission Acceptance

### 2.1 Topic Must Be "Active"

A topic must pass liveness checks to accept submissions:

**Activation Criteria** (`_validate_topic_creation_and_funding()` in train.py):

```
is_active = (
    ✅ Topic exists (is_topic_active == true)
    AND ✅ delegated_stake > 0 (minimum stake threshold met)
    AND ✅ reputers_count >= 1 (at least one reputer exists)
    AND ✅ effective_revenue > 0 (topic generating activity)
    AND ✅ weight_estimate > min_weight (weight not too low)
)
```

**Query to verify**:
```bash
allorad q emissions is-topic-active <topic_id>
# Returns true/false
```

**If topic is inactive**, submissions are rejected with reasons like:
- `missing_stake` - delegated_stake is null or 0
- `reputers_missing` - no active reputers (reputers_count < 1)
- `inactive_from_chain` - is_topic_active = false on-chain
- `weight_below_minimum` - topic weight too low

### 2.2 Reputer Requirements for Active Topics

**Minimum viable setup**:
- At least 1 active reputer must exist
- Reputers score submissions and generate rewards
- Without reputers, a topic cannot validate predictions

**Query active reputers**:
```bash
allorad q emissions active-reputers <topic_id>
```

**Fallback logic**: If REST endpoints return 501 errors, the system estimates reputers_count = 1 if the topic is queryable and operational.

### 2.3 Delegated Stake Requirement

**For submissions to be rewardable**:
- Topic must have `delegated_stake > 0`
- This represents total stake delegated to topic participants
- Minimum stake varies by network but defaults conservatively

**Fallback behavior**: When REST APIs unavailable, stake is assumed to exist if topic is otherwise functional.

---

## 3. Epoch Timing & Submission Windows

### 3.1 Epoch Structure

```
Parameter              | Typical Value | Description
-----------           | ------------- | -----------
epoch_length          | 3600 seconds  | Duration of one epoch (commonly 1 hour)
ground_truth_lag      | 3600 seconds  | Delay before ground truth becomes available
worker_submission_window | 600 seconds | Duration predictions can be submitted (10 minutes)
```

**Query to retrieve**:
```bash
allorad q emissions topic <topic_id>
# Returns: epochLength, groundTruthLag, workerSubmissionWindow
```

### 3.2 Submission Window Mechanics

**Submission window** is the time period within an epoch when workers can submit:

```
Window = Last (worker_submission_window) seconds of the epoch
Example (for 1-hour epoch, 10-minute window):
  - Epoch: 12:00-13:00
  - Submission window: 12:50-13:00 (last 10 minutes)
  - Submissions outside this window are rejected
```

**State calculation** (from `train.py`):
```python
blocks_in_epoch = epoch_length_seconds / 12  # ~12s per block
blocks_remaining_in_epoch = current_block % blocks_in_epoch

submission_window_open = (
    0 < blocks_remaining_in_epoch <= (worker_submission_window / 12)
)

submission_window_state = {
    "is_open": submission_window_open,
    "blocks_remaining": blocks_remaining_in_epoch,
    "window_size": worker_submission_window_seconds
}
```

### 3.3 Propagation Delay

**From submission to blockchain finality**:
- Submit tx → 2-5 seconds for consensus (testnet)
- Blocks finalized → Nonce fulfilled
- Score availability → Additional 1-2 epochs (depends on reputer latency)

**Submission success doesn't mean immediate leaderboard visibility**:
- Immediate: Transaction accepted, nonce marked fulfilled
- Delayed (1-2 minutes): Score calculated by reputers
- Delayed (epoch boundaries): Reward distribution processed

---

## 4. Leaderboard Visibility Determinants

### 4.1 What Makes a Submission Visible

A submission appears on the leaderboard when:

1. ✅ **Submitted to an unfulfilled nonce** (fulfills the nonce)
2. ✅ **Transaction confirmed** (code: 0, no errors)
3. ✅ **Score is calculated** (reputer processes within 1-2 epochs)
4. ✅ **Topic is active** (meets all liveness criteria)
5. ✅ **Submission is within window** (submitted during worker_submission_window)

### 4.2 Score & Reward Extraction

**Score availability**:
```bash
allorad q emissions inferer-score-ema <topic_id> <wallet_address>
```

- Score may not be immediately available after submission
- Appears after reputer processes (typically 1-2 minutes)
- Stored as EMA (Exponential Moving Average) of performance

**Reward extraction**:
- Found in transaction events: `coin_received` with denom `uallo`
- Available in transaction logs after finalization
- Distributed per epoch based on score ranking

### 4.3 "Rewardable" State

A topic enters rewardable state when:
```python
is_rewardable = (
    unfulfilled_worker_nonces is not None 
    and int(unfulfilled_worker_nonces) == 0
)
```

- Means: All pending nonces have been fulfilled
- Indicates: Epoch is settling, rewards are being calculated
- Not a requirement for submission, but signals healthy network state

---

## 5. Minimum Submission Thresholds

### 5.1 Per-Submission Requirements

Each submission must meet:
- **Value**: Any float (prediction)
- **Topic**: Must exist and be active
- **Nonce**: Must have an unfulfilled nonce
- **Wallet**: Must have sufficient balance for gas (typically >0.001 ALLO)
- **Window**: Must be within submission window

### 5.2 Leaderboard Inclusion Minimum

For participation to be recorded:
- ✅ Minimum 1 submission per epoch (if nonce available)
- ✅ Consistent participation (each epoch with nonces)
- ✅ Valid predictions (within acceptable range)

**No explicit threshold**, but:
- First submission: Immediately visible on leaderboard after score calc
- Multiple submissions: Tracked in leaderboard history
- Zero submissions: No leaderboard entry for that epoch

---

## 6. Campaign & Gating Mechanisms

### 6.1 Competition Deadlines

Some topics have explicit deadline campaigns:
```python
# Example: Topic 67 may have a deadline
deadline_info = get_deadline_info(topic_id=67)
# Returns: {"deadline": "2025-01-15T23:59:59Z", "is_active": True}
```

**Deadline impact**:
- Submissions accepted until deadline
- After deadline: Leaderboard frozen, no new submissions
- Resets per competition cycle

**Query format** (from `competition_deadline.py`):
```bash
allorad q emissions deadline <topic_id>
# or REST endpoint: /allora/emissions/topic/<topic_id>/deadline
```

### 6.2 Topic-Specific Gating

Additional constraints may apply:

**Quantile-based gates**:
```python
active_inferer_quantile      # Min performance rank to be eligible
active_forecaster_quantile   # Min forecast quality required
active_reputer_quantile      # Min reputer stake to earn
```

**Weight-based gates**:
```python
weight_estimate = sqrt(delegated_stake) * sqrt(effective_revenue)
is_eligible = weight_estimate > min_weight_threshold
```

If weight too low, topic enters "churnable" state - submissions still accepted but with reduced visibility.

---

## 7. Topic Status Verification

### 7.1 Pre-Flight Checks (Recommended)

Before submitting, verify:

```python
def check_topic_submission_ready(topic_id: int):
    # 1. Topic is active
    active = check_is_topic_active(topic_id)
    assert active, "Topic not active"
    
    # 2. At least one reputer exists
    reputers = query_active_reputers(topic_id)
    assert len(reputers) >= 1, "No reputers"
    
    # 3. Delegated stake exists
    stake = query_delegated_stake(topic_id)
    assert stake > 0, "No stake"
    
    # 4. Effective revenue positive
    revenue = query_effective_revenue(topic_id)
    assert revenue > 0, "No revenue"
    
    # 5. Weight meets minimum
    weight = calculate_weight_estimate(topic_id)
    assert weight > min_weight, "Weight too low"
    
    # 6. Unfulfilled nonces exist (or wait for them)
    unfulfilled = query_unfulfilled_worker_nonces(topic_id)
    if not unfulfilled:
        wait_for_nonce_or_timeout(topic_id)
    
    return {
        "is_active": True,
        "unfulfilled_nonces": len(unfulfilled),
        "reputers_count": len(reputers),
        "ready_to_submit": len(unfulfilled) > 0
    }
```

### 7.2 CLI Commands for Verification

```bash
# Check if topic is active
allorad q emissions is-topic-active 67

# List unfulfilled nonces
allorad q emissions unfulfilled-worker-nonces 67

# Get active reputers
allorad q emissions active-reputers 67

# Get topic details
allorad q emissions topic 67

# Get delegated stake
allorad q emissions topic-stake 67

# Check effective revenue
allorad q emissions topic-fee-revenue 67

# Verify emission parameters
allorad q emissions params

# Query your score
allorad q emissions inferer-score-ema 67 <wallet_address>
```

---

## 8. Visibility State Machine

```
┌─────────────────────────────────────────────────────┐
│ TOPIC LIFECYCLE                                     │
└─────────────────────────────────────────────────────┘

State: INACTIVE (is_active = false)
├─ Cause: No reputers, no stake, or inactive flag
├─ Submissions: REJECTED
└─ Leaderboard: NO ENTRY

     ↓ [Topic funded, reputers join]

State: ACTIVE (is_active = true)
├─ Cause: All activation criteria met
├─ Submissions: ACCEPTED (if unfulfilled nonces exist)
├─ Leaderboard: ENTRIES VISIBLE (after score calc)
└─ Next: Awaiting epoch to generate nonces

     ↓ [Epoch begins, nonces generated]

State: SUBMISSIONS_OPEN
├─ Unfulfilled nonces: N > 0
├─ Submission window: OPEN
├─ Submissions: IMMEDIATELY VISIBLE
└─ Leaderboard: REAL-TIME UPDATES

     ↓ [Epoch end, nonces fulfilled]

State: SETTLING
├─ Unfulfilled nonces: 0
├─ is_rewardable: true
├─ Submissions: REJECTED (no nonces)
├─ Leaderboard: FINALIZED
└─ Reputers: Calculating rewards

     ↓ [Rewards distributed]

State: EPOCH_CLOSED
├─ Submissions: REJECTED (epoch over)
├─ Leaderboard: HISTORICAL
└─ Next epoch: Loop back to ACTIVE
```

---

## 9. Practical Implementation Patterns

### 9.1 Production Submission Flow

```python
# From train.py - proven production pattern

async def submit_with_visibility_checks(prediction: float, topic_id: int):
    """Production-grade submission with visibility guarantees."""
    
    # Step 1: Verify topic is active
    topic_info = _get_topic_info(topic_id)
    if not topic_info.get("is_topic_active"):
        log.error(f"Topic {topic_id} not active")
        return SubmissionResult(False, "inactive_topic")
    
    # Step 2: Verify reputers exist (needed for scoring)
    reputers = topic_info.get("reputers_count", 0)
    if reputers < 1:
        log.error(f"Topic {topic_id} has no reputers")
        return SubmissionResult(False, "no_reputers")
    
    # Step 3: Check for unfulfilled nonces (visibility trigger)
    unfulfilled = topic_info.get("unfulfilled_worker_nonces", set())
    if not unfulfilled:
        log.warning(f"No unfulfilled nonces for topic {topic_id}")
        # Submissions won't be visible; wait or return
        return SubmissionResult(False, "no_unfulfilled_nonces")
    
    # Step 4: Submit prediction (will be visible)
    try:
        worker = AlloraWorker(
            run=lambda _: float(prediction),
            wallet=wallet_config,
            network=network_config,
            topic_id=topic_id,
            polling_interval=120  # Wait up to 2 min for window
        )
        result = await worker.run(timeout=120)
        
        # Step 5: Extract score and nonce (visibility confirmations)
        tx_result = result.tx_result
        nonce = extract_nonce(tx_result)
        score = extract_score(tx_result)
        
        log.info(f"Submission visible: nonce={nonce}, score={score}")
        return SubmissionResult(True, tx_hash, nonce, score)
        
    except asyncio.TimeoutError:
        log.error("Submission window closed")
        return SubmissionResult(False, "submission_window_closed")
    except Exception as e:
        log.error(f"Submission failed: {e}")
        return SubmissionResult(False, str(e))
```

### 9.2 Leaderboard Position Estimation

```python
def estimate_leaderboard_visibility(topic_id: int, wallet: str):
    """Estimate if submission will appear on leaderboard."""
    
    checks = {
        "topic_active": _get_topic_info(topic_id).get("is_topic_active"),
        "has_reputers": _get_topic_info(topic_id).get("reputers_count", 0) >= 1,
        "has_unfulfilled_nonces": len(_query_unfulfilled_nonces(topic_id)) > 0,
        "in_submission_window": check_submission_window(topic_id),
        "sufficient_balance": check_wallet_balance(wallet) > 0.001,
        "no_deadline_passed": check_deadline_active(topic_id),
    }
    
    visibility_confidence = sum(checks.values()) / len(checks)
    
    return {
        "will_be_visible": all(checks.values()),
        "confidence": visibility_confidence,
        "blockers": [k for k, v in checks.items() if not v],
        "estimated_appearance_time": "1-2 minutes after submission (score calculation)"
    }
```

---

## 10. Key Takeaways

| Aspect | Requirement | Impact |
|--------|-------------|--------|
| **Unfulfilled Nonce** | MANDATORY | Without it, submission cannot be recorded at all |
| **Topic Active** | MANDATORY | Must pass liveness checks (stake, reputers, revenue) |
| **Active Reputers** | MANDATORY (≥1) | Needed to score and rank submissions |
| **Delegated Stake** | MANDATORY (>0) | Signals topic economic viability |
| **Submission Window** | CONDITIONAL | Must be within epoch's submission window |
| **Score Propagation** | 1-2 min delay | Leaderboard shows score after reputer calculation |
| **Minimum Submissions** | None (per epoch) | First submission visible, can submit as frequently as nonces appear |
| **Campaign Deadlines** | Topic-specific | May restrict submission eligibility to date range |
| **Weight Ranking** | Influences rewards | Low weight = reduced reward potential |

---

## 11. Troubleshooting Visibility Issues

### Issue: Submission succeeds but doesn't appear on leaderboard

**Diagnosis**:
1. Check: `allorad q emissions unfulfilled-worker-nonces 67` - If empty, submission not recorded
2. Check: `allorad q emissions is-topic-active 67` - If false, topic inactive
3. Check: `allorad q emissions active-reputers 67` - If none, no scoring possible
4. Check: Score availability - `allorad q emissions inferer-score-ema 67 <wallet>` after 2 minutes

**Resolution**:
- If no unfulfilled nonces: Wait for next epoch or verify topic has requests
- If topic inactive: Verify delegated_stake and reputers exist
- If no reputers: Topic cannot score submissions - may be bootstrapping
- If score unavailable: Wait 1-2 minutes, reputers may be processing

### Issue: "0 unfulfilled nonces" state persists

**This is normal when**:
- Epoch is settling and fulfillments processing
- Very few workers requesting predictions (low demand)
- Network has recent surge (all nonces filled quickly)

**Action**: Continue polling - next nonces will appear at epoch boundary

### Issue: Topic exists but submissions rejected

**Check**:
1. Wallet has sufficient ALLO for gas (`> 0.001 ALLO`)
2. Submission within window: `submission_window_open == True`
3. Topic weight not critically low: `weight_rank <= total/2`
4. Submission not already made this epoch: Check `submission_log.csv`

---

## 12. References & Related Queries

### Allora SDK Integration Points
- `AlloraWorker` - Handles nonce polling and submission
- `AlloraRPCClient` - Queries unfulfilled nonces
- `AlloraNetworkConfig` - Topic and epoch configuration

### Chain Query Patterns
- `/allora/emissions/unfulfilled-worker-nonces/<topic>` - REST endpoint
- `q emissions unfulfilled-worker-nonces <topic>` - CLI command
- `/allora/emissions/topic/<topic_id>/deadline` - Deadline check

### Monitoring Metrics
- `unfulfilled_worker_nonces` count - Pending requests
- `is_rewardable` - Epoch settling indicator  
- `active_reputers` count - Scoring capability
- `delegated_stake` - Economic viability
- `effective_revenue` - Network activity

---

**Last Updated**: 2025-11-21
**Based on**: Allora SDK Analysis, Production Implementation, Testnet Observations
