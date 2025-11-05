#!/usr/bin/env python3
"""Orchestrate training and submission for Allora topic 67.

This script executes ``train.py`` followed by ``submit_prediction.py`` using the
current Python interpreter. It captures stdout/stderr into structured log files,
rotates historical logs, inspects failures, and appends submission metadata to
``submission_log.csv``. The workflow is designed so it can run unattended in a
VM and rely on its own logs to diagnose and retry common issues like submission
cooldowns or unfulfilled worker nonces.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from allora_forge_builder_kit.submission_log import (
    CANONICAL_SUBMISSION_HEADER,
    ensure_submission_log_schema,
    log_submission_row,
    normalize_submission_log_file,
)
from dotenv import find_dotenv, load_dotenv

KEEP_LOGS_PER_STEP = 10
LOG_STEPS = ("train", "submit", "resolve")
DEFAULT_WALLET_ADDR = "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
DEFAULT_TOPIC_ID = 67
DEFAULT_RETRY_DELAY = 120
MAX_AUTO_ATTEMPTS = 3


class StepResult:
    __slots__ = ("step", "command", "returncode", "log_path", "log_excerpt")

    def __init__(self, step: str, command: List[str], returncode: int, log_path: Path, log_excerpt: str) -> None:
        self.step = step
        self.command = command
        self.returncode = returncode
        self.log_path = log_path
        self.log_excerpt = log_excerpt

    def ok(self) -> bool:
        return self.returncode == 0


def _now_ts() -> datetime:
    return datetime.now(timezone.utc)


def _window_timestamp() -> str:
    ts = _now_ts().replace(minute=0, second=0, microsecond=0)
    return ts.strftime("%Y-%m-%dT%H:00:00Z")


def _log_dir(root: Path) -> Path:
    return root / "data" / "artifacts" / "logs"


def _ensure_log_dirs(root: Path) -> None:
    for step in LOG_STEPS:
        step_dir = _log_dir(root) / step
        step_dir.mkdir(parents=True, exist_ok=True)


def _rotate_logs(step_dir: Path, keep: int = KEEP_LOGS_PER_STEP) -> None:
    logs = sorted([p for p in step_dir.glob("*.log") if p.is_file()])
    if len(logs) <= keep:
        return
    for old in logs[: len(logs) - keep]:
        try:
            old.unlink()
        except OSError:
            continue


def _write_manual_log(step: str, message: str, root: Path) -> Path:
    _ensure_log_dirs(root)
    step_dir = _log_dir(root) / step
    step_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _now_ts().strftime("%Y%m%dT%H%M%SZ")
    log_path = step_dir / f"{timestamp}_{step}.log"
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")
    _rotate_logs(step_dir)
    return log_path


def _capture_step(step: str, cmd: List[str], root: Path, env: Optional[Dict[str, str]] = None) -> StepResult:
    _ensure_log_dirs(root)
    step_dir = _log_dir(root) / step
    step_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _now_ts().strftime("%Y%m%dT%H%M%SZ")
    log_path = step_dir / f"{timestamp}_{step}.log"
    excerpt_lines: List[str] = []

    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(cmd)}\n")
        fh.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            fh.write(line)
            if len(excerpt_lines) < 40:
                excerpt_lines.append(line.rstrip())
        proc.wait()
        rc = proc.returncode
    _rotate_logs(step_dir)
    excerpt = "\n".join(excerpt_lines)
    return StepResult(step, cmd, rc, log_path, excerpt)


def _read_submission_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [row for row in reader]


def _parse_status(row: Optional[Dict[str, str]]) -> Tuple[bool, Optional[str]]:
    if not row:
        return False, None
    success_flag = str(row.get("success", "")).strip().lower() in ("true", "1")
    status = (row.get("status") or "").strip()
    return success_flag, status or None


def _status_reason(status: Optional[str]) -> Optional[str]:
    if not status:
        return None
    low = status.lower()
    if "cooldown" in low:
        return "cooldown"
    if "unfulfilled" in low:
        return "unfulfilled_nonces"
    if "not_ready" in low or "not rewardable" in low:
        return "not_rewardable"
    if "duplicate" in low:
        return "duplicate"
    if "not_whitelisted" in low:
        return "not_whitelisted"
    if "sdk_error" in low:
        return "sdk_error"
    return None


def _query_unfulfilled(root: Path, env: Dict[str, str]) -> StepResult:
    cmd = [
        "allorad",
        "q",
        "emissions",
        "unfulfilled-worker-nonces",
        str(DEFAULT_TOPIC_ID),
        "--node",
        env.get("ALLORA_RPC_URL")
        or env.get("ALLORA_NODE")
        or os.getenv("ALLORA_RPC_URL", "https://allora-rpc.testnet.allora.network"),
        "--output",
        "json",
        "--trace",
    ]
    try:
        return _capture_step("resolve", cmd, root, env)
    except FileNotFoundError:
        # allorad not available; write a synthetic log entry
        step_dir = _log_dir(root) / "resolve"
        timestamp = _now_ts().strftime("%Y%m%dT%H%M%SZ")
        log_path = step_dir / f"{timestamp}_resolve.log"
        with log_path.open("w", encoding="utf-8") as fh:
            fh.write("ERROR: allorad CLI not found while attempting to query unfulfilled nonces\n")
        _rotate_logs(step_dir)
        return StepResult("resolve", cmd, 127, log_path, "allorad CLI not found")


def _log_training_failure(
    root: Path,
    exit_code: int,
    value: Optional[float],
    *,
    status: str = "train_error",
) -> None:
    csv_path = root / "submission_log.csv"
    ensure_submission_log_schema(str(csv_path))
    row = {
        "timestamp_utc": _window_timestamp(),
        "topic_id": DEFAULT_TOPIC_ID,
        "value": value if value is not None else None,
        "wallet": os.getenv("ALLORA_WALLET_ADDR", DEFAULT_WALLET_ADDR),
        "nonce": None,
        "tx_hash": None,
        "success": False,
        "exit_code": exit_code,
        "status": status,
        "log10_loss": None,
        "score": None,
        "reward": None,
    }
    log_submission_row(str(csv_path), row)
    normalize_submission_log_file(str(csv_path))


def _extract_api_key_from_text(text: str) -> Optional[str]:
    stripped = text.strip()
    if not stripped:
        return None
    if "\n" not in stripped and "=" not in stripped and ":" not in stripped and len(stripped) >= 8:
        return stripped
    for line in stripped.splitlines():
        chunk = line.strip()
        if not chunk or chunk.startswith("#"):
            continue
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        elif ":" in chunk:
            key, value = chunk.split(":", 1)
        else:
            continue
        key = key.strip().lower()
        if key in {"allora_api_key", "api_key", "alloraapikey"}:
            candidate = value.strip().strip('"').strip("'")
            if candidate:
                return candidate
    return None


def _extract_api_key_from_path(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
            if isinstance(data, dict):
                for key in ("ALLORA_API_KEY", "allora_api_key", "api_key"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            return None
        return _extract_api_key_from_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _ensure_api_key(env: Dict[str, str], root: Path) -> Tuple[Optional[str], List[Path]]:
    current = env.get("ALLORA_API_KEY") or os.getenv("ALLORA_API_KEY")
    if current and current.strip():
        env["ALLORA_API_KEY"] = current.strip()
        return current.strip(), []

    candidate_paths: List[Path] = []

    explicit_file = env.get("ALLORA_API_KEY_FILE") or os.getenv("ALLORA_API_KEY_FILE")
    if explicit_file:
        candidate_paths.append(Path(explicit_file).expanduser())

    repo_root = root
    candidate_paths.extend(
        [
            repo_root / ".env",
            repo_root / "config" / ".env",
            repo_root / "config" / "secrets.env",
            repo_root / "config" / "secrets.json",
            repo_root / "config" / "credentials.json",
        ]
    )

    home = Path.home()
    candidate_paths.extend(
        [
            home / ".allora" / "api_key",
            home / ".allora" / "credentials.json",
            home / ".allora_api_key",
        ]
    )

    xdg_config = os.getenv("XDG_CONFIG_HOME")
    if xdg_config:
        candidate_paths.append(Path(xdg_config) / "allora" / "api_key")

    found_key: Optional[str] = None
    inspected: List[Path] = []
    for path in candidate_paths:
        inspected.append(path)
        key = _extract_api_key_from_path(path)
        if key and key.strip():
            found_key = key.strip()
            break

    if found_key:
        env["ALLORA_API_KEY"] = found_key
        os.environ.setdefault("ALLORA_API_KEY", found_key)
    return found_key, inspected


def _infer_training_failure_status(log_excerpt: str) -> str:
    if not log_excerpt:
        return "train_error"
    text = log_excerpt.lower()
    if "allora_api_key" in text and "not found" in text:
        return "missing_api_key"
    if "module not found" in text and "train.py" not in text:
        return "missing_dependency"
    if "no module named" in text:
        return "missing_dependency"
    if "permission denied" in text:
        return "permission_denied"
    return "train_error"


def _load_prediction_value(root: Path) -> Optional[float]:
    pred_path = root / "data" / "artifacts" / "predictions.json"
    if not pred_path.exists():
        return None
    try:
        data = json.loads(pred_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    val = data.get("value") if isinstance(data, dict) else None
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _handle_failure(status_reason: Optional[str], attempt: int, env: Dict[str, str], root: Path, retry_delay: int) -> bool:
    if status_reason == "duplicate":
        return False
    if status_reason == "not_whitelisted":
        return False
    if status_reason == "sdk_error":
        return False
    if status_reason == "unfulfilled_nonces":
        _query_unfulfilled(root, env)
    if attempt >= MAX_AUTO_ATTEMPTS:
        return False
    if status_reason in {"cooldown", "unfulfilled_nonces", "not_rewardable"}:
        try:
            time.sleep(retry_delay)
        except KeyboardInterrupt:
            return False
        return True
    return False


def _append_manual_row_if_needed(csv_path: Path, expected_wallet: str) -> None:
    rows = _read_submission_rows(csv_path)
    if rows:
        last = rows[-1]
        wallet = last.get("wallet", "")
        if wallet and wallet != expected_wallet:
            new_row = {k: "null" for k in CANONICAL_SUBMISSION_HEADER}
            new_row.update(
                {
                    "timestamp_utc": _window_timestamp(),
                    "topic_id": str(DEFAULT_TOPIC_ID),
                    "wallet": expected_wallet,
                    "status": "wallet_mismatch_corrected",
                    "success": "false",
                    "exit_code": "0",
                }
            )
            log_submission_row(str(csv_path), new_row)
            normalize_submission_log_file(str(csv_path))


def run_workflow(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parent
    discovered_env = find_dotenv(usecwd=True) or str(root / ".env")
    if discovered_env:
        load_dotenv(discovered_env, override=False)
    env = os.environ.copy()
    env.setdefault("ALLORA_WALLET_ADDR", args.wallet or DEFAULT_WALLET_ADDR)
    env.setdefault("ALLORA_TOPIC_ID", str(DEFAULT_TOPIC_ID))
    expected_wallet = env["ALLORA_WALLET_ADDR"]

    csv_path = root / "submission_log.csv"
    ensure_submission_log_schema(str(csv_path))
    _append_manual_row_if_needed(csv_path, expected_wallet)

    api_key, inspected_paths = _ensure_api_key(env, root)
    if not api_key:
        inspected_str = ", ".join(str(p) for p in inspected_paths if str(p).strip()) or "(no fallback paths)"
        message_lines = [
            "Preflight check failed: ALLORA_API_KEY not found in environment.",
            f"Checked locations: {inspected_str}",
            "Populate .env or set ALLORA_API_KEY/ALLORA_API_KEY_FILE before rerunning.",
        ]
        manual_log = _write_manual_log("train", "\n".join(message_lines), root)
        value = _load_prediction_value(root)
        _log_training_failure(root, 1, value, status="missing_api_key_precheck")
        print("\n".join(message_lines), file=sys.stderr)
        print(f"See {manual_log} for details.", file=sys.stderr)
        return 1

    attempt = 0
    retry_delay = max(30, int(args.retry_delay or DEFAULT_RETRY_DELAY))
    while attempt < MAX_AUTO_ATTEMPTS:
        attempt += 1
        print(f"=== Attempt {attempt}/{MAX_AUTO_ATTEMPTS}: training ===")
        train_cmd = [sys.executable, "train.py"]
        train_result = _capture_step("train", train_cmd, root, env)
        if not train_result.ok():
            value = _load_prediction_value(root)
            status = _infer_training_failure_status(train_result.log_excerpt)
            _log_training_failure(root, train_result.returncode, value, status=status)
            if status == "missing_api_key":
                print(
                    "train.py aborted: ALLORA_API_KEY missing. Populate .env or export the key before rerunning.",
                    file=sys.stderr,
                )
                print(f"See {train_result.log_path} for full context.", file=sys.stderr)
            else:
                print(
                    f"train.py failed (rc={train_result.returncode}); see {train_result.log_path}",
                    file=sys.stderr,
                )
            return train_result.returncode

        prediction_value = _load_prediction_value(root)
        if prediction_value is None:
            print("ERROR: training completed but predictions.json is missing or invalid", file=sys.stderr)
            _log_training_failure(root, 1, None, status="prediction_missing")
            return 1

        print(f"Training completed; prediction value={prediction_value}")
        print(f"=== Attempt {attempt}/{MAX_AUTO_ATTEMPTS}: submission ===")
        submit_cmd = [
            sys.executable,
            "submit_prediction.py",
            "--topic-id",
            str(DEFAULT_TOPIC_ID),
            "--wallet",
            expected_wallet,
            "--timeout",
            str(int(args.submit_timeout)),
            "--retries",
            str(int(args.submit_retries)),
        ]
        submit_result = _capture_step("submit", submit_cmd, root, env)
        if not submit_result.ok():
            print(f"submit_prediction.py exited with rc={submit_result.returncode}; see {submit_result.log_path}")

        rows = _read_submission_rows(csv_path)
        success_row: Optional[Dict[str, str]] = rows[-1] if rows else None
        success, status = _parse_status(success_row)
        if success:
            print("Submission succeeded; workflow complete")
            return 0

        reason = _status_reason(status)
        print(f"Submission unsuccessful (status={status}); reason={reason}")
        should_retry = _handle_failure(reason, attempt, env, root, retry_delay)
        if not should_retry:
            return submit_result.returncode if submit_result.returncode else 1
    return 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run training and submission sequentially with logging and retries")
    parser.add_argument("--wallet", default=DEFAULT_WALLET_ADDR, help="Wallet address to use for submissions")
    parser.add_argument("--submit-timeout", type=int, default=60, help="Timeout passed to submit_prediction.py")
    parser.add_argument("--submit-retries", type=int, default=3, help="Retry count passed to submit_prediction.py")
    parser.add_argument(
        "--retry-delay",
        type=int,
        default=DEFAULT_RETRY_DELAY,
        help="Seconds to wait before retrying after recoverable submission failures",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return run_workflow(args)
    except KeyboardInterrupt:
        print("Workflow interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
