# Competition Time-Bound Deadline Control

**Competition Period:** September 16, 2025, 13:00 UTC → December 15, 2025, 13:00 UTC  
**Duration:** ~90 days  
**Submission Frequency:** Hourly (configurable)  

---

## Overview

The pipeline now includes automatic time-bound control that ensures graceful shutdown when the competition deadline is reached. This prevents:

- ❌ Initiating new cycles that cannot be completed before deadline
- ❌ Requiring manual process termination  
- ❌ Cron jobs running past competition end
- ❌ Wasted resources on ineligible submissions

Instead, the system:

- ✅ Checks deadline before each cycle
- ✅ Stops cleanly when next cycle would exceed deadline
- ✅ Preserves all logging and submission records
- ✅ Returns graceful exit code (0)
- ✅ Displays deadline status to operators

---

## Module Architecture

### `competition_deadline.py`

Core deadline management utilities:

```python
from allora_forge_builder_kit.competition_deadline import (
    should_exit_loop,           # Check if next cycle exceeds deadline
    log_deadline_status,        # Display deadline info
    get_deadline_info,          # Get detailed deadline data
    is_deadline_exceeded,       # Check if deadline passed
    seconds_until_deadline,     # Get seconds remaining
    parse_iso_utc,             # Parse ISO 8601 datetime
)
```

**Key Functions:**

| Function | Purpose | Returns |
|----------|---------|---------|
| `should_exit_loop(cadence_hours)` | Determine if loop should exit | `(bool, str)` |
| `get_deadline_info()` | Get comprehensive deadline data | `dict` |
| `is_deadline_exceeded()` | Check if deadline has passed | `bool` |
| `log_deadline_status()` | Log formatted deadline status | `None` |
| `seconds_until_deadline()` | Get seconds until deadline | `float` |

---

## Integration with competition_submission.py

### Automatic Deadline Checking

The `run_competition_pipeline()` function now:

1. **Logs deadline status at startup**
   ```
   ═══════════════════════════════════════════════════════════════════
   COMPETITION DEADLINE STATUS
   ═══════════════════════════════════════════════════════════════════
   Deadline:          2025-12-15T13:00:00+00:00
   Current UTC:       2025-11-21T13:00:00+00:00
   Status:            🟢 ACTIVE
   Time Remaining:    24d 0h 0m remaining
   ═══════════════════════════════════════════════════════════════════
   ```

2. **Checks deadline before each cycle**
   ```python
   should_exit, exit_reason = should_exit_loop(cadence_hours=1.0)
   if should_exit:
       logger.info(exit_reason)
       return 0  # Exit gracefully
   ```

3. **Displays time remaining per cycle**
   ```
   ⏰ Time remaining: 24d 0h 0m remaining
   ```

4. **Stops gracefully when deadline approached**
   ```
   🎯 COMPETITION DEADLINE REACHED
   Insufficient time for next cycle...
   ✅ Pipeline stopped gracefully.
   ```

---

## Usage Examples

### Start Continuous Submissions (Auto-Stop at Deadline)

```bash
export MNEMONIC="tiger salmon health level chase..."
export ALLORA_WALLET_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"

# Run continuously - will stop automatically on Dec 15, 2025, 13:00 UTC
python competition_submission.py
```

**Output:**
```
✅ Environment verified
   Wallet: test-wallet
   Topic: 67 (7 Day BTC/USD Log-Return Prediction)
   Mode: Continuous (hourly until deadline)

═══════════════════════════════════════════════════════════════════
COMPETITION DEADLINE STATUS
═══════════════════════════════════════════════════════════════════
Deadline:          2025-12-15T13:00:00+00:00
Current UTC:       2025-11-21T12:00:00+00:00
Status:            🟢 ACTIVE
Time Remaining:    24d 1h 0m remaining
═══════════════════════════════════════════════════════════════════

======================================================================
SUBMISSION CYCLE 1
======================================================================
⏰ Time remaining: 24d 1h 0m remaining
📊 Generating training data...
🤖 Training XGBoost model...
📈 Evaluating model...
✅ Cycle 1 complete - submission successful!

⏳ Waiting 1 hour until next submission...
```

### Single Test Run (No Deadline Check)

```bash
# Test single submission without deadline control
python competition_submission.py --once
```

**Output:**
```
✅ Cycle 1 complete - submission successful!
```

---

## Behavior at Deadline

### 24 Hours Before Deadline

