import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np
import pandas as pd
import requests
from allora_sdk.rpc_client.config import AlloraNetworkConfig, AlloraWalletConfig
from allora_sdk.worker import AlloraWorker
from sklearn.ensemble import RandomForestRegressor

BINANCE_URL = "https://api.binance.com/api/v3/klines"
TOPIC_ID = 67
HORIZON_HOURS = 24 * 7
HISTORY_DAYS = 90
TRAIN_WINDOW_HOURS = HISTORY_DAYS * 24

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def fetch_btcusd_data() -> pd.DataFrame:
    """Fetch hourly BTC/USDT candles with price and volume from Binance."""
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=HISTORY_DAYS + 7)
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    frames: List[pd.DataFrame] = []
    cursor = start_ms
    while cursor < end_ms:
        params = {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }
        response = requests.get(BINANCE_URL, params=params, timeout=30)
        response.raise_for_status()
        klines = response.json()
        if not klines:
            break

        chunk = pd.DataFrame(
            klines,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )
        chunk["timestamp"] = pd.to_datetime(chunk["open_time"], unit="ms", utc=True)
        chunk = chunk[["timestamp", "close", "volume"]].astype(float)
        frames.append(chunk)

        last_close_time = int(klines[-1][6])
        cursor = last_close_time + 1

    if not frames:
        raise RuntimeError("No data received from Binance API")

    df = pd.concat(frames).drop_duplicates(subset=["timestamp"])
    df = df[df["timestamp"] <= now].sort_values("timestamp").reset_index(drop=True)
    logger.info("Fetched %s hourly rows ending at %s", len(df), df["timestamp"].max())
    return df


def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    """Align timestamps, handle gaps, and build model features."""
    aligned_index = pd.date_range(
        start=df["timestamp"].min(),
        end=df["timestamp"].max(),
        freq="1h",
        tz=timezone.utc,
    )
    frame = df.set_index("timestamp").reindex(aligned_index)
    frame["close"] = frame["close"].ffill()
    frame["volume"] = frame["volume"].fillna(0.0)

    frame["return_1h"] = frame["close"].pct_change()
    frame["log_return_1h"] = np.log(frame["close"] / frame["close"].shift(1))
    frame["ma_24h"] = frame["close"].rolling(24).mean()
    frame["ma_72h"] = frame["close"].rolling(72).mean()
    frame["volatility_24h"] = frame["log_return_1h"].rolling(24).std()
    frame["volume_ma_24h"] = frame["volume"].rolling(24).mean()
    frame["volume_ratio"] = frame["volume"] / (frame["volume_ma_24h"] + 1e-8)

    clean = frame.dropna().rename_axis("timestamp").reset_index()
    logger.info("Prepared feature frame with %s rows", len(clean))
    return clean


def add_target(feature_frame: pd.DataFrame) -> pd.DataFrame:
    """Compute 7-day forward log-return target."""
    df = feature_frame.copy()
    df["target"] = np.log(df["close"].shift(-HORIZON_HOURS) / df["close"])
    with_target = df.dropna(subset=["target"])
    logger.info("Computed targets for %s rows", len(with_target))
    return with_target


def train_model(train_df: pd.DataFrame) -> RandomForestRegressor:
    feature_cols = [c for c in train_df.columns if c not in {"timestamp", "target"}]
    X = train_df[feature_cols]
    y = train_df["target"]

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X, y)
    logger.info("Model trained on %s samples", len(train_df))
    return model


def predict_latest(model: RandomForestRegressor, feature_frame: pd.DataFrame) -> float:
    feature_cols = [c for c in feature_frame.columns if c not in {"timestamp", "target"}]
    live_row = feature_frame.iloc[[-1]][feature_cols]
    prediction = float(model.predict(live_row)[0])
    logger.info("Predicted 7-day log-return: %.6f", prediction)
    return prediction


def save_artifact(prediction: float) -> None:
    artifacts_dir = os.path.join("data", "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    payload = {
        "topic_id": TOPIC_ID,
        "value": prediction,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    artifact_path = os.path.join(artifacts_dir, "prediction.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, indent=2))
    logger.info("Saved prediction artifact to %s", artifact_path)


async def _submit_async(prediction: float) -> bool:
    api_key = os.getenv("ALLORA_API_KEY")
    if not api_key:
        logger.warning("ALLORA_API_KEY missing; skipping submission")
        return False

    try:
        wallet = AlloraWalletConfig.from_env()
    except ValueError as exc:  # pragma: no cover - environment specific
        logger.error("Wallet configuration error: %s", exc)
        return False

    network = AlloraNetworkConfig(
        chain_id="allora-testnet-1",
        url="grpc+https://allora-rpc.testnet.allora.network/",
        websocket_url="wss://allora-rpc.testnet.allora.network/websocket",
        fee_denom="uallo",
        fee_minimum_gas_price=10.0,
    )

    worker = AlloraWorker(
        run=lambda _: float(prediction),
        wallet=wallet,
        network=network,
        api_key=api_key,
        topic_id=TOPIC_ID,
        polling_interval=60,
    )

    async for outcome in worker.run(timeout=120):
        worker.stop()
        if outcome is None:
            continue
        logger.info("Submission broadcast attempted")
        return True

    worker.stop()
    logger.error("Submission did not return a result")
    return False


def submit_prediction(prediction: float) -> bool:
    return asyncio.run(_submit_async(prediction))


def main() -> None:
    raw = fetch_btcusd_data()
    features = preprocess_data(raw)
    labeled = add_target(features)

    training_frame = labeled.tail(TRAIN_WINDOW_HOURS)
    if training_frame.empty:
        raise RuntimeError("Not enough data to train the model")

    model = train_model(training_frame)
    prediction = predict_latest(model, features)
    save_artifact(prediction)
    submit_prediction(prediction)


if __name__ == "__main__":
    main()
