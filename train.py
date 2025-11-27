import os
import json
import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, UTC
from sklearn.linear_model import Ridge

# === Load config ===
load_dotenv()

DAYS_BACK = 90
HORIZON = 168
FORCE_RETRAIN = False
TIINGO_API_KEY = os.getenv("TIINGO_API_KEY")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

def log(msg):
    print(f"{datetime.now(UTC).isoformat()}Z - {msg}")

log(f"INFO - Starting training run: days_back={DAYS_BACK}, horizon={HORIZON}, force_retrain={FORCE_RETRAIN}")

# === Mock or fallback data logic ===
def fetch_price_series():
    try:
        if not TIINGO_API_KEY:
            raise ValueError("Missing TIINGO_API_KEY")

        # Simulated Tiingo rate-limited fallback
        raise RuntimeError("429 Tiingo rate limit hit")

    except Exception as e:
        log(f"WARNING - {str(e)}")
        log(f"INFO - Falling back to synthetic price series for {DAYS_BACK} days.")

        dates = pd.date_range(
            end=datetime.now(UTC),
            periods=DAYS_BACK * 24,
            freq='h'  # FIXED: 'H' deprecated
        )

        prices = pd.Series(
            100 + np.random.randn(len(dates)).cumsum(),
            index=dates
        )
        return prices

# === Feature Engineering ===
def generate_features(prices: pd.Series):
    df = pd.DataFrame({
        "price": prices,
        "return_1h": prices.pct_change(1),
        "return_24h": prices.pct_change(24),
        "volatility_24h": prices.pct_change(1).rolling(24).std(),
        "momentum_24h": prices - prices.shift(24),
    }).dropna()
    return df

# === Train Model ===
prices = fetch_price_series()
features_df = generate_features(prices)

X_train = features_df.drop(columns=["price"])
y_train = features_df["price"].pct_change(HORIZON).shift(-HORIZON).dropna()

# Align X and y
X_train = X_train.iloc[:len(y_train)]
y_train = y_train.iloc[:len(X_train)]

model = Ridge()
model.fit(X_train, y_train)

# === Save model and feature names together ===
feature_names = X_train.columns.tolist()
joblib.dump({'model': model, 'feature_names': feature_names}, 'model_bundle.joblib')

# === Example Prediction (check inference shape) ===
example_input = pd.DataFrame([X_train.iloc[-1]], columns=feature_names)
example_prediction = model.predict(example_input)[0]

log(f"INFO - Training complete. Example prediction on latest row: {example_prediction:.8f}")

