# Script Consolidation Summary

**Date**: November 16, 2025  
**Purpose**: Streamline operations by consolidating utility scripts into `train.py`

## Overview

All utility functions from `tools/` directory have been integrated into `train.py` as standalone commands. This eliminates the need to run multiple scripts and provides a unified interface for all operations.

## Consolidated Functions

### 1. Score/Reward Refresh (from `tools/refresh_scores.py`)

**Old Command**:
```bash
python3 tools/refresh_scores.py --csv submission_log.csv --rest https://allora-testnet-api.lavenderfive.com --tail 20
```

**New Command**:
```bash
python3 train.py --refresh-scores --refresh-tail 20
```

**What it does**:
- Queries blockchain REST API for transaction logs
- Extracts EMA scores and ALLO rewards from on-chain events
- Updates `submission_log.csv` with score/reward data
- Falls back to `allorad` CLI for EMA queries if needed
- Automatically runs after successful submissions

**Implementation**:
- `_http_get_json()`: HTTP GET with urllib
- `_parse_reward_from_events()`: Extract ALLO amounts from transfer events
- `_parse_score_from_events()`: Extract EMA scores from blockchain events
- `_fetch_tx_logs()`: Query Cosmos SDK REST API for tx details
- `_is_nullish()`: Check for null/NaN/empty values
- `_post_submit_backfill()`: Main refresh logic (now embedded in train.py)

### 2. Wallet Address Display (from `tools/print_wallet_address.py`)

**Old Command**:
```bash
python3 tools/print_wallet_address.py
```

**New Command**:
```bash
python3 train.py --print-wallet
```

**What it does**:
- Initializes Allora SDK worker
- Resolves wallet address from SDK
- Checks for mismatches with `ALLORA_WALLET_ADDR` env var
- Displays current wallet balance

**Example Output**:
```
Resolved SDK wallet address: allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
```

### 3. Submission Log Inspector (from `tools/inspect_submission_log.py`)

**Old Command**:
```bash
python3 tools/inspect_submission_log.py submission_log.csv --tail 3
```

**New Command**:
```bash
python3 train.py --inspect-log --inspect-tail 3
```

**What it does**:
- Validates CSV schema (12-column canonical header)
- Shows column names and count
- Displays last N rows
- Identifies schema mismatches (missing/extra columns)

**Example Output**:
```
CSV exists: True -> /workspaces/allora-forge-builder-kit/submission_log.csv
Columns (count=12):
['timestamp_utc', 'topic_id', 'value', 'wallet', 'nonce', 'tx_hash', 'success', 'exit_code', 'status', 'log10_loss', 'score', 'reward']
Schema: PASS (exact 12-column canonical header)

Last 2 rows:
2025-11-16T00:00:00Z, 67, -0.054082192481, allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma, 6534235, null, false, 0, epoch_already_submitted, 0, 0, 0
2025-11-16T03:00:00Z, 67, -0.054082192481, allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma, 6536395, 46BE0CB668A745CA2610BFC04446D62D2287BC131F6879DBD662DAD87D2EBB13, true, 0, submitted, -1.303405, 0, 0
```

## New train.py Command Reference

### Training & Submission
```bash
# Single run with submission
python3 train.py --submit --force-submit

# Continuous loop (1h cadence)
python3 train.py --loop --submit --force-submit

# Custom cadence
python3 train.py --loop --submit --cadence 30m
```

### Utility Commands
```bash
# Refresh scores/rewards for last 20 submissions
python3 train.py --refresh-scores --refresh-tail 20

# Show wallet address
python3 train.py --print-wallet

# Inspect submission log
python3 train.py --inspect-log --inspect-tail 5
```

### All Available Flags
```
--from-month FROM_MONTH       Data start month (default: 2025-01)
--schedule-mode MODE          Schedule mode (single, loop, etc.)
--cadence CADENCE             Cadence for scheduling (e.g., 1h, 30m)
--start-utc START_UTC         Start datetime in UTC (ISO format)
--end-utc END_UTC             End datetime in UTC (ISO format)
--as-of AS_OF                 As-of datetime in UTC (ISO format)
--as-of-now                   Use current UTC time as as_of
--submit                      Submit the prediction after training
--submit-timeout TIMEOUT      Timeout for submission in seconds (default: 30)
--submit-retries RETRIES      Number of retries for submission (default: 3)
--force-submit                Force submission even if guards are active
--loop                        Continuously run training/submission cycles
--once                        Run exactly one iteration even if config requests loop
--timeout TIMEOUT             Loop runtime limit in seconds (0 = indefinite)
--refresh-scores              Refresh score/reward data from blockchain
--refresh-tail N              Number of recent rows to refresh (default: 20)
--print-wallet                Print wallet address from SDK and exit
--inspect-log                 Inspect submission_log.csv schema and recent entries
--inspect-tail N              Number of recent rows to show (default: 3)
```

