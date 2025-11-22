from __future__ import annotations

import logging
import os
import pathlib
from typing import Tuple

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LinearRegression

from .environment import load_environment
from .submission import submit_prediction

BTC_MARKET_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
DEFAULT_HISTORY_DAYS = 90
MIN_HISTORY_DAYS = 60
FORECAST_HOURS = 24 * 7
DEFAULT_TOPIC_ID = int(os.getenv("ALLORA_TOPIC_ID", "67"))


logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
logger = logging.getLogger("pipeline")


def fetch_data(days: int = DEFAULT_HISTORY_DAYS) -> pd.DataFrame:
    """Fetch recent BTC/USD price and volume history.

    The Coingecko hourly endpoint returns up to 90 days of hourly prices and
    total volumes. The data is aligned to UTC timestamps so the latest row
    represents the most recent completed hour.
    """

    params = {"vs_currency": "usd", "days": days, "interval": "hourly"}
    response = requests.get(BTC_MARKET_URL, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()

    prices = payload.get("prices", [])
    volumes = payload.get("total_volumes", [])
    if not prices or not volumes:
        raise RuntimeError("BTC/USD response did not include price and volume data")

    price_frame = pd.DataFrame(prices, columns=["timestamp", "price"])
    volume_frame = pd.DataFrame(volumes, columns=["timestamp", "volume"])
    price_frame["timestamp"] = pd.to_datetime(price_frame["timestamp"], unit="ms", utc=True)
    volume_frame["timestamp"] = pd.to_datetime(volume_frame["timestamp"], unit="ms", utc=True)

    merged = (
        price_frame.set_index("timestamp")
        .join(volume_frame.set_index("timestamp"), how="inner")
        .sort_index()
        .rename_axis("timestamp")
    )
    return merged.ffill().dropna()


def generate_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Prepare a feature matrix from hourly BTC/USD price and volume."""

    frame = raw.copy()
    frame = frame.resample("1h").last().ffill()
    frame["log_price"] = np.log(frame["price"])
    frame["hourly_return"] = frame["log_price"].diff()
    frame["rolling_volatility_24h"] = frame["hourly_return"].rolling(24).std()
    frame["rolling_volatility_7d"] = frame["hourly_return"].rolling(FORECAST_HOURS).std()
    frame["rolling_volume_7d"] = frame["volume"].rolling(FORECAST_HOURS).mean()
    frame["price_trend_7d"] = frame["price"].rolling(FORECAST_HOURS).apply(lambda x: np.polyfit(range(len(x)), x, 1)[0])
    return frame.dropna()


def calculate_log_return(features: pd.DataFrame, horizon_hours: int = FORECAST_HOURS) -> pd.DataFrame:
    """Attach the 7-day forward log-return target."""

    target = np.log(features["price"].shift(-horizon_hours) / features["price"])
    dataset = features.copy()
    dataset["target"] = target
    return dataset.dropna(subset=["target"])


def train_model(dataset: pd.DataFrame) -> Tuple[LinearRegression, list[str]]:
    """Train a simple linear regression model on prepared features."""

    X = dataset.drop(columns=["target"])
    y = dataset["target"]
    model = LinearRegression()
    model.fit(X.values, y.values)
    return model, list(X.columns)


def predict_next_log_return(model: LinearRegression, feature_frame: pd.DataFrame, columns: list[str]) -> float:
    """Generate a prediction for the most recent hour."""

    latest_row = feature_frame.tail(1)[columns]
    prediction = float(model.predict(latest_row.values)[0])
    return prediction


def main() -> int:
    repo_root = os.getenv("REPO_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_environment(pathlib.Path(repo_root))

    history = fetch_data(DEFAULT_HISTORY_DAYS)
    if len(history) < MIN_HISTORY_DAYS * 24:
        raise RuntimeError("Not enough historical data to compute a stable 7-day return")

    features = generate_features(history)
    dataset = calculate_log_return(features)
    model, columns = train_model(dataset)
    prediction = predict_next_log_return(model, features, columns)

    logger.info("Predicted 7-day log-return: %.6f", prediction)
    result = submit_prediction(prediction, topic_id=DEFAULT_TOPIC_ID)
    status = "submitted" if result.success else f"failed: {result.status}"
    logger.info("Submission %s (tx=%s nonce=%s)", status, result.tx_hash, result.nonce)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
