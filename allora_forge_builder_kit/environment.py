"""Environment handling helpers for the builder pipeline."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import find_dotenv, load_dotenv

__all__ = [
    "load_environment",
    "resolve_env_path",
    "load_last_nonce",
    "write_last_nonce",
    "require_api_key",
    "warn_on_suspect_api_key",
]

_ALLORA_KEY_PATTERN = re.compile(r"^UP-[A-Za-z0-9]{8,}")
_TIINGO_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)


def resolve_env_path(root: Path) -> Path:
    """Locate the most specific ``.env`` file for the repository."""

    explicit = root / ".env"
    if explicit.exists():
        return explicit
    discovered = find_dotenv(str(explicit), usecwd=True)
    if discovered:
        return Path(discovered)
    return explicit


def load_environment(root: Path, override: bool = False) -> None:
    """Load environment variables from ``.env`` if present."""

    env_path = resolve_env_path(root)
    if env_path.exists():
        load_dotenv(env_path, override=override)

    # Load mnemonic from .allora_key if present
    allora_key_path = root / ".allora_key"
    if allora_key_path.exists():
        try:
            mnemonic = allora_key_path.read_text(encoding="utf-8").strip()
            if mnemonic and not os.getenv("ALLORA_MNEMONIC"):
                os.environ["ALLORA_MNEMONIC"] = mnemonic
        except OSError:
            pass  # Ignore file read errors

    # Normalise builder specific variable names for the SDK
    _promote_env("ALLORA_API_KEY", "ALLORA_API_KEY")
    _promote_env("ALLORA_WALLET_ADDR", "ALLORA_WALLET_ADDR")
    _promote_env("ALLORA_MNEMONIC", "MNEMONIC")
    _promote_env("ALLORA_MNEMONIC_FILE", "MNEMONIC_FILE")
    _promote_env("ALLORA_PRIVATE_KEY", "PRIVATE_KEY")


def _promote_env(source: str, target: str) -> None:
    value = os.getenv(source)
    if value and not os.getenv(target):
        os.environ[target] = value


def load_last_nonce(root: Path) -> Optional[Dict[str, Any]]:
    path = root / ".last_nonce.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_last_nonce(root: Path, payload: Dict[str, Any]) -> None:
    path = root / ".last_nonce.json"
    try:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        # Do not crash the pipeline on bookkeeping issues
        pass


def require_api_key() -> str:
    key = os.getenv("ALLORA_API_KEY", "").strip()
    if not key:
        warn_on_suspect_api_key(key)
        raise RuntimeError("ALLORA_API_KEY is not set. Add it to .env or the environment.")
    warn_on_suspect_api_key(key)
    return key


def warn_on_suspect_api_key(key: str) -> None:
    """Emit a warning when the configured key is missing or malformed."""

    if not key:
        print("Warning: ALLORA_API_KEY is missing; OHLCV fetches will fall back to offline data only.", file=sys.stderr)
        return

    if _TIINGO_KEY_PATTERN.match(key):
        print(
            "Warning: ALLORA_API_KEY looks like a Tiingo token. Set TIINGO_API_KEY for Tiingo and use a valid Allora key for"
            " market data.",
            file=sys.stderr,
        )
    elif not _ALLORA_KEY_PATTERN.match(key):
        print(
            "Warning: ALLORA_API_KEY does not match the expected 'UP-' Allora format. Double-check the key in your .env.",
            file=sys.stderr,
        )
