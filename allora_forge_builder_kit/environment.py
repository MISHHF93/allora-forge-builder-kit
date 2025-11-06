"""Environment handling helpers for the builder pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import find_dotenv, load_dotenv

__all__ = [
    "load_environment",
    "resolve_env_path",
    "load_last_nonce",
    "write_last_nonce",
    "require_api_key",
]


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
        raise RuntimeError("ALLORA_API_KEY is not set. Add it to .env or the environment.")
    return key
