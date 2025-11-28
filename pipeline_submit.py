"""Helpers for submitting predictions to the Allora chain via CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Tuple


def _build_payload(topic_id: int, value: float) -> str:
    """Return proto-text payload expected by the insert-worker-payload command."""

    # The CLI expects a single argument with proto-text formatting (not JSON).
    # Example: "topic_id: 67 value: -0.07178"
    return f"topic_id: {int(topic_id)} value: {value}"


def submit_prediction_to_chain(
    topic_id: int,
    value: float,
    wallet: str,
    logger,
) -> Tuple[bool, str | None]:
    """Submit a prediction to the Allora chain.

    Returns a tuple of (success flag, tx_hash if available).
    """

    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        logger.error("Allora CLI not found on PATH")
        return False, None

    payload = _build_payload(topic_id, value)

    chain_id = os.getenv("ALLORA_CHAIN_ID", "allora-testnet-1")
    node = os.getenv("ALLORA_NODE", "https://allora-rpc.testnet.allora.network/")
    fees = os.getenv("ALLORA_FEES", "2500000uallo")
    gas = os.getenv("ALLORA_GAS", "250000")
    keyring_backend = os.getenv("ALLORA_KEYRING_BACKEND", "test")

    cmd = [
        cli,
        "tx",
        "emissions",
        "insert-worker-payload",
        wallet,
        payload,
        "--from",
        wallet,
        "--yes",
        "--keyring-backend",
        keyring_backend,
        "--chain-id",
        chain_id,
        "--node",
        node,
        "--fees",
        fees,
        "--gas",
        gas,
        "--broadcast-mode",
        "sync",
        "--output",
        "json",
    ]

    logger.info("Submitting prediction to chain with payload: %s", payload)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:  # pragma: no cover - protective logging
        logger.error("Submission command failed: %s", exc)
        return False, None

    if proc.returncode != 0:
        logger.error("Submission failed (exit %s): %s", proc.returncode, proc.stderr.strip())
        logger.debug("Command stdout: %s", proc.stdout.strip())
        return False, None

    try:
        resp = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.error("Unable to parse submission response as JSON: %s", exc)
        logger.debug("Raw response: %s", proc.stdout.strip())
        return False, None

    tx_hash = resp.get("txhash")
    code = resp.get("code", 1)

    if code == 0 and tx_hash:
        logger.info("Submission accepted with tx hash %s", tx_hash)
        return True, tx_hash

    logger.error("Submission rejected: %s", resp)
    return False, tx_hash
