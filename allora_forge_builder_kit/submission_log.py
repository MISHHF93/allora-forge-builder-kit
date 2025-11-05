from __future__ import annotations

import csv
import os
from typing import Any, Dict, Iterable, List, Callable, Optional
import re
import time
import numpy as np

def _lock_path(path: str) -> str:
    return f"{path}.lock"

def _acquire_lock(path: str, timeout_s: float = 5.0, poll_s: float = 0.05) -> Optional[int]:
    """Acquire an exclusive lock via atomic lock-file creation. Returns fd or None on failure."""
    lock = _lock_path(path)
    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            # Write pid for debugging (best-effort)
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            except Exception:
                pass
            return fd
        except FileNotFoundError:
            # Parent dir may not exist yet; ensure it exists for lock file
            try:
                os.makedirs(os.path.dirname(lock) or ".", exist_ok=True)
            except Exception:
                pass
        except FileExistsError:
            time.sleep(poll_s)
        except Exception:
            # On unexpected error, do not block pipeline
            return None
    return None

def _release_lock(path: str, fd: Optional[int]) -> None:
    lock = _lock_path(path)
    try:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if os.path.exists(lock):
            os.unlink(lock)
    except Exception:
        pass

def _atomic_write(path: str, write_rows: Callable[[Any], None]) -> None:
    """Write to a temporary file then atomically replace the target."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        write_rows(fh)
    os.replace(tmp, path)

# Canonical 12-column schema in fixed order
CANONICAL_SUBMISSION_HEADER: List[str] = [
    "timestamp_utc",
    "topic_id",
    "value",
    "wallet",
    "nonce",
    "tx_hash",
    "success",
    "exit_code",
    "status",
    "log10_loss",
    "score",
    "reward",
]


def _normalize_cell(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v).strip()
    if s == "":
        return "null"
    # Normalize non-finite numeric tokens to null
    low = s.lower()
    if low in ("nan", "inf", "+inf", "infinity", "+infinity", "-inf", "-infinity"):
        return "null"
    
    # For numeric values, ensure consistent formatting
    try:
        # Check if it's an integer first
        if '.' not in s and 'e' not in low:
            int_val = int(s)
            return str(int_val)  # Return as integer string
        
        float_val = float(s)
        if np.isfinite(float_val):
            # Check if it's actually an integer value
            if float_val.is_integer():
                return str(int(float_val))
            # Format with appropriate precision based on magnitude
            elif abs(float_val) < 1e-10:
                return "0"
            elif abs(float_val) >= 1e6:
                return f"{float_val:.6e}"  # Scientific notation for very large numbers
            elif abs(float_val) >= 1:
                return f"{float_val:.6f}".rstrip('0').rstrip('.')  # Remove trailing zeros
            else:
                return f"{float_val:.12f}".rstrip('0').rstrip('.')  # Higher precision for small numbers
        return "null"
    except (ValueError, TypeError):
        pass
    
    return s


def ensure_submission_log_schema(path: str) -> None:
    """Ensure the CSV file exists and the header matches exactly the canonical schema.
    If file exists with a different header, rewrite the header and preserve data rows (best effort).
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.exists(path):
        # Initial create with header using atomic write
        _atomic_write(path, lambda fh: csv.writer(fh).writerow(CANONICAL_SUBMISSION_HEADER))
        return
    # If exists, verify header
    try:
        with open(path, "r", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        if not rows:
            _atomic_write(path, lambda fh: csv.writer(fh).writerow(CANONICAL_SUBMISSION_HEADER))
            return
        header = rows[0]
        if header != CANONICAL_SUBMISSION_HEADER:
            # Rewrite header, keep remaining rows normalized
            cleaned = [CANONICAL_SUBMISSION_HEADER]
            for r in rows[1:]:
                cleaned.append(_normalize_row_fixed(r))
            _atomic_write(path, lambda fh: csv.writer(fh).writerows(cleaned))
    except Exception:
        # On any read/parse error, reset file to just the header
        _atomic_write(path, lambda fh: csv.writer(fh).writerow(CANONICAL_SUBMISSION_HEADER))


def _normalize_row_fixed(row: Iterable[Any]) -> List[str]:
    r = [_normalize_cell(v) for v in row]
    # Trim/pad to exact number of columns
    n = len(CANONICAL_SUBMISSION_HEADER)
    if len(r) > n:
        r = r[:n]
    elif len(r) < n:
        r.extend(["null"] * (n - len(r)))
    return r


def normalize_submission_log_file(path: str) -> None:
    """Normalize all rows to the canonical width and cell forms (true/false/null).
    Keeps first header row; removes duplicate header lines in the body.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        # Strict UTC hourly cadence: only keep rows whose timestamp_utc is top-of-hour (..:00:00Z)
        def _is_top_of_hour(ts: str) -> bool:
            # Accept exactly: YYYY-MM-DDTHH:00:00Z
            return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:00:00Z$", ts or ""))

        cleaned: List[List[str]] = [CANONICAL_SUBMISSION_HEADER]
        for r in rows[1:]:
            if r == CANONICAL_SUBMISSION_HEADER:
                continue
            norm = _normalize_row_fixed(r)
            # Filter out non-top-of-hour timestamps to enforce strict cadence
            try:
                ts = norm[0]
            except Exception:
                ts = None
            if ts and _is_top_of_hour(str(ts)):
                cleaned.append(norm)
        _atomic_write(path, lambda fh: csv.writer(fh).writerows(cleaned))
    except Exception:
        # Best-effort: reset file with just the header
        _atomic_write(path, lambda fh: csv.writer(fh).writerow(CANONICAL_SUBMISSION_HEADER))


def dedupe_submission_log_file(path: str) -> None:
    """Dedupe rows with a per-window policy and keep a single header.
    Policy:
      - Group by (timestamp_utc, topic_id)
      - Prefer rows with success == true; if multiple, keep the last occurrence
      - Otherwise keep the last occurrence in file order
    Also removes identical duplicate lines.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return
        header = rows[0]
        data = [r for r in rows[1:] if r and r != CANONICAL_SUBMISSION_HEADER]

        # Normalize rows and build groups
        norm_rows: List[List[str]] = [_normalize_row_fixed(r) for r in data]
        groups: Dict[tuple, List[List[str]]] = {}
        for r in norm_rows:
            try:
                ts = r[0]
                topic = r[1]
                key = (ts, topic)
                groups.setdefault(key, []).append(r)
            except Exception:
                # If row malformed, drop it
                continue

        # Select best row per group according to policy
        selected: List[List[str]] = []
        for key, rows_in_key in groups.items():
            # Prefer success == true
            success_rows = [r for r in rows_in_key if (len(r) >= 7 and str(r[6]).lower() == "true")]
            if success_rows:
                chosen = success_rows[-1]
            else:
                chosen = rows_in_key[-1]
            selected.append(chosen)

        # Sort by timestamp then topic for stable output (optional)
        try:
            def _sort_key(r: List[str]):
                return (r[0], int(r[1]))
            selected.sort(key=_sort_key)
        except Exception:
            pass

        out: List[List[str]] = [CANONICAL_SUBMISSION_HEADER] + selected
        _atomic_write(path, lambda fh: csv.writer(fh).writerows(out))
    except Exception:
        pass


def log_submission_row(path: str, row: Dict[str, Any]) -> None:
    """Write a submission row, replacing any existing entry for the same epoch/topic."""

    ensure_submission_log_schema(path)
    ordered = [_normalize_cell(row.get(k)) for k in CANONICAL_SUBMISSION_HEADER]
    key_indices = (
        CANONICAL_SUBMISSION_HEADER.index("timestamp_utc"),
        CANONICAL_SUBMISSION_HEADER.index("topic_id"),
    )
    key = tuple(ordered[idx] for idx in key_indices)

    fd = _acquire_lock(path, timeout_s=5.0)
    try:
        try:
            with open(path, "r", newline="", encoding="utf-8") as fh:
                reader = list(csv.reader(fh))
        except FileNotFoundError:
            reader = []
        except Exception:
            reader = []

        if not reader:
            current_rows: List[List[str]] = [CANONICAL_SUBMISSION_HEADER]
        else:
            header = reader[0]
            current_rows = [CANONICAL_SUBMISSION_HEADER]
            for existing in reader[1:]:
                if existing == CANONICAL_SUBMISSION_HEADER:
                    continue
                current_rows.append(_normalize_row_fixed(existing))

        updated_body: List[List[str]] = []
        replaced = False
        for existing in current_rows[1:]:
            try:
                existing_key = tuple(existing[idx] for idx in key_indices)
            except Exception:
                existing_key = None
            if existing_key == key:
                if not replaced:
                    updated_body.append(ordered)
                    replaced = True
                else:
                    continue
            else:
                updated_body.append(existing)

        if not replaced:
            updated_body.append(ordered)

        _atomic_write(
            path,
            lambda fh: csv.writer(fh).writerows(
                [CANONICAL_SUBMISSION_HEADER] + updated_body
            ),
        )
    finally:
        _release_lock(path, fd)
