import csv
import os
from typing import List, Tuple

# Resolve header from shared module if available; otherwise use local fallback
HEADER: List[str]
try:
    from allora_forge_builder_kit.submission_log import CANONICAL_SUBMISSION_HEADER as _SHARED_HEADER
    HEADER = list(_SHARED_HEADER)
except Exception:
    HEADER = [
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


def normalize_row(row: List[str], ncols: int) -> Tuple[List[str], int]:
    """Ensure row has exactly ncols entries.
    - Pad missing cells with 'null'
    - Truncate extras
    - Normalize empty strings to 'null'
    Returns (normalized_row, fixes_count)
    """
    fixes = 0
    r = list(row)
    # Trim extras
    if len(r) > ncols:
        r = r[:ncols]
        fixes += 1
    # Pad missing
    if len(r) < ncols:
        r.extend(["null"] * (ncols - len(r)))
        fixes += 1
    # Normalize empties
    for i, v in enumerate(r):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            r[i] = "null"
            fixes += 1
    return r, fixes


def validate_and_repair(path: str) -> None:
    if not os.path.exists(path):
        print(f"No file at {path}")
        return

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    # Remove any duplicate header occurrences inside data
    cleaned: List[List[str]] = []
    dup_header_count = 0
    if not rows:
        rows = [HEADER]
    else:
        # Ensure first row is the correct header
        first = rows[0]
        if first != HEADER:
            # Replace with correct header
            cleaned.append(HEADER)
        else:
            cleaned.append(first)

    fixes_total = 0
    seen: set = set()
    duplicate_rows = 0
    for idx, row in enumerate(rows[1:], start=2):
        if row == HEADER:
            dup_header_count += 1
            continue
        norm, fixes = normalize_row(row, len(HEADER))
        fixes_total += fixes
        key = tuple(norm)
        if key in seen:
            duplicate_rows += 1
            continue
        seen.add(key)
        cleaned.append(norm)

    # Write back
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerows(cleaned)

    print("submission_log.csv validation summary:")
    print(f"  Header OK: {cleaned[0] == HEADER}")
    print(f"  Rows written (including header): {len(cleaned)}")
    print(f"  Duplicate header lines removed: {dup_header_count}")
    print(f"  Data duplicate rows removed: {duplicate_rows}")
    print(f"  Cell fixes applied (pad/trim/normalize): {fixes_total}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(here, "submission_log.csv")
    validate_and_repair(csv_path)
