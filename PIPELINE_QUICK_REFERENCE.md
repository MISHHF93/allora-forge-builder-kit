# 🚀 Pipeline Quick Reference

## Current Status
- **Daemon PID**: 23375
- **Status**: ✅ RUNNING
- **Mode**: Continuous daemon mode
- **Schedule**: Hourly submissions at XX:00:00 UTC
- **Competition End**: Dec 15, 2025 at 1:00 PM UTC

## Key Monitoring Commands

### Real-Time Monitoring Dashboard
```bash
/workspaces/allora-forge-builder-kit/monitor_pipeline.sh
```
Updates every 10 seconds with daemon status, stats, and latest activity.

### Watch Live Logs
```bash
tail -f /workspaces/allora-forge-builder-kit/logs/submission.log
```
See all submissions as they happen.

### Check Daemon Status
```bash
ps aux | grep submit_prediction | grep -v grep
```
Verify daemon is running and check process metrics.

### View Submission CSV
```bash
tail -20 /workspaces/allora-forge-builder-kit/submission_log.csv
```
See recent submissions and their status.

### Check Next Submission Time
```bash
grep 'Sleeping' /workspaces/allora-forge-builder-kit/logs/submission.log | tail -1
```
See when the next submission cycle will run.

## Restart Daemon

If you need to restart:
```bash
pkill -9 -f "submit_prediction.py"
sleep 2
cd /workspaces/allora-forge-builder-kit
nohup python3 submit_prediction.py --daemon --model model.pkl --features features.json > /dev/null 2>&1 &
echo $! > pipeline.pid
```

## Test Pipeline (Without Waiting)

Run a single submission cycle:
```bash
cd /workspaces/allora-forge-builder-kit
python3 submit_prediction.py --once --model model.pkl --features features.json
```

Run a dry-run (no actual submission):
```bash
cd /workspaces/allora-forge-builder-kit
python3 submit_prediction.py --dry-run --model model.pkl --features features.json
```

## System Architecture

```
📊 Data Source (Tiingo API)
   ↓
🔄 Feature Engineering (13 indicators)
   ↓
🤖 XGBoost Model (prediction)
   ↓
⛓️  Blockchain (Allora network)
   ├─ RPC Failover (3 endpoints)
   ├─ Nonce Query
   └─ Submission
   ↓
📝 CSV Logging (all attempts)
   ↓
📋 Monitoring (real-time logs)
```

## Current Performance

- **Total Attempts**: 42
- **Successful**: 5 (11.9%)
- **Skipped (no nonce)**: 31 (73.8%)
- **Failed**: 4 (9.5%)

## Competition Details

- **Topic**: BTC/USD 7-day log-return prediction
- **Topic ID**: 67
- **Prediction Frequency**: Every hour
- **Period**: Sep 16, 2025 (1:00 PM) → Dec 15, 2025 (1:00 PM)
- **Remaining**: ~21 days

## Important Files

- `submit_prediction.py` - Main daemon script
- `model.pkl` - XGBoost model (740.5 KB)
- `features.json` - Feature column definitions
- `logs/submission.log` - Live activity log
- `submission_log.csv` - CSV record of all submissions
- `pipeline.pid` - Current daemon PID
- `latest_submission.json` - Latest submission details

## Troubleshooting

### Daemon not running?
```bash
cat /workspaces/allora-forge-builder-kit/pipeline.pid
ps -p <PID>
```

### Check for errors:
```bash
tail -50 /workspaces/allora-forge-builder-kit/logs/submission.log | grep -i error
```

### View latest submission:
```bash
cat /workspaces/allora-forge-builder-kit/latest_submission.json
```

## Notes

- Submissions happen at precise hourly UTC boundaries (04:00, 05:00, etc.)
- If no nonce is available, submission is skipped (normal behavior)
- RPC failover handles endpoint failures automatically
- CSV logs all attempts for analysis
- Daemon continues until exactly Dec 15, 2025 at 1:00 PM UTC

---
**Last Updated**: Nov 24, 2025 - 03:42 UTC
