"""
Allora network status helpers for v0.14+ CLI.
"""

from __future__ import annotations
import json, shutil, subprocess
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class WindowStatus:
    cli_found: bool
    topic_active: Optional[bool] = None
    worker_registered: Optional[bool] = None
    worker_can_submit: Optional[bool] = None
    latest_nonce: Optional[int] = None
    raw_outputs: Dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def ok_to_submit(self) -> bool:
        return (
            self.cli_found
            and self.topic_active is True
            and self.worker_registered is True
            and self.worker_can_submit is True
        )


def _run_cli(cmd: list[str], logger):
    cli = shutil.which("allorad")
    if not cli:
        raise FileNotFoundError("allorad CLI not installed")

    full_cmd = [cli] + cmd
    logger.debug("Running CLI command: %s", " ".join(full_cmd))

    proc = subprocess.run(full_cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

    output = proc.stdout.strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        raise RuntimeError(f"CLI returned non‑JSON output:\n{output}")


def query_window_status(topic_id: int, wallet: str, logger) -> WindowStatus:
    status = WindowStatus(cli_found=bool(shutil.which("allorad")))
    if not status.cli_found:
        status.errors.append("allorad CLI not found")
        return status

    # -----------------------------------------------------------
    # 1️⃣ Check if topic is active
    # -----------------------------------------------------------
    try:
        resp = _run_cli(
            ["q", "emissions", "is-topic-active", str(topic_id)],
            logger
        )
        status.raw_outputs["is_topic_active"] = resp

        # Correct key from CLI: "is_active"
        status.topic_active = resp.get("is_active", False)
        logger.info("✅ Topic %s active: %s", topic_id, status.topic_active)

    except Exception as exc:
        status.errors.append(f"is-topic-active error: {exc}")
        logger.error("❌ Topic active check failed: %s", exc)

    # -----------------------------------------------------------
    # 2️⃣ Check if worker is registered
    # -----------------------------------------------------------
    try:
        resp = _run_cli(
            ["q", "emissions", "is-worker-registered", str(topic_id), wallet],
            logger
        )
        status.raw_outputs["is_worker_registered"] = resp

        # Correct key from CLI: "is_registered"
        status.worker_registered = resp.get("is_registered", False)
        logger.info("✅ Worker registered: %s", status.worker_registered)

    except Exception as exc:
        status.errors.append(f"is-worker-registered error: {exc}")
        logger.error("❌ Worker registration check failed: %s", exc)

    # -----------------------------------------------------------
    # 3️⃣ Check worker submission window
    # CORRECT ORDER: topic_id → wallet
    # -----------------------------------------------------------
    try:
        resp = _run_cli(
            [
                "q", "emissions", "worker-submission-window-status",
                str(topic_id), wallet,
                "--node", "https://allora-rpc.testnet.allora.network/",
            ],
            logger
        )
        status.raw_outputs["submission_window"] = resp

        # Correct key: "is_open"
        status.worker_can_submit = resp.get("is_open", False)

        # The chain does NOT expose a numeric nonce, but block height:
        # "current_nonce_block_height": "6766795"
        if "current_nonce_block_height" in resp:
            try:
                status.latest_nonce = int(resp["current_nonce_block_height"])
            except:
                status.latest_nonce = None

        logger.info(
            "✅ Can submit: %s (Block/Nonce: %s)",
            status.worker_can_submit, status.latest_nonce
        )

    except Exception as exc:
        status.errors.append(f"worker-submission-window-status error: {exc}")
        logger.error("❌ Submission window check failed: %s", exc)

    return status

