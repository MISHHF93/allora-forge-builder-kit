# Allora Forge Production Worker Guide

## Overview

The production worker (`run_worker.py`) is a continuous, event-driven submission agent that integrates directly with the Allora network to provide predictions for Topic 67 (BTC/USD 7-day log-return) during the competition period (Sep 16 - Dec 15, 2025).

Unlike batch pipelines that try to force submissions, this worker **responds to network events** - it listens for submission window openings and provides predictions when requested by the blockchain.

## How It Works

### Event-Driven Architecture

```
1. Worker starts → Connects to Allora RPC + WebSocket
2. Subscribes to submission window events
3. Waits for EventWorkerSubmissionWindowOpened
4. Network opens window → Worker receives nonce
5. Worker calls get_prediction(nonce)
6. Trains model or uses cached prediction
7. Submits prediction to blockchain
8. Returns to waiting state
```

### Key Features

- ✅ **Network-synchronized**: Responds to real submission windows, no forced attempts
- ✅ **Singleton enforcement**: Only one worker instance per topic
- ✅ **Intelligent caching**: Reuses predictions less than 1 hour old
- ✅ **Adaptive training**: Works with available data (14-28 days)
- ✅ **Graceful degradation**: Falls back to 0.0 if training fails
- ✅ **Comprehensive logging**: Event log + stdout log
- ✅ **Competition-aware**: Automatically starts/stops within competition window

## Quick Start

### Start the Worker

```bash
# Production mode (recommended)
./start_worker.sh

# Debug mode (verbose logging)
./start_worker.sh --debug
```

### Monitor the Worker

```bash
# Real-time output
tail -f data/artifacts/logs/worker_output.log

# Event log (JSON format)
tail -f data/artifacts/logs/worker_continuous.log

# Check if running
ps aux | grep run_worker.py
```

### Stop the Worker

```bash
./stop_worker.sh
```

## Configuration

### Environment Variables (`.env`)

```bash
MNEMONIC=your wallet mnemonic here
TIINGO_API_KEY=your tiingo api key
ALLORA_WALLET_ADDR=allo1...  # (optional, derived from mnemonic)
TOPIC_ID=67                   # (optional, defaults to 67)
```

### Worker Parameters

Edit `run_worker.py` to adjust:

```python
TOPIC_ID = 67                    # Competition topic
TICKER = "btcusd"                # Market data ticker
TARGET_HOURS = 168               # 7-day prediction horizon
TRAIN_SPAN_HOURS = 336           # 14 days of training data
VALIDATION_SPAN_HOURS = 168      # 7 days of validation
POLLING_INTERVAL = 120           # Seconds between network checks
```

## Operational Modes

### Normal Operation

```
🚀 [timestamp] Starting Allora Worker
✅ [timestamp] Environment loaded successfully
✅ [timestamp] Singleton guard passed
✅ [timestamp] Competition is active
✅ [timestamp] Worker initialized
ℹ️ [timestamp] Starting worker polling loop...
🔔 [timestamp] Submission window opened (nonce=XXXXXX)
🎯 [timestamp] Model trained and prediction generated
📤 [timestamp] Prediction submitted
```

### Before Competition Starts

Worker detects the start time and waits:
```
ℹ️ [timestamp] Competition starts in X hours
ℹ️ [timestamp] Worker will start when competition begins
```

### After Competition Ends

Worker detects the end and shuts down gracefully:
```
ℹ️ [timestamp] Competition ended - shutting down
🛑 [timestamp] Worker stopped gracefully
```

### Error Handling

If prediction fails, worker logs error but continues:
```
❌ [timestamp] Prediction function failed: Insufficient data
   (Worker submits fallback value 0.0 and continues operating)
```

## Prediction Logic

### Primary Path: Cached Prediction

```python
if model_exists and prediction_age < 1 hour:
    return cached_prediction
```

### Secondary Path: Fresh Training

```python
1. Fetch market data (Tiingo API)
2. Calculate log returns
3. Engineer features (lags, moving averages, volatility)
4. Train GradientBoostingRegressor
5. Validate on holdout set
6. Save model + prediction
7. Return prediction value
```

### Fallback Path: Error Recovery

```python
if training_fails:
    log_error()
    return 0.0  # No expected change
```

## Monitoring & Debugging

### Event Log Format

Each line in `worker_continuous.log` is a JSON object:

```json
{
  "timestamp": "2025-11-07T01:36:20.316588Z",
  "event": "window_open",
  "message": "Submission window opened (nonce=6392395)",
  "data": {}
}
```

Event types:
- `startup`: Worker initialization
- `window_open`: Submission window detected
- `prediction`: Model training complete
- `submission`: Blockchain submission
- `success`: Operation succeeded
- `error`: Operation failed
- `warning`: Non-critical issue
- `info`: General information
- `shutdown`: Worker stopping

### Common Issues

#### "Another worker instance is already running"

```bash
# Check for running workers
ps aux | grep run_worker.py

# Stop existing worker
./stop_worker.sh

# Or manually
pkill -f "python.*run_worker.py"
```

#### "Insufficient data" errors

- The worker needs at least 14 days of market data
- For new competitions, wait until sufficient history accumulates
- Fallback prediction (0.0) is automatically used

#### "0 unfulfilled nonces" (normal)

This means no submission window is currently open. The worker is correctly waiting for the network to open a window.

#### Transaction timeouts

