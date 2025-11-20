"""Tests for verifying Allora API key handling in the builder kit."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


# Ensure environment variables are available even when pytest is launched without
# an explicit ``--env`` flag. This mirrors the behaviour configured in
# ``conftest.py`` but keeps the test runnable in isolation.
ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env", override=False)


def _require_api_key() -> str:
    key = (os.getenv("ALLORA_API_KEY") or "").strip()
    if not key:
        pytest.skip("ALLORA_API_KEY not configured; skipping API key flow tests.")
    return key


def test_allora_api_key_loaded_from_env():
    """The Allora API key should be present after loading .env."""

    key = _require_api_key()
    assert key, "ALLORA_API_KEY should be non-empty once .env is loaded."


def test_allora_worker_receives_api_key(monkeypatch):
    """Ensure the API key is passed through to the worker constructor."""

    api_key = _require_api_key()

    try:
        import allora_sdk.worker as sdk_worker
    except ImportError:
        pytest.skip("allora-sdk not installed; skipping worker integration check.")

    captured: dict[str, object] = {}

    class DummyWorker:
        def __init__(self, run, api_key, topic_id):  # noqa: ANN001 - external signature
            captured["run"] = run
            captured["api_key"] = api_key
            captured["topic_id"] = topic_id

    monkeypatch.setattr(sdk_worker, "AlloraWorker", DummyWorker)

    def dummy_run(topic_id: int) -> float:
        return float(topic_id)

    worker = sdk_worker.AlloraWorker(run=dummy_run, api_key=api_key, topic_id=67)

    assert captured["api_key"] == api_key
    assert captured["topic_id"] == 67
    assert callable(captured["run"])
    assert isinstance(worker, DummyWorker)

