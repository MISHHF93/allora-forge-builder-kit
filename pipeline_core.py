"""Core feature engineering, training, and submission helpers."""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from pipeline_utils import ARTIFACTS_DIR, LOG_DIR, ensure_directories


def generate_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["log_price"] = np.log(df["close"])
    df["ret_1h"] = df["log_price"].diff(1)
    df["ret_24h"] = df["log_price"].diff(24)
    df["ma_24h"] = df["close"].rolling(24).mean()
    df["ma_72h"] = df["close"].rolling(72).mean()
    df["vol_24h"] = df["ret_1h"].rolling(24).std()
    df["price_pos_24h"] = df["close"] / df["ma_24h"] - 1.0
    df["price_pos_72h"] = df["close"] / df["ma_72h"] - 1.0
    df["ma_ratio_72_24"] = df["ma_72h"] / df["ma_24h"] - 1.0
    df["exp_vol_ratio"] = df["vol_24h"].rolling(24).mean() / (df["vol_24h"] + 1e-8) - 1.0
    df = df.dropna().reset_index(drop=True)
    return df


def add_forward_target(df: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    df = df.copy()
    future_price = df["close"].shift(-horizon_hours)
    df["target"] = np.log(future_price / df["close"])
    return df.iloc[:-horizon_hours]


def train_model(train_df: pd.DataFrame, feature_cols: List[str]) -> Ridge:
    model = Ridge(alpha=1.0)
    model.fit(train_df[feature_cols], train_df["target"])
    return model


def save_artifacts(model: object, feature_cols: List[str]) -> None:
    ensure_directories()
    model_path = ARTIFACTS_DIR / "model.pkl"
    features_path = ARTIFACTS_DIR / "features.json"
    import joblib

    joblib.dump(model, model_path)
    with features_path.open("w") as f:
        json.dump(feature_cols, f, indent=2)


def artifacts_available() -> bool:
    return (ARTIFACTS_DIR / "model.pkl").exists() and (ARTIFACTS_DIR / "features.json").exists()


def load_artifacts() -> Tuple[object, List[str]]:
    import joblib

    model_path = ARTIFACTS_DIR / "model.pkl"
    features_path = ARTIFACTS_DIR / "features.json"

    model = joblib.load(model_path)
    with features_path.open() as f:
        features = json.load(f)
    return model, features


def latest_feature_row(df: pd.DataFrame, feature_cols: List[str]) -> np.ndarray:
    return df[feature_cols].iloc[-1:].values


def validate_prediction(prediction: float, max_abs: float = 1.5) -> bool:
    if prediction is None or not math.isfinite(prediction):
        return False
    return abs(prediction) <= max_abs


def log_submission_record(
    timestamp: datetime,
    topic_id: int,
    prediction: float,
    worker: str,
    status: str,
    extra: dict | None = None,
) -> Path:
    ensure_directories()
    csv_path = LOG_DIR / "submission_log.csv"
    header_needed = not csv_path.exists()
    with csv_path.open("a", newline="") as f:
        fieldnames = ["timestamp", "topic_id", "prediction", "worker", "status", "details"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if header_needed:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp.isoformat(),
                "topic_id": topic_id,
                "prediction": prediction,
                "worker": worker,
                "status": status,
                "details": json.dumps(extra or {}),
            }
        )
    return csv_path


def artifacts_fresh_enough(reference: Path, artifacts_paths: list[Path]) -> bool:
    """Check artifact timestamps against a reference (e.g., cache) file."""
    if not reference.exists():
        return False
    ref_mtime = reference.stat().st_mtime
    for path in artifacts_paths:
        if not path.exists() or path.stat().st_mtime < ref_mtime:
            return False
    return True
