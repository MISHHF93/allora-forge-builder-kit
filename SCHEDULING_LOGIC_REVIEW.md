# Scheduling Logic Review - Topic 67 Pipeline

## Executive Summary

**Status**: ✅ **NO NESTED LOOPING** - Scheduling logic is correct and working as intended.

**Issue**: User concern about potential nested or redundant looping when using `--loop` flag.

**Finding**: After thorough code review, no nested looping exists. The architecture cleanly separates single-shot and continuous modes with proper cadence alignment.

**Action Taken**: Enhanced visibility with startup banners and iteration tracking to make execution mode crystal clear.

---

## Code Architecture Review

### Main Entry Point (`main()` function)

Located at lines 4671-4893 in `train.py`, the main function follows this clean flow:

```
main()
├── Parse arguments (--loop, --once, --submit, etc.)
├── Determine effective_mode
│   ├── If --once: effective_mode = "once"
│   └── If --loop OR config mode=="loop": effective_mode = "loop"
├── Set effective_cadence (1h for loop, configurable for others)
└── Execute based on mode
    ├── If NOT loop: _run_once() → EXIT IMMEDIATELY
    └── If loop: _sleep_until_next_window() once → while True loop
```

### Key Functions

#### 1. `_run_once()` - Single Pipeline Execution
```python
def _run_once() -> int:
    return run_pipeline(args, cfg, root_dir)
```
- Wraps the entire pipeline (train → predict → submit)
- Called exactly ONCE per iteration
- Returns exit code (0=success, non-zero=error)
- No internal looping

#### 2. `_sleep_until_next_window()` - Cadence Alignment
Located at lines 3246-3286:
```python
def _sleep_until_next_window(cadence_s: float):
    now_utc = pd.Timestamp.now(tz="UTC")
    window_start = _window_start_utc(now=now_utc, cadence_s=cadence_s)
    next_window = window_start + pd.Timedelta(seconds=cadence_s)
    sleep_seconds = max(0.0, (next_window - now_utc).total_seconds())
    # ... sleep logic ...
```
- Called exactly ONCE before entering the while True loop
- Aligns to the next cadence boundary (e.g., next hour mark)
- Does NOT recurse or create nested loops

#### 3. Loop Logic (lines 4827-4890)
```python
# Initial alignment: sleep until next cadence boundary before first iteration
_sleep_until_next_window(cadence_s)

last_rc = 0
while True:
    if loop_timeout and (time.time() - start_wall) >= loop_timeout:
        return last_rc
    
    iteration += 1
    # Execute pipeline
    try:
        rc = _run_once()  # ← Single call per iteration, no nesting
        last_rc = rc
    except Exception as e:
        # Handle error, continue to next cycle
        ...
    
    # Calculate sleep time to next window
    next_window = _window_start_utc(...) + cadence_s
    sleep_seconds = (next_window - now_utc).total_seconds()
    time.sleep(sleep_seconds)
```

**Structure**:
- Single `while True` loop
- One `_run_once()` call per iteration
- Exception handling prevents crashes
- Sleep alignment between iterations
- No recursion, no nested loops

---

## Execution Modes

### Mode 1: Single-Shot (`--once`)
```bash
python train.py --once --submit
```

**Behavior**:
1. Print startup banner showing "Single iteration (--once mode)"
2. Call `_run_once()` exactly once
3. EXIT immediately (return code from pipeline)
4. No looping, no sleeping

**Use Case**: Manual runs, debugging, cron jobs

### Mode 2: Continuous Loop (`--loop`)
```bash
python train.py --loop --submit
```

**Behavior**:
1. Print startup banner showing "Continuous loop (--loop mode)"
2. Show next cycle time and timeout info
3. Call `_sleep_until_next_window()` once to align
4. Enter `while True` loop:
   - Increment iteration counter
   - Print iteration banner with timestamp
   - Call `_run_once()` (single pipeline execution)
   - Print success/error status with duration
   - Calculate sleep time to next window
   - Print sleep message with time in minutes
   - Sleep until next cycle
