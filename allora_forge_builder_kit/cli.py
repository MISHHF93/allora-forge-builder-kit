from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from .logging_utils import get_stage_logger
from .pipeline import Pipeline
from .submission import SubmissionResult


def _parse_when(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = pd.to_datetime(value, utc=True)
    if not isinstance(dt, pd.Timestamp):
        raise ValueError(f"Cannot parse datetime value: {value}")
    return dt.to_pydatetime()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Allora builder kit pipeline")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent, help="Repository root")

    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="Run feature generation and training")
    train_parser.add_argument("--when", help="Override inference timestamp (ISO8601)")
    train_parser.add_argument("--submit", action="store_true", help="Submit immediately after training")

    submit_parser = subparsers.add_parser("submit", help="Submit an existing prediction artifact")
    submit_parser.add_argument("--artifact", type=Path, help="Path to prediction artifact")
    submit_parser.add_argument("--topic-id", type=int, help="Override topic id")
    submit_parser.add_argument("--timeout", type=int, help="Submission timeout in seconds")
    submit_parser.add_argument("--retries", type=int, help="Maximum submission retries")

    tas_parser = subparsers.add_parser("train-and-submit", help="Run training followed by submission")
    tas_parser.add_argument("--when", help="Override inference timestamp (ISO8601)")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    pipeline = Pipeline.from_repo_root(args.root)

    if args.command == "train":
        result = pipeline.run_training(_parse_when(args.when))
        logger = get_stage_logger("train")
        logger.info("Training complete. Prediction %.6f for %s", result.prediction_value, result.prediction_time)
        if args.submit:
            submit_result = pipeline.run_submission()
            _emit_submission_summary(submit_result)
        return 0

    if args.command == "submit":
        result = pipeline.run_submission(
            artifact_path=args.artifact,
            topic_id=args.topic_id,
            timeout=args.timeout,
            retries=args.retries,
        )
        _emit_submission_summary(result)
        return 0 if result.success else 1

    if args.command == "train-and-submit":
        result = pipeline.train_and_submit(_parse_when(args.when))
        _emit_submission_summary(result)
        return 0 if result.success else 1

    parser.error("Unknown command")
    return 1


def _emit_submission_summary(result: SubmissionResult) -> None:
    logger = get_stage_logger("submit")
    if result.success:
        logger.info("Submission succeeded (tx=%s nonce=%s)", result.tx_hash, result.nonce)
    else:
        logger.error("Submission failed: %s", result.status)


if __name__ == "__main__":
    raise SystemExit(main())