Pipeline continues normally, displays countdown:
```
⏰ Time remaining: 1d 0h 0m remaining
```

### 1 Hour Before Deadline

Pipeline detects next cycle would exceed deadline:
```
⏳ Waiting 1 hour until next submission...
(after sleep, deadline check triggers)

🎯 COMPETITION DEADLINE REACHED
═══════════════════════════════════════════════════════════════════
Insufficient time for next cycle.
Next cycle would start at 2025-12-15T14:00:00+00:00
(after deadline 2025-12-15T13:00:00+00:00).
Only 0.9h remaining.
Stopping cleanly to preserve final submission opportunity.
Deadline: 2025-12-15T13:00:00+00:00
Current:  2025-12-15T13:59:59+00:00
═══════════════════════════════════════════════════════════════════
✅ Pipeline stopped gracefully. All submissions completed.
```

### After Deadline Passes

```
🎯 COMPETITION DEADLINE REACHED
═══════════════════════════════════════════════════════════════════
Deadline exceeded at 2025-12-15T14:30:00+00:00. Competition ended.
═══════════════════════════════════════════════════════════════════
✅ Pipeline stopped gracefully. All submissions completed.
```

---

## Deployment Scenarios

### Scenario 1: Long-Running Process (Recommended)

**Setup:**
```bash
# Start at any time during competition window
nohup python competition_submission.py > competition.log 2>&1 &
echo $! > competition.pid
```

**Behavior:**
- Runs continuously for ~90 days
- Stops automatically on Dec 15, 2025, 13:00 UTC
- No manual intervention needed
- No cron restart required
- All logs preserved in `competition.log`

**Monitoring:**
```bash
# Check status
tail -f competition.log

# Verify process
cat competition.pid

# View submissions
tail -20 competition_submissions.csv
```

**Cleanup:**
```bash
# After process completes naturally, verify completion
grep "Pipeline stopped gracefully" competition.log

# View final submission count
wc -l competition_submissions.csv
```

### Scenario 2: Systemd Service (Production)

**Create `/etc/systemd/system/allora-competition.service`:**
```ini
[Unit]
Description=Allora Competition Pipeline
After=network.target

[Service]
Type=simple
WorkingDirectory=/workspaces/allora-forge-builder-kit
Environment="MNEMONIC=tiger salmon health level..."
Environment="ALLORA_WALLET_ADDR=allo1cxvw0..."
ExecStart=/usr/bin/python3 competition_submission.py
Restart=no
StandardOutput=append:/var/log/allora-competition.log
StandardError=append:/var/log/allora-competition.log
User=ubuntu

[Install]
WantedBy=multi-user.target
```

**Usage:**
```bash
# Start service
sudo systemctl start allora-competition

# View logs
sudo journalctl -u allora-competition -f

# Check status
sudo systemctl status allora-competition

# (Service stops automatically at deadline)
```

### Scenario 3: Docker Container

**Dockerfile:**
```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN pip install -r requirements.txt

ENV MNEMONIC=<from-env>
ENV ALLORA_WALLET_ADDR=<from-env>

CMD ["python", "competition_submission.py"]
```

**Run:**
```bash
docker run -e MNEMONIC="..." -e ALLORA_WALLET_ADDR="..." \
  --volume competition_data:/app/data \
  allora-competition
```

**Behavior:**
- Container starts at any time
- Runs hourly until deadline
- Container exits gracefully (code 0) at deadline
- Kubernetes/Nomad can detect exit and clean up naturally

---

## Configuration & Customization

### Current Competition Window

Defined in `competition_deadline.py`:

```python
COMPETITION_START_UTC = "2025-09-16T13:00:00Z"  # Sep 16, 2025, 13:00 UTC
COMPETITION_END_UTC = "2025-12-15T13:00:00Z"    # Dec 15, 2025, 13:00 UTC
```

### Modifying for Future Competitions

Update these constants in `competition_deadline.py`:

```python
# For a new competition:
COMPETITION_START_UTC = "2026-01-01T00:00:00Z"
COMPETITION_END_UTC = "2026-12-31T23:59:59Z"
```

No changes needed to submission pipeline code.

### Cadence Configuration

Control submission frequency in `competition_submission.py`:

```python
SUBMISSION_INTERVAL_HOURS = 1  # Change to 6, 12, 24, etc.
```

The deadline logic automatically adjusts:
- If cadence is 1h: stops at 13:00 UTC (1h before deadline)
- If cadence is 6h: stops at 07:00 UTC (6h before deadline)  
- If cadence is 24h: stops at 13:00 UTC previous day (24h before deadline)

