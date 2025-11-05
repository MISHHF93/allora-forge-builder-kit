#!/usr/bin/env python3
"""Submit the latest prediction artifact to the Allora network.

This script loads ``data/artifacts/predictions.json`` emitted by ``train.py``
and uses the async submission helpers that live in ``train.py`` to perform
an SDK-based submission. The goal is to keep a single source of truth for
Allora-specific submission logic while still allowing external automation to
invoke submissions directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import train

from allora_forge_builder_kit.submission_log import ensure_submission_log_schema

DEFAULT_TOPIC_ID = 67
DEFAULT_WALLET_ADDR = "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"


def _load_prediction(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):  # pragma: no cover - defensive guard
        raise ValueError("Prediction artifact must be a JSON object")
    if "value" not in data:
        raise KeyError("Prediction artifact missing 'value'")
    return data


def _load_log10_loss(root: Path) -> Optional[float]:
    metrics_path = root / "data" / "artifacts" / "metrics.json"
    if not metrics_path.exists():
        return None
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(metrics, dict):
        val = metrics.get("log10_loss") or metrics.get("loss")
        try:
            if val is not None:
                return float(val)
        except (TypeError, ValueError):
            return None
    return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Submit prediction for Allora topic 67 using the SDK")
    parser.add_argument("--topic-id", type=int, default=DEFAULT_TOPIC_ID, help="Topic identifier to submit against")
    parser.add_argument("--prediction", default=None, help="Path to predictions.json (defaults to data/artifacts/predictions.json)")
    parser.add_argument("--wallet", default=None, help="Wallet address override (defaults to env or configured wallet)")
    parser.add_argument("--timeout", type=int, default=60, help="Submission timeout in seconds for SDK helper")
    parser.add_argument("--retries", type=int, default=3, help="Maximum SDK retry attempts")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent
    prediction_path = Path(args.prediction) if args.prediction else root / "data" / "artifacts" / "predictions.json"
    if not prediction_path.exists():
        raise FileNotFoundError(f"Prediction artifact not found: {prediction_path}")

    artifact = _load_prediction(prediction_path)
    topic_id = int(artifact.get("topic_id", args.topic_id or DEFAULT_TOPIC_ID))
    if topic_id != args.topic_id:
        print(
            f"INFO: overriding topic_id from artifact ({artifact.get('topic_id')}) with CLI value {args.topic_id}",
            file=sys.stderr,
        )
        topic_id = int(args.topic_id)

    value_raw = artifact.get("value")
    if value_raw is None:
        raise ValueError("Prediction artifact missing numeric 'value'")
    try:
        prediction_value = float(value_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Prediction value must be numeric, got {value_raw!r}") from exc

    wallet = (args.wallet or os.getenv("ALLORA_WALLET_ADDR") or DEFAULT_WALLET_ADDR).strip()
    os.environ["ALLORA_WALLET_ADDR"] = wallet

    # Ensure the submission log exists prior to calling into the train helpers so
    # that even early exits from the helper have a place to record metadata.
    log_path = root / "submission_log.csv"
    ensure_submission_log_schema(str(log_path))

    api_key = os.getenv("ALLORA_API_KEY", "").strip()
    if not api_key:
        api_key = train._require_api_key()  # pylint: disable=protected-access

    pre_log10_loss = _load_log10_loss(root)

    # Delegate to the async SDK helper living in train.py so submission logging
    # remains centralized. The helper already records detailed metadata to
    # submission_log.csv via train._log_submission.
    result_code = asyncio.run(
        train._submit_with_sdk(  # type: ignore[attr-defined]
            int(topic_id),
            float(prediction_value),
            api_key,
            int(args.timeout),
            int(args.retries),
            str(root),
            pre_log10_loss,
        )
    )

    if result_code == 0:
        print(
            f"Submission successful for topic {topic_id} using wallet {wallet} with value {prediction_value}",
            file=sys.stderr,
        )
    else:
        print(
            f"Submission helper exited with code {result_code} for topic {topic_id} (wallet={wallet})",
            file=sys.stderr,
        )
    return int(result_code)


if __name__ == "__main__":
    sys.exit(main())