## Benefits

### ✅ Unified Interface
- All operations accessible through single `train.py` script
- Consistent command-line interface
- Reduced cognitive overhead

### ✅ Automatic Integration
- Score refresh runs automatically after submissions
- No need to manually run separate scripts
- Better workflow integration

### ✅ Simplified Deployment
- Fewer scripts to track and deploy
- Easier to maintain on EC2/remote instances
- Single source of truth for all operations

### ✅ Better Error Handling
- Consolidated exception handling
- Consistent logging approach
- Shared configuration and environment variables

## Migration Guide

### For Existing Workflows

**Old Workflow**:
```bash
# Train and submit
python3 train.py --submit --force-submit

# Wait 24-48 hours, then refresh scores
python3 tools/refresh_scores.py --csv submission_log.csv --tail 20

# Check wallet
python3 tools/print_wallet_address.py

# Inspect log
python3 tools/inspect_submission_log.py
```

**New Workflow**:
```bash
# Train and submit (automatically refreshes scores)
python3 train.py --submit --force-submit

# Manual refresh if needed (after 24-48 hours)
python3 train.py --refresh-scores --refresh-tail 20

# Check wallet
python3 train.py --print-wallet

# Inspect log
python3 train.py --inspect-log --inspect-tail 3
```

### For EC2 Deployment

**Update command**:
```bash
cd ~/allora-forge-builder-kit
git pull origin main

# Test new commands
python3 train.py --print-wallet
python3 train.py --inspect-log

# Start continuous operation
nohup python3 train.py --loop --submit --force-submit --submit-timeout 300 > pipeline.log 2>&1 &
```

## Files Status

### ✅ Consolidated (functionality now in train.py)
- `tools/refresh_scores.py` - 329 lines → integrated
- `tools/print_wallet_address.py` - 48 lines → integrated  
- `tools/inspect_submission_log.py` - 84 lines → integrated

### 📦 Still Standalone (specialized use)
- `tools/normalize_submission_log.py` - Schema normalization (imported by train.py)
- `tools/validate_submission_log.py` - Deep validation checks
- `tools/scrub_wallets.py` - Wallet cleanup utility
- `tools/sign_worker_bundle/` - Bundle signing (Go-based)

### 🚀 Enhanced Core
- `train.py` - Now 4,705 lines (previously 4,484)
  - Added 221 lines of consolidated utility functions
  - 3 new CLI flags: `--refresh-scores`, `--print-wallet`, `--inspect-log`
  - All existing functionality preserved

## Technical Details

### REST API Integration
- Base URL: `https://allora-testnet-api.lavenderfive.com`
- Endpoint: `/cosmos/tx/v1beta1/txs/{tx_hash}`
- Parses transaction logs for EMA scores and reward amounts
- Handles both uallo (micro) and ALLO denominations

### CLI Fallback
- Uses `allorad q emissions inferer-score-ema <topic> <wallet>` for EMA scores
- JSON parsing with recursive value extraction
- Regex fallback for non-JSON responses

### CSV Schema Validation
- 12-column canonical header enforced
- Columns: `timestamp_utc`, `topic_id`, `value`, `wallet`, `nonce`, `tx_hash`, `success`, `exit_code`, `status`, `log10_loss`, `score`, `reward`
- Automatic schema normalization via `allora_forge_builder_kit.submission_log`

## Testing Results

### ✅ All Tests Passed
```bash
# Refresh scores test
python3 train.py --refresh-scores --refresh-tail 10
# Result: [refresh_scores] No updates found; CSV unchanged.

# Print wallet test  
python3 train.py --print-wallet
# Result: Resolved SDK wallet address: allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma

# Inspect log test
python3 train.py --inspect-log --inspect-tail 2
# Result: Schema: PASS (exact 12-column canonical header)
```

## Next Steps

1. **Update EC2 instances**: `git pull origin main` to get consolidated code
2. **Update documentation**: Reflect new commands in README.md and other docs
3. **Monitor automatic refresh**: Verify score/reward backfill after submissions
4. **Deprecate old scripts**: Consider archiving `tools/*.py` after transition period

## Compatibility Notes

- **Backward Compatible**: All existing `train.py` commands still work
- **Environment Variables**: Same `.env` requirements (ALLORA_API_KEY, etc.)
- **Dependencies**: No new packages required (uses urllib, built-in csv module)
- **Python Version**: Tested on Python 3.12 (compatible with 3.8+)

---

**Summary**: `train.py` is now your one-stop command for all operations - training, submission, score refresh, wallet checks, and log inspection. The tools/ directory utilities are preserved but no longer needed for routine operations.
