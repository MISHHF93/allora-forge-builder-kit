import os
from getpass import getpass

def train_model(training_price_data_path: str, model_file_path: str) -> None:
    """
    Deprecated.

    This repository now enforces an XGBoost-only policy for modeling.
    The legacy LinearRegression trainer has been removed to avoid accidental use
    of non-XGB models. Please use the main pipeline in `train.py`, which trains
    and saves the XGB model bundle at `models/xgb_model.pkl`.
    """
    raise NotImplementedError(
        "Non-XGBoost training is disabled. Use train.py for the XGB-only pipeline."
    )

def get_api_key(api_key_file=".allora_api_key"):
    """
    Load API key from file if available, otherwise prompt and save it.
    """
    if os.path.exists(api_key_file):
        with open(api_key_file, "r") as f:
            return f.read().strip()

    key = getpass("Enter your Allora API key: ").strip()
    with open(api_key_file, "w") as f:
        f.write(key)
    return key