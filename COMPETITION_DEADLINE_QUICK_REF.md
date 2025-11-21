# 🎯 Time-Bound Competition Control - Quick Reference

## What Changed

Your pipeline now has **automatic deadline control**. It will:

✅ Run continuously until **December 15, 2025, 13:00 UTC**  
✅ Check deadline before each hourly cycle  
✅ Exit gracefully when deadline is reached  
✅ Require NO manual intervention  
✅ Preserve all submissions and logs  

---

## Start Competition Submission Pipeline

```bash
# Set environment variables
export MNEMONIC="tiger salmon health level chase shift type enough glue cliff rubber pitch alert arrest novel goose doll sweet tired carbon visit custom soul random"
export ALLORA_WALLET_ADDR="allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"

# Start pipeline - runs until Dec 15, 2025, 13:00 UTC
python competition_submission.py
```

**Output:**
```
═══════════════════════════════════════════════════════════════════
COMPETITION DEADLINE STATUS
═══════════════════════════════════════════════════════════════════
Deadline:          2025-12-15T13:00:00+00:00
Current UTC:       2025-11-21T13:00:00+00:00
Status:            🟢 ACTIVE
Time Remaining:    24d 0h 0m remaining
═══════════════════════════════════════════════════════════════════

======================================================================
SUBMISSION CYCLE 1
======================================================================
⏰ Time remaining: 24d 0h 0m remaining
✅ Cycle 1 complete - submission successful!

⏳ Waiting 1 hour until next submission...
```

---

## What Happens at Deadline

### 1 Hour Before Deadline

```
⏳ Waiting 1 hour until next submission...
(sleep 3600 seconds)

🎯 COMPETITION DEADLINE REACHED
═══════════════════════════════════════════════════════════════════
Insufficient time for next cycle.
Next cycle would start at 2025-12-15T14:00:00+00:00
(after deadline 2025-12-15T13:00:00+00:00).
Only 0.9h remaining.
Stopping cleanly to preserve final submission opportunity.
═══════════════════════════════════════════════════════════════════
✅ Pipeline stopped gracefully. All submissions completed.
```

Process exits with status **0** (success).

---

## Monitoring

### View Live Submissions

```bash
# New terminal
tail -f competition_submissions.log
```

### Track Submissions CSV

```bash
# See all submissions
cat competition_submissions.csv

# Count submissions
wc -l competition_submissions.csv
```

### Check Deadline Status Anytime

```bash
python -c "
from allora_forge_builder_kit.competition_deadline import get_deadline_info
import json
info = get_deadline_info()
print(f'Status: {info[\"formatted_remaining\"]}')
print(f'Active: {info[\"is_active\"]}')
"
```

---

## Production Deployment

### Option 1: Nohup (Recommended)

```bash
nohup python competition_submission.py > competition.log 2>&1 &
echo $! > competition.pid
```

**Monitor:**
```bash
tail -f competition.log
```

**Cleanup after (it stops itself):**
```bash
kill $(cat competition.pid) 2>/dev/null || true
```

### Option 2: Systemd Service

Create `/etc/systemd/system/allora-competition.service`:

```ini
[Unit]
Description=Allora Competition Pipeline
After=network.target

[Service]
Type=simple
WorkingDirectory=/workspaces/allora-forge-builder-kit
Environment="MNEMONIC=..."
Environment="ALLORA_WALLET_ADDR=..."
ExecStart=/usr/bin/python3 competition_submission.py
Restart=no
StandardOutput=append:/var/log/allora-competition.log
StandardError=append:/var/log/allora-competition.log

[Install]
WantedBy=multi-user.target
```

**Usage:**
```bash
sudo systemctl start allora-competition
sudo journalctl -u allora-competition -f
```

Service stops automatically at deadline.

### Option 3: Docker

```bash
docker run -e MNEMONIC="..." \
  -e ALLORA_WALLET_ADDR="..." \
  -v $(pwd)/data:/app/data \
  allora-competition python competition_submission.py
```

Container exits at deadline (code 0).

---

## Key Architecture

### New Module: `competition_deadline.py`

Handles all deadline logic:

```python
from allora_forge_builder_kit.competition_deadline import (
    should_exit_loop(),         # Check if next cycle exceeds deadline
    get_deadline_info(),        # Get deadline data
    is_deadline_exceeded(),     # Check if deadline passed
    log_deadline_status(),      # Display status
)
```

### Updated: `competition_submission.py`

Main loop now:
1. Checks deadline before each cycle
2. Logs remaining time
3. Exits gracefully when appropriate

```python
# Before cycle
should_exit, reason = should_exit_loop(cadence_hours=1.0)
if should_exit:
    logger.info(reason)
    return 0  # Exit
```

---

## Competition Window

| Metric | Value |
|--------|-------|
| Start | Sep 16, 2025, 13:00 UTC |
| End | Dec 15, 2025, 13:00 UTC |
| Duration | ~90 days |
| Submission Cadence | 1 hour (configurable) |
| Topic ID | 67 (BTC/USD 7-day log-return) |

---

## Troubleshooting

### Pipeline Not Stopping at Deadline

**Check system clock:**
```bash
date -u
```

**Check deadline logic:**
```bash
python -c "
from allora_forge_builder_kit.competition_deadline import is_deadline_exceeded
print('Deadline exceeded:', is_deadline_exceeded())
"
```

### Verify Module Works

```bash
python -c "
from allora_forge_builder_kit.competition_deadline import validate_deadline_configuration
validate_deadline_configuration()
print('✅ Deadline module OK')
"
```

### Exit Codes

- `0` = Success (cycle completed OR deadline reached)
- `1` = Environment/initialization error
- `2` = Network/timeout error
- `3` = Wallet not whitelisted

---

## Test Before Production

```bash
# Test single cycle
python competition_submission.py --once

# Check it succeeds
echo $?  # Should print 0
```

---

## Files Changed

- ✅ Created: `allora_forge_builder_kit/competition_deadline.py`
- ✅ Updated: `competition_submission.py` (deadline checking)
- ✅ Created: `COMPETITION_DEADLINE_GUIDE.md` (full docs)
- ✅ Created: `COMPETITION_DEADLINE_QUICK_REF.md` (this file)

---

## Next Steps

1. **Start pipeline:**
   ```bash
   python competition_submission.py
   ```

2. **Monitor:**
   ```bash
   tail -f competition_submissions.log
   ```

3. **Verify deadline control works:**
   - Check logs show "Time remaining" counter
   - Confirm graceful exit at deadline (no manual kill needed)

4. **Optional: Deploy to production**
   - Use nohup, systemd, or Docker
   - Set and forget for ~90 days
   - Pipeline auto-stops at deadline

---

## Support

**Full documentation:**  
→ `COMPETITION_DEADLINE_GUIDE.md`

**Deadline module source:**  
→ `allora_forge_builder_kit/competition_deadline.py`

**Quick test:**  
```bash
python -c "from allora_forge_builder_kit.competition_deadline import log_deadline_status; log_deadline_status()"
```

---

🚀 **Ready to run for 90 days until competition deadline!**
