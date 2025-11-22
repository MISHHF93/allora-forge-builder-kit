# BTC 7-Day Log-Return Forecast & Submission

Minimal single-run pipeline for the Allora competition:

1. Fetch recent BTC/USD hourly prices (CoinGecko API; synthetic fallback).
2. Engineer lightweight features.
3. Compute forward 7-day (168h) log-return training target.
4. Train a fresh model (XGBoost if available, else Ridge) on a rolling window (default 90 days).
5. Predict the 7-day forward log-return for the current hour.
6. Submit the forecast via Allora CLI (if installed) and log it locally.

## Usage

Environment variables configure run behavior:

| Variable | Default | Description |
|----------|---------|-------------|
| `FORECAST_DAYS_BACK` | `90` | Days of hourly history to pull/train on |
| `FORECAST_SUBMIT` | `true` | Set to `false` to skip CLI submission |
| `ALLORA_TOPIC_ID` | `67` | Competition topic ID |

Run (training + prediction + optional submission):

```bash
python btc_7d_log_return_forecast.py
```

Disable submission:

```bash
FORECAST_SUBMIT=false python btc_7d_log_return_forecast.py
```

Adjust history window:

```bash
FORECAST_DAYS_BACK=75 python btc_7d_log_return_forecast.py
```

## Output Artifacts

| File | Purpose |
|------|---------|
| `latest_submission.json` | Snapshot of last forecast metadata |
| `submission_log.csv` | Append-only log of predictions |

## Cron Example (Hourly)

```cron
0 * * * * cd /path/to/repo && FORECAST_SUBMIT=true python btc_7d_log_return_forecast.py >> hourly_forecast.log 2>&1
```

## Dependencies

Minimal requirements listed in `requirements.txt`: numpy, pandas, scikit-learn, xgboost (optional), requests.

## Notes

* No model or artifact persistence between runs.
* If CoinGecko API fails, a reproducible synthetic random walk is used.
* Allora CLI submission is skipped gracefully if the binary is absent.

