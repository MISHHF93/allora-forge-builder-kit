# Successful Submission Configuration

## Status: ✅ WORKING

**Last successful submission**: 2025-11-15 23:00:00 UTC
**TX Hash**: `2AFBDB28615999FF404B040ECAB26043CAC19437729715584A33FEFD1F6D405F`
**Nonce**: 6534235

## Key Configuration Changes

### 1. Increased Worker Timeout
**Problem**: Worker was timing out after 30 seconds while waiting for unfulfilled nonces.

**Solution**: Increased `--submit-timeout` from 30 to 300 seconds (5 minutes).

**Reason**: The Allora SDK worker needs time to:
- Connect to the network
- Query for unfulfilled nonces
- Wait for the blockchain to create a nonce if none exists
- Submit when a nonce becomes available

### 2. Current Running Configuration
```bash
python3 train.py --loop --submit --force-submit --submit-timeout 300
```

**Process Details**:
- **PID**: 15110
- **Started**: 2025-11-15 23:34 UTC
- **Next cycle**: 2025-11-16 00:00:00 UTC
- **Cadence**: Hourly (3600s intervals)

## How It Works

### Training Phase
1. Downloads BTC/USD OHLC data from Allora API
2. Engineers 1014 features (after deduplication)
3. Trains XGBoost model
4. Generates prediction for next 7-day log-return
5. Saves artifacts to `data/artifacts/`

### Submission Phase
1. **Client-based submission** (first attempt):
   - Builds transaction with forecast elements
   - Usually fails with `tx_hash=null` due to broadcast mode issues
   
2. **SDK worker fallback** (reliable method):
   - Initializes Allora SDK worker with wallet
   - Polls for unfulfilled nonces on Topic 67
   - When nonce found: submits inference immediately
   - Returns transaction hash on success

### Submission Window Details
From lifecycle diagnostics:
```
is_active=True
is_rewardable=False
submission_window_open=None
submission_window_confidence=False
churn_reasons=['missing_epoch_or_last_update']
unfulfilled=1
```

**Key findings**:
- Topic is **active** but not yet rewardable
- Epoch information is missing (`epoch_length: None`)
- Worker finds unfulfilled nonces despite missing epoch data
- When unfulfilled nonce exists, submission succeeds quickly (2-3 seconds)

## Troubleshooting

### If submission times out again:
1. Check if unfulfilled nonces exist:
   ```bash
   allorad q emissions topic-last-worker-commit 67 --node https://testnet-rpc.lavenderfive.com:443/allora/ --output json
   ```

2. Check topic status:
   ```bash
   allorad q emissions topic 67 --node https://testnet-rpc.lavenderfive.com:443/allora/ --output json
   ```

3. Verify wallet balance (must have > 0.000001 ALLO for gas):
   ```bash
   allorad q bank balances allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma --node https://testnet-rpc.lavenderfive.com:443/allora/
   ```

### If loop stops:
1. Check for process:
   ```bash
   ps aux | grep "train.py --loop"
   ```

2. Review error logs:
   ```bash
   tail -100 continuous_pipeline.log | grep -i error
   ```

3. Restart with:
   ```bash
   nohup python3 train.py --loop --submit --force-submit --submit-timeout 300 > continuous_pipeline.log 2>&1 &
   ```

## Monitoring Commands

### Check recent submissions:
```bash
tail -5 submission_log.csv
```

### Watch live progress:
```bash
tail -f continuous_pipeline.log
```

### Verify next cycle timing:
```bash
grep "sleeping" continuous_pipeline.log | tail -1
```

### Check submission success rate:
```bash
awk -F',' 'NR>1 {total++; if($7=="true") success++} END {printf "Success: %d/%d (%.1f%%)\n", success, total, 100*success/total}' submission_log.csv
```

## Competition Details

- **Topic ID**: 67
- **Task**: BTC/USD 7-day log-return prediction
- **Duration**: Sep 16 - Dec 15, 2025
- **Submission Cadence**: Hourly
- **Wallet**: allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma
- **Balance**: 0.251295 ALLO (sufficient for ~50,000 submissions)

## Next Steps

1. ✅ **Training & submission working** with 300s timeout
2. ⏳ **Monitor next cycle** at 00:00 UTC to confirm continuous operation
3. ⏳ **Wait for scores** - check after 24-48 hours for EMA scores to appear
4. ⏳ **Optimize model** - improve prediction accuracy to increase rewards

## Files Reference

- **Training log**: `pipeline_run.log`
- **Continuous operation log**: `continuous_pipeline.log`
- **Submission history**: `submission_log.csv`
- **Model artifacts**: `data/artifacts/model.joblib`, `predictions.json`
- **Configuration**: `config/pipeline.yaml`
