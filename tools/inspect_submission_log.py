#!/usr/bin/env python
import argparse
import os
import sys
from typing import List

try:
    import pandas as pd
except Exception as e:
    print(f"[ERROR] pandas is required to run this tool: {e}")
    sys.exit(2)

CANONICAL_HEADER: List[str] = [
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect and validate submission_log.csv schema and recent rows")
    ap.add_argument("path", nargs="?", default="submission_log.csv", help="Path to the submission log CSV (default: submission_log.csv)")
    ap.add_argument("--tail", type=int, default=3, help="Show last N rows (default: 3)")
    args = ap.parse_args()

    path = args.path
    print(f"CSV exists: {os.path.exists(path)} -> {os.path.abspath(path)}")
    if not os.path.exists(path):
        print("No CSV found")
        return 0

    try:
        df = pd.read_csv(path)
    except Exception as e:
        print(f"[ERROR] Failed to read CSV: {e}")
        return 2

    cols = list(df.columns)
    print(f"Columns (count={len(cols)}):")
    print(cols)

    # Schema check
    ok = cols == CANONICAL_HEADER
    if ok:
        print("Schema: PASS (exact 12-column canonical header)")
    else:
        print("Schema: FAIL (header mismatch)")
        # Show diff hints
        expected = set(CANONICAL_HEADER)
        actual = set(cols)
        missing = list(expected - actual)
        extra = list(actual - expected)
        order_ok = [c1 == c2 for c1, c2 in zip(CANONICAL_HEADER, cols)]
        first_misordered = next((i for i, v in enumerate(order_ok) if not v), None)
        if missing:
            print(f" - Missing: {missing}")
        if extra:
            print(f" - Extra: {extra}")
        if first_misordered is not None:
            print(f" - First out-of-order index: {first_misordered} (expected '{CANONICAL_HEADER[first_misordered]}', got '{cols[first_misordered]}')")

    # Tail rows
    n = max(1, int(args.tail))
    print(f"\nLast {n} rows:")
    try:
        print(df.tail(n).to_string(index=False))
    except Exception:
        # Fallback safe print
        for _, row in df.tail(n).iterrows():
            print(", ".join(str(row.get(k)) for k in CANONICAL_HEADER if k in df.columns))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
