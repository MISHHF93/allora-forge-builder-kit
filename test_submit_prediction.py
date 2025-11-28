import json
from pathlib import Path

import pytest

from pipeline_core import FEATURE_COLUMNS
from submit_prediction import load_bundle, submit_prediction


def test_load_bundle_falls_back_when_missing(monkeypatch, tmp_path, caplog):
    caplog.set_level("INFO")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("submit_prediction.MODEL_BUNDLE_PATH", tmp_path / "model_bundle.joblib")

    import logging

    logger = logging.getLogger("test")
    model, feature_names, bundle_meta = load_bundle(logger)

    assert feature_names == FEATURE_COLUMNS
    assert hasattr(model, "predict")
    assert bundle_meta.get("fallback") is True


def test_submit_prediction_dry_run_without_wallet(monkeypatch, tmp_path):
    """Dry-run submissions should work without blockchain credentials."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ALLORA_WALLET_ADDR", raising=False)

    result = submit_prediction(0.1234, topic_id=99, dry_run=True)

    assert result is True

    latest_path = Path("latest_submission.json")
    assert latest_path.exists()
    latest = json.loads(latest_path.read_text())
    assert latest["status"] == "dry_run"
    assert latest["topic_id"] == 99
    assert latest["worker"] == "dry-run"

    log_path = Path("logs/submission_log.csv")
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert lines[0].startswith("timestamp,topic_id,prediction,worker,status")
    assert any("dry_run" in line for line in lines[1:])