---

## Monitoring & Debugging

### Check Deadline Status

```bash
python -c "
from allora_forge_builder_kit.competition_deadline import get_deadline_info
import json
info = get_deadline_info()
print(json.dumps(info, indent=2, default=str))
"
```

**Output:**
```json
{
  "deadline": "2025-12-15T13:00:00+00:00",
  "current_utc": "2025-11-21T12:00:00+00:00",
  "is_active": true,
  "is_exceeded": false,
  "time_remaining": 2101200.0,
  "formatted_remaining": "24d 4h 20m remaining"
}
```

### Verify Module Integration

```bash
python -c "
from allora_forge_builder_kit.competition_deadline import should_exit_loop
should_exit, reason = should_exit_loop(cadence_hours=1.0)
print(f'Should exit: {should_exit}')
print(f'Reason: {reason}')
"
```

### Watch Live Deadline Countdown

```bash
watch -n 60 'python -c "from allora_forge_builder_kit.competition_deadline import get_deadline_info; info = get_deadline_info(); print(info[\"formatted_remaining\"])"'
```

---

## Error Handling

The system handles edge cases gracefully:

| Scenario | Behavior |
|----------|----------|
| Process starts after deadline | Detects immediately, exits with status 0 |
| Deadline configuration invalid | Raises `ValueError` at module import |
| System clock skewed | Uses UTC for consistency, handles gracefully |
| Network issues during submission | Retries within cycle, respects deadline |
| User presses Ctrl+C | Stops gracefully, returns 0 |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success - cycle completed OR deadline reached |
| `1` | Initialization/environment error |
| `2` | Network/submission timeout |
| `3` | Wallet not whitelisted |

**Deadline-triggered exit always returns `0`** (graceful shutdown).

---

## Logging & Audit Trail

All deadline-related events logged to:
- `competition_submissions.log` - submission details
- `pipeline_run.log` - training/model details
- `competition_submissions.csv` - structured submission records

### Final Submission Record

Last row in CSV shows final eligible submission:

```csv
timestamp,topic_id,prediction,tx_hash,nonce,status
2025-12-15T12:59:04.595648+00:00,67,-2.9062538146972656,0A642E1C44E4...,6619915,success
```

---

## Verification Checklist

Before deploying to production, verify:

- [ ] `MNEMONIC` environment variable set correctly
- [ ] `ALLORA_WALLET_ADDR` environment variable set
- [ ] Wallet has sufficient balance (251+ billion ALLO)
- [ ] Network connectivity to Allora testnet verified
- [ ] Deadline constants match competition rules
- [ ] `competition_deadline.py` module imports without error
- [ ] `competition_submission.py` shows deadline status at startup
- [ ] Test run with `--once` completes successfully

---

## Next Steps

1. **Start Pipeline**
   ```bash
   export MNEMONIC="..."
   export ALLORA_WALLET_ADDR="..."
   python competition_submission.py
   ```

2. **Monitor Submissions**
   ```bash
   tail -f competition_submissions.log
   ```

3. **Verify Deadline Control**
   - Observe deadline countdown in logs
   - Confirm automatic stop at deadline
   - No manual intervention required

4. **Archive Results**
   - Save `competition_submissions.csv`
   - Save `competition_submissions.log`
   - Calculate final metrics

---

## Support & Troubleshooting

### Pipeline Not Stopping at Deadline

**Check:**
```bash
python -c "
from allora_forge_builder_kit.competition_deadline import is_deadline_exceeded
print('Deadline exceeded:', is_deadline_exceeded())
"
```

If `False` but expected to be `True`, check system clock:
```bash
date -u
```

### Unclear Deadline Status

**View:** `python -c "from allora_forge_builder_kit.competition_deadline import log_deadline_status; log_deadline_status()"`

### Need Early Exit

**Manual stop:** `Ctrl+C` (graceful)

### Restart After Stoppage

The pipeline can be restarted anytime before deadline:
```bash
python competition_submission.py
```

It will resume from where it left off (based on submission log).

---

## Summary

✅ **Time-bound control is fully integrated**  
✅ **Automatic graceful shutdown at deadline**  
✅ **No manual intervention required**  
✅ **Comprehensive logging for audit trail**  
✅ **Production-ready for 90-day competition**  

🚀 **Ready to submit to Allora competition leaderboard!**
