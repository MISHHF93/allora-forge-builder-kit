import os
import sys
import shutil
from datetime import datetime, timezone
import re
from typing import Any, cast
from dotenv import load_dotenv

load_dotenv()

# Wallet rotation resolver using SDK worker for address resolution.
# Strategy:
# 1) Try existing .allora_key by constructing a minimal AlloraWorker and reading its wallet address.
# 2) If that fails and .allora_key_bak exists, copy backup over .allora_key (non-destructive backup of original if present),
#    then resolve again. Persist this copy so subsequent submissions use the fallback wallet.
# 3) Print the resolved address to stdout. Also write .active_wallet_path with the source path used.

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PRIMARY = os.path.join(ROOT, ".allora_key")
BACKUP = os.path.join(ROOT, ".allora_key_bak")
MARKER = os.path.join(ROOT, ".active_wallet_path")
MNEMONIC_CANDIDATES = [
    os.path.join(ROOT, "allora-mnemonic.txt"),
    os.path.join(ROOT, ".allora_mnemonic"),
]


def _print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _print_info(msg: str) -> None:
    print(msg)


def _print_warn(msg: str) -> None:
    # Route warnings to stdout to avoid PowerShell "NativeCommandError" banners
    print(msg)


def _resolve_addr_via_worker() -> str | None:
    try:
        from allora_sdk.worker import AlloraWorker  # type: ignore[import-not-found]
    except ImportError as e:
        _print_err(f"ERROR: please install allora-sdk (pip install allora-sdk) - {e}")
        return None
    try:
        # Minimal run fn per SDK signature
        def _dummy(_: int) -> float:
            return 0.0
        w = AlloraWorker(run=_dummy, api_key=os.getenv("ALLORA_API_KEY", ""), topic_id=67)
        for attr in ("wallet_address", "address", "wallet"):
            try:
                val = getattr(w, attr, None)
                # Direct string
                if isinstance(val, str) and val.startswith("allo"):
                    return val
                # Dict container
                if isinstance(val, dict):
                    v = cast(dict[str, Any], val).get("address")
                    if isinstance(v, str) and v.startswith("allo"):
                        return v
                # Object with address property
                v2 = getattr(val, "address", None)  # type: ignore[attr-defined]
                if isinstance(v2, str) and v2.startswith("allo"):
                    return v2
                v3 = getattr(val, "bech32_address", None)  # type: ignore[attr-defined]
                if isinstance(v3, str) and v3.startswith("allo"):
                    return v3
            except AttributeError:
                continue
        return None
    except (RuntimeError, ValueError) as e:
        _print_warn(f"WARN: AlloraWorker failed to resolve wallet: {e}")
        return None


def _safe_copy(src: str, dst: str) -> None:
    try:
        if os.path.exists(dst):
            # Backup existing primary once
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            bkp = dst + f".orig.{ts}"
            try:
                shutil.copy2(dst, bkp)
            except (OSError, IOError):
                pass
        shutil.copy2(src, dst)
    except (OSError, IOError) as e:
        _print_err(f"ERROR: failed to copy {src} -> {dst}: {e}")


def _write_marker(path_used: str) -> None:
    try:
        with open(MARKER, "w", encoding="utf-8") as f:
            f.write(path_used)
    except (OSError, IOError):
        pass


def _fallback_via_printer() -> str | None:
    """Invoke tools/print_wallet_address.py and parse an allo... address from stdout."""
    try:
        import subprocess
        script = os.path.join(ROOT, "tools", "print_wallet_address.py")
        if not os.path.exists(script):
            return None
        proc = subprocess.run([sys.executable, "-u", script], capture_output=True, text=True, check=False)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        # Look for a full bech32-like address
        m = re.search(r"(allo[0-9a-z]{10,})", out)
        if m:
            return m.group(0)
    except (OSError, IOError):
        return None
    return None


def main() -> int:
    # 1) If a mnemonic candidate file exists, promote it to primary and try
    for cand in MNEMONIC_CANDIDATES:
        if os.path.exists(cand):
            _safe_copy(cand, PRIMARY)
            addr_m = _resolve_addr_via_worker() or _fallback_via_printer()
            if addr_m and addr_m.startswith("allo"):
                _write_marker(os.path.basename(cand))
                print(addr_m)
                return 0

    # 1b) Otherwise, try with current primary as-is
    addr = _resolve_addr_via_worker() or _fallback_via_printer()
    if addr and addr.startswith("allo"):
        _write_marker(".allora_key")
        print(addr)
        return 0

    # 2) Fallback: if backup exists, copy it into primary and retry
    if os.path.exists(BACKUP):
        _safe_copy(BACKUP, PRIMARY)
        addr2 = _resolve_addr_via_worker() or _fallback_via_printer()
        if addr2 and addr2.startswith("allo"):
            _write_marker(".allora_key_bak")
            print(addr2)
            return 0

    _print_err("ERROR: Unable to resolve wallet from .allora_key or .allora_key_bak")
    return 1


if __name__ == "__main__":
    sys.exit(main())
