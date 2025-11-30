"""Helpers for submitting predictions to the Allora chain via CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Tuple


def _build_payload(topic_id: int, value: float) -> str:
    """Return proto-text payload expected by the insert-worker-payload command."""
    return f'topic_id: {int(topic_id)} value: {float(value)}'


def submit_prediction_to_chain(
    topic_id: int,
    value: float,
    wallet: str,
    logger,
) -> Tuple[bool, str | None]:
    """Submit a prediction to the Allora chain.

    Returns a tuple of (success flag, tx_hash if available).
    """

    cli = shutil.which("allorad")
    if not cli:
        logger.error("❌ allorad CLI not found in PATH")
        return False, None

    payload = _build_payload(topic_id, value)

    # Load from .env or use sensible fallbacks
    chain_id = os.getenv("CHAIN_ID", "allora-testnet-1")
    node = os.getenv("RPC_URL", "https://allora-rpc.testnet.allora.network/")
    fees = os.getenv("ALLORA_FEES", "2500000uallo")
    gas = os.getenv("ALLORA_GAS", "250000")
    keyring_backend = os.getenv("ALLORA_KEYRING_BACKEND", "test")

    cmd = [
        cli,
        "tx",
        "emissions",
        "insert-worker-payload",
        wallet,
        payload,  # This must be quoted or single argument
        "--from", wallet,
        "--yes",
        "--keyring-backend", keyring_backend,
        "--chain-id", chain_id,
        "--node", node,
        "--fees", fees,
        "--gas", gas,
        "--broadcast-mode", "sync",
        "--output", "json",
    ]

    logger.info("📨 Submitting prediction: topic_id=%s value=%.6f", topic_id, value)
    logger.debug("Running command: %s", " ".join(cmd))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        logger.error("❌ CLI submission failed: %s", exc)
        return False, None

    if proc.returncode != 0:
        logger.error("❌ TX failed with code %s: %s", proc.returncode, proc.stderr.strip())
        logger.debug("⚙️ stdout: %s", proc.stdout.strip())
        logger.debug("⚙️ stderr: %s", proc.stderr.strip())
        return False, None

    try:
        resp = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.error("❌ Failed to parse JSON response: %s", exc)
        logger.debug("Raw output: %s", proc.stdout.strip())
        return False, None

    tx_hash = resp.get("txhash")
    code = resp.get("code", 1)

    if code == 0 and tx_hash:
        logger.info("✅ Submission succeeded! TX hash: %s", tx_hash)
        return True, tx_hash

    logger.error("❌ Submission rejected by chain: %s", json.dumps(resp, indent=2))
    return False, None