5. Handle KeyboardInterrupt gracefully
6. Continue indefinitely or until timeout

**Use Case**: Production hourly submissions

---

## Improvements Made (Commit ae2ead3)

### 1. Startup Banner
```
================================================================================
ALLORA PIPELINE - Topic 67 (7-Day BTC/USD Log-Return Prediction)
================================================================================
Start Time:    2025-11-17 02:30:15 UTC
Mode:          LOOP
Cadence:       1h (3600 seconds)
Submit:        YES
Force Submit:  NO
Execution:     Continuous loop (--loop mode)
Next Cycle:    2025-11-17 03:00:00 UTC
Timeout:       None (runs indefinitely)
================================================================================
```

**Benefits**:
- Immediately clear which mode is active
- Shows next expected cycle time
- Displays submit flags status
- No ambiguity about loop behavior

### 2. Iteration Tracking
```
================================================================================
LOOP ITERATION 1 - 2025-11-17 03:00:00 UTC
================================================================================

[pipeline execution output...]

✅ Iteration 1 completed (rc=0, duration=42.3s)

💤 Sleeping 57.7 minutes until next cycle at 04:00:00 UTC...
```

**Benefits**:
- Clear iteration boundaries
- Success/error status with emoji indicators (✅❌💤🛑)
- Duration tracking for each cycle
- Sleep time displayed in minutes (more readable than seconds)
- Graceful KeyboardInterrupt handling with 🛑 indicator

### 3. Error Resilience
```python
except Exception as e:
    error_msg = f"[loop] iteration={iteration} failed with exception: {type(e).__name__}: {e}"
    logging.error(error_msg)
    print(f"\n❌ ERROR in iteration {iteration}: {type(e).__name__}: {e}", file=sys.stderr)
    rc = 1
    last_rc = rc
    logging.info(f"[loop] iteration={iteration} error handled, continuing to next cycle")
    print(f"⚠️  Error handled. Will retry in next cycle.")
```

**Benefits**:
- Pipeline errors don't crash the loop
- Clear error messages with emoji indicators
- Automatic retry in next cycle
- Maintains continuous operation during API failures or validation errors

---

## Verification Checklist

✅ **No nested looping**: Single `while True` with one `_run_once()` per iteration  
✅ **No duplicate execution**: `_sleep_until_next_window()` called once before loop  
✅ **Clean mode separation**: `--once` exits immediately, `--loop` enters continuous mode  
✅ **Proper cadence alignment**: Sleep calculated to next window boundary  
✅ **Clear visibility**: Startup banner and iteration messages show mode and progress  
✅ **Error resilience**: Exceptions handled gracefully, loop continues  
✅ **Graceful shutdown**: KeyboardInterrupt handled cleanly with status message  

---

## Testing Recommendations

### Test 1: Single-Shot Mode
```bash
python train.py --once --submit
```
**Expected**: Run once, show single iteration banner, exit immediately

### Test 2: Loop Mode (Short Timeout)
```bash
python train.py --loop --submit --timeout 300
```
**Expected**: Show loop banner, run iterations until 5-minute timeout

### Test 3: Loop Mode (Production)
```bash
./start_worker.sh
```
**Expected**: 
- Clean PID management
- Clear startup banner
- Continuous hourly iterations
- Visible progress with iteration numbers
- Graceful interrupt handling

### Test 4: Live Monitoring
```bash
./watch_live.sh
```
**Expected**: Real-time dashboard showing current iteration and status

---

## Conclusion

The scheduling logic in `train.py` is **architecturally sound** with no nested looping or redundant execution. The improvements made enhance **visibility and predictability** without changing the underlying logic.

**Key Takeaway**: Running `python train.py --loop --submit` will:
1. Print clear startup banner showing LOOP mode
2. Align to next cadence boundary
3. Execute one pipeline cycle per hour
4. Display iteration progress with emoji indicators
5. Continue until interrupted or timeout

No nested loops exist. Execution is predictable and visible.

---

**Commit**: ae2ead3  
**Date**: 2025-11-17  
**Author**: GitHub Copilot  
