import json
from pathlib import Path

from submit_prediction import submit_prediction


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

    log_path = Path("submission_log.csv")
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert lines[0].startswith("timestamp,topic_id,prediction,worker,block_height")
    assert any("dry_run" in line for line in lines[1:])
