"""Allora network status helpers for safe submission windows."""
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
        return bool(
            self.cli_found
            and self.topic_active is True
            and self.worker_has_nonce is True
            and (self.latest_nonce is None or self.latest_nonce >= 0)
        )


def _run_allorad(args: list[str], logger) -> tuple[Optional[object], str]:
    cli = shutil.which("allorad") or shutil.which("allora")
    if not cli:
        raise FileNotFoundError("allorad CLI not installed")
    cmd = [cli] + args + ["--output", "json"]
    logger.debug("Running allorad command: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    try:
        return json.loads(proc.stdout), proc.stdout
    except Exception as exc:
        raise RuntimeError(f"Failed to parse allorad output: {exc}")


def query_window_status(topic_id: int, worker: str, logger) -> WindowStatus:
    status = WindowStatus(cli_found=bool(shutil.which("allorad") or shutil.which("allora")))
    if not status.cli_found:
        status.errors.append("allorad CLI not found")
        return status

    try:
        topic_resp, raw_topic = _run_allorad(
            ["q", "emissions", "is-topic-active", "--id", str(topic_id)], logger
        )
        status.raw_outputs["is_topic_active"] = topic_resp
        status.topic_active = bool(topic_resp)
    except Exception as exc:
        status.errors.append(f"topic-active query failed: {exc}")

    try:
        nonce_resp, raw_nonce = _run_allorad(
            ["q", "emissions", "worker-nonce-unfulfilled", str(topic_id), worker], logger
        )
        status.raw_outputs["worker_nonce"] = nonce_resp
        # The response may be a dict with nonce field or boolean
        if isinstance(nonce_resp, dict):
            nonce_value = nonce_resp.get("nonce") or nonce_resp.get("unfulfilledNonce")
            status.latest_nonce = int(nonce_value) if nonce_value is not None else None
            status.worker_has_nonce = nonce_value is not None
        else:
            status.worker_has_nonce = bool(nonce_resp)
    except Exception as exc:
        status.errors.append(f"worker-nonce query failed: {exc}")

    try:
        unfulfilled_resp, _ = _run_allorad(
            ["q", "emissions", "unfulfilled-worker-nonces", str(topic_id)], logger
        )
        status.raw_outputs["unfulfilled_nonces"] = unfulfilled_resp
    except Exception as exc:
        status.errors.append(f"unfulfilled nonce query failed: {exc}")

    return status


__all__ = ["WindowStatus", "query_window_status"]
