# Python-Only BTC/USD 7-Day Log-Return Pipeline

End-to-end pipeline for the Allora Labs competition, fully in Python (no shell scripts).

## Workflow
1. **Fetch**: `pipeline_core.fetch_price_history` pulls hourly BTC/USD prices (Tiingo first, fallback CoinGecko) with retry/backoff and caches under `tiingo_debug/`.
2. **Validate**: `price_coverage_ok` enforces coverage/freshness before training or submission.
3. **Train**: `train.py` uses ~90 days of hourly data to model the 7-day log-return target and saves artifacts to `artifacts/`.
4. **Submit**: `submit_prediction.py` reloads artifacts, regenerates the freshest features, validates predictions, and writes submission metadata to `logs/submission_log.csv` plus `artifacts/latest_submission.json`.

## Usage

```bash
# Train (uses cache if fresh; set FORCE_RETRAIN=1 to force)
python train.py

# Submit using latest artifacts and cached/live data
python submit_prediction.py
```

Environment toggles:

| Variable | Default | Purpose |
|---|---|---|
| `FORECAST_DAYS_BACK` | `90` (train) / `120` (submit) | Lookback window in days |
| `FORECAST_HORIZON_HOURS` | `168` | Forward horizon for log-return target |
| `FORCE_FETCH` | `0` | Force refetch of price data, bypassing cache |
| `FORCE_RETRAIN` | `0` | Ignore existing artifacts and retrain |
| `TOPIC_ID` | `67` | Competition topic ID |
| `ALLORA_WALLET_ADDR` | empty | Worker identifier logged with artifacts |

## Artifacts & Logs

- `artifacts/model.pkl` and `artifacts/features.json`: saved model + feature column order.
- `artifacts/latest_submission.json`: latest submission payload ready for CLI/SDK hand-off.
- `logs/train.log`, `logs/submit.log`: pipeline logging.
- `logs/submission_log.csv`: append-only metadata for training and predictions.
- `tiingo_debug/`: cached parquet/JSON price history and fetch chunks.

## Notes

- All former shell scripts have been archived; the Python entrypoints (`train.py`, `submit_prediction.py`) now encapsulate the full flow.
- `python -m compileall .` should succeed for syntax validation.
- Add a lightweight integration check (e.g., `test_pipeline.py`) if automated validation is required.
