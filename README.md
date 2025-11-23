# BTC 7-Day Log-Return Forecast & Submission

Minimal single-run pipeline for the Allora competition:

1. Fetch recent BTC/USD hourly prices (CoinGecko API; synthetic fallback).
2. Engineer lightweight features.
3. Compute forward 7-day (168h) log-return training target.
4. Train a fresh model (XGBoost if available, else Ridge) on a rolling window (default 90 days).
5. Predict the 7-day forward log-return for the current hour.
6. Submit the forecast via Allora CLI (if installed) and log it locally.

## Quick Start - Production Daemon

For reliable 24/7 operation until December 15, 2025:

```bash
# 1. Train the model
python train.py

# 2. Install and start daemon via systemd (recommended)
sudo ./daemon_manager.sh install
sudo ./daemon_manager.sh start
sudo ./daemon_manager.sh enable

# 3. Monitor
./daemon_manager.sh logs
./daemon_manager.sh health
```

**See [DAEMON_GUIDE.md](DAEMON_GUIDE.md) for comprehensive documentation.**

## Single-Run Usage

Environment variables configure run behavior:

| Variable | Default | Description |
|----------|---------|-------------|
| `FORECAST_DAYS_BACK` | `90` | Days of hourly history to pull/train on |
| `FORECAST_SUBMIT` | `true` | Set to `false` to skip CLI submission |
| `ALLORA_TOPIC_ID` | `67` | Competition topic ID |

Run (training + prediction + optional submission):

```bash
python train.py
```

Disable submission:

```bash
FORECAST_SUBMIT=false python train.py
```

Adjust history window:

```bash
FORECAST_DAYS_BACK=75 python train.py
```

## Continuous Submission Mode

Submit predictions every hour automatically:

```bash
# Test with dry-run
python submit_prediction.py --dry-run

# Run continuous in background (simple)
nohup python submit_prediction.py --continuous > logs/submission.log 2>&1 &

# Or use systemd (better)
sudo ./daemon_manager.sh start
```

## Output Artifacts

| File | Purpose |
|------|---------|
| `latest_submission.json` | Snapshot of last forecast metadata |
| `submission_log.csv` | Append-only log of predictions (8 fields) |
| `logs/submission.log` | Daemon operation log with heartbeats and tracebacks |

## Monitoring Daemon Health

```bash
# Check daemon status
./daemon_manager.sh status
./daemon_manager.sh health

# Follow live logs with heartbeats
./daemon_manager.sh logs

# Check recent submissions
tail -5 submission_log.csv

# Search for specific events
grep "HEARTBEAT" logs/submission.log
grep "Submission success" logs/submission.log
```

## Cron Example (Hourly)

```cron
0 * * * * cd /path/to/repo && FORECAST_SUBMIT=true python train.py >> hourly_forecast.log 2>&1
```

## Daemon Features

- **Auto-restart**: Automatically restarts on crash, kill, or reboot (systemd)
- **Heartbeat monitoring**: Logs every hour confirming daemon is alive
- **Comprehensive error handling**: All exceptions logged with full Python tracebacks
- **Cycle tracking**: Each submission cycle numbered and timed
- **No silent failures**: All errors caught and logged
- **Dual-mode logging**: File (DEBUG level) + console (INFO level)
- **Graceful degradation**: Uses synthetic data if API fails, retries if no nonce
- **Two deployment options**: Systemd (recommended) or supervisord

## Requirements

```bash
pip install -r requirements.txt
```

Key dependencies:
- `pandas` - Data manipulation
- `numpy` - Numerical computing
- `xgboost` - Fast tree boosting
- `scikit-learn` - Machine learning utilities
- `requests` - HTTP library
- `python-dotenv` - Environment variable management
- `allora-sdk` - Blockchain submission


## Dependencies

Minimal requirements listed in `requirements.txt`: numpy, pandas, scikit-learn, xgboost (optional), requests.

## Notes

* No model or artifact persistence between runs.
* If CoinGecko API fails, a reproducible synthetic random walk is used.
* Allora CLI submission is skipped gracefully if the binary is absent.