The worker automatically retries failed transactions. Check blockchain status if persistent.

## Production Deployment

### System Requirements

- Python 3.10+
- 512MB RAM minimum
- Stable internet connection
- Linux/macOS (tested on Ubuntu 24.04)

### Dependencies

```bash
pip install -r requirements.txt
```

Key packages:
- `allora-sdk` - Blockchain integration
- `scikit-learn` - Model training
- `pandas`, `numpy` - Data processing
- `psutil` - Process management
- `requests` - API calls

### Running as Service (systemd)

Create `/etc/systemd/system/allora-worker.service`:

```ini
[Unit]
Description=Allora Topic 67 Worker
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/allora-forge-builder-kit
ExecStart=/usr/bin/python3 /path/to/allora-forge-builder-kit/run_worker.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable allora-worker
sudo systemctl start allora-worker
sudo systemctl status allora-worker
```

### Monitoring in Production

```bash
# Watch logs in real-time
tail -f data/artifacts/logs/worker_output.log | grep -E "✅|❌|🔔"

# Check submission count
grep "Submission window opened" data/artifacts/logs/worker_continuous.log | wc -l

# Last 10 submissions
grep "submission" data/artifacts/logs/worker_continuous.log | tail -10

# Error summary
grep "error" data/artifacts/logs/worker_continuous.log | jq -r '.message'
```

## Performance Expectations

### Normal Operation

- **CPU**: 1-5% idle, 20-40% during training
- **Memory**: 100-200MB baseline, 300-500MB during training
- **Network**: Minimal (WebSocket keepalives + periodic polling)
- **Disk**: <1MB/day logs

### Submission Timing

- **Window detection**: <1 second after blockchain event
- **Training time**: 3-10 seconds (depending on data size)
- **Submission time**: 2-5 seconds (blockchain confirmation)
- **Total latency**: <15 seconds from window open to submission

## Differences from Batch Pipeline

| Feature | Batch Pipeline (`run_pipeline.py`) | Production Worker (`run_worker.py`) |
|---------|-------------------------------------|-------------------------------------|
| Triggering | Manual/cron schedule | Network events |
| Submission attempts | Forces submissions | Only when window opens |
| Window awareness | Estimates submission windows | Directly observes blockchain events |
| Error handling | Retries with backoff | Logs and continues |
| Resource usage | Periodic spikes | Constant low baseline |
| Use case | Backfilling, testing | Production operation |

## Security Considerations

1. **Private Key Protection**: The mnemonic in `.env` controls funds - never commit to git
2. **API Key Limits**: Tiingo has rate limits - worker handles this gracefully
3. **Network Access**: Worker needs outbound HTTPS (443) and WebSocket access
4. **Process Isolation**: Singleton guard prevents conflicts

## Troubleshooting

### Worker won't start

1. Check environment: `cat .env | grep MNEMONIC`
2. Verify dependencies: `python3 -c "import allora_sdk; print('OK')"`
3. Check for conflicts: `ps aux | grep run_worker`
4. Review startup logs: `python3 run_worker.py --debug`

### No submissions happening

1. Check competition window (Sep 16 - Dec 15, 2025)
2. Verify network connection: `ping allora-rpc.testnet.allora.network`
3. Check WebSocket: Look for "Websocket connected" in logs
4. Monitor for window events: `grep "window_open" data/artifacts/logs/worker_continuous.log`

### Predictions are always 0.0

1. Check market data availability: `python3 -c "import requests; print(requests.get(...).json())"`
2. Verify sufficient history: Need 14+ days of data
3. Check training logs for errors
4. Try manual training: `python3 train.py`

## Advanced Usage

### Custom Prediction Function

Edit the `get_prediction()` function in `run_worker.py`:

```python
def get_prediction(nonce: int) -> float:
    # Your custom logic here
    # Must return a float prediction
    return your_prediction_value
```

### Adjust Polling Interval

```bash
# Faster polling (60 seconds)
python3 run_worker.py --polling 60

# Slower polling (300 seconds)
python3 run_worker.py --polling 300
```

### Integration with Monitoring Tools

```bash
# Prometheus metrics export
grep -E "prediction|submission" data/artifacts/logs/worker_continuous.log | \
    jq -r '"\(.timestamp) \(.event) \(.data.prediction // 0)"'

# Grafana dashboard: Parse JSON logs and visualize predictions, submission rate, errors
```

## FAQ

**Q: How often does the worker check for submission windows?**
A: Every 120 seconds by default, but it's also notified immediately via WebSocket when windows open.

**Q: What happens if my internet connection drops?**
A: The worker will attempt to reconnect and resume operation. Missed windows cannot be recovered.

**Q: Can I run multiple workers for different topics?**
A: Yes, but modify `TOPIC_ID` in each worker and ensure they use different wallets.

**Q: How much does it cost to run?**
A: Transaction fees are ~0.0001 ALLO per submission. Competition has ~2000 hourly windows = ~0.2 ALLO total.

**Q: Will the worker drain my wallet?**
A: No. Each submission costs minimal gas. The worker stops if competition ends or balance is insufficient.

## Support

For issues, check:
1. This documentation
2. Worker event logs (`worker_continuous.log`)
3. Allora SDK documentation
4. Competition rules at allora.network

---

**Ready to run?**

```bash
./start_worker.sh
tail -f data/artifacts/logs/worker_output.log
```

Good luck in the competition! 🚀
