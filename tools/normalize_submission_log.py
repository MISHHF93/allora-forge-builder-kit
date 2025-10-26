import os
from allora_forge_builder_kit.submission_log import (
    ensure_submission_log_schema,
    normalize_submission_log_file,
    dedupe_submission_log_file,
)


def main() -> int:
    root = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(os.path.dirname(root), "submission_log.csv")
    ensure_submission_log_schema(csv_path)
    normalize_submission_log_file(csv_path)
    dedupe_submission_log_file(csv_path)
    print(f"normalized: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
