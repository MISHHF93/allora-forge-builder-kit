"""
Allora network status helpers for v0.14.0 CLI.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class WindowStatus:
    cli_found: bool
    topic_active: Optional[bool] = None
    worker_has_nonce: Optional[bool] = None
    latest_nonce: Optional[int] = None
    raw_outputs: Dict[str, object] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def ok_to_submit(self) -> bool:
        return (
            self.cli_found
            and self.topic_active is True
            and self.worker_has_nonce is True
        )


def _run_cli(cmd: list[str], logger):
    cli = shutil.which("allorad")
    if not cli:
        raise FileNotFoundError("allorad CLI not installed")

    command = [cli] + cmd
    logger.debug("Running command: %s", " ".join(command))

    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"Failed to parse JSON: {exc}")


def query_window_status(topic_id: int, wallet: str, logger) -> WindowStatus:
    status = WindowStatus(cli_found=bool(shutil.which("allorad")))
    if not status.cli_found:
        status.errors.append("allorad CLI not found")
        return status

    # 1️⃣ Check if topic is active using new command
    try:
        resp = _run_cli(
            ["query", "emissions", "is-topic-active", str(topic_id)],
            logger
        )
        status.raw_outputs["is_topic_active"] = resp
        status.topic_active = resp.get("active", False)
    except Exception as exc:
        status.errors.append(f"is-topic-active error: {exc}")

    # 2️⃣ Check worker submission window
    try:
        resp = _run_cli(
            ["query", "emissions", "worker-submission-window-status", wallet, str(topic_id)],
            logger
        )
        status.raw_outputs["submission_window"] = resp
        nonce = resp.get("latestNonce")
        status.worker_has_nonce = resp.get("canSubmit", False)
        if nonce is not None:
            status.latest_nonce = int(nonce)
    except Exception as exc:
        status.errors.append(f"worker-submission-window-status error: {exc}")

    # 3️⃣ Optionally: check for unfulfilled nonces (optional, non-blocking)
    try:
        resp = _run_cli(
            ["query", "emissions", "unfulfilled-worker-nonces", str(topic_id)],
            logger
        )
        status.raw_outputs["unfulfilled"] = resp
    except Exception as exc:
        status.errors.append(f"unfulfilled-worker-nonces error: {exc}")

    return status

