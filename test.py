"""Utility test harness for the Allora Topic 67 training pipeline.

This script provides a fast, repeatable way to exercise ``train.py`` before
making on-chain submissions.  It intentionally prefers offline execution so
that contributors can validate the forecasting stack—even in air-gapped
environments—while still allowing online runs when desired.

Typical usage::

    # Run a single offline integration test with deterministic time bounds
    python test.py

    # Repeat the run three times and keep the generated artifacts between runs
    python test.py --iterations 3 --keep-artifacts

    # Allow the pipeline to fetch live data instead of synthesized fixtures
    python test.py --online

Command-line options mirror the key ``train.py`` arguments so we can stress the
pipeline with different horizons or from-month anchors.  By default the test
patches ``AlloraMLWorkflow`` to rely on local fixtures or synthetic OHLCV data,
allowing the XGBoost-only architecture to train end-to-end without network
access.  After each iteration the script asserts that the critical competition
artifacts are produced and that the submission log retains the required
12-column schema.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence

import pandas as pd
from allora_forge_builder_kit.submission_log import CANONICAL_SUBMISSION_HEADER


ROOT_DIR = Path(__file__).resolve().parent
ARTIFACT_DIR = ROOT_DIR / "data" / "artifacts"
MODELS_DIR = ROOT_DIR / "models"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"
PREDICTIONS_PATH = ARTIFACT_DIR / "predictions.json"
MODEL_PATH = MODELS_DIR / "xgb_model.pkl"
SUBMISSION_LOG_PATH = ROOT_DIR / "submission_log.csv"

# Sensible defaults that keep runtimes short while touching the full pipeline.
DEFAULT_FROM_MONTH = "2025-01"
DEFAULT_START_UTC = "2025-01-01T00:00:00Z"
DEFAULT_END_UTC = "2025-06-10T00:00:00Z"
DEFAULT_AS_OF = "2025-06-03T00:00:00Z"


def ensure_api_key(*, offline: bool) -> None:
    """Ensure API credentials are configured for the requested mode."""

    if offline:
        if not os.getenv("ALLORA_API_KEY"):
            # Any non-empty token is acceptable for offline fallback mode.
            os.environ["ALLORA_API_KEY"] = "offline-test-key"
        return

    if not os.getenv("ALLORA_API_KEY"):
        raise RuntimeError(
            "ALLORA_API_KEY is required for online tests.\n"
            "Please export your real Allora API token, e.g.\n"
            "  export ALLORA_API_KEY=\"YOUR_REAL_ALLORA_KEY\""
        )

    if "TIINGO" in os.getenv("DATA_PROVIDER", "").upper() and not os.getenv("TIINGO_API_KEY"):
        raise RuntimeError(
            "TIINGO_API_KEY is required when DATA_PROVIDER requests Tiingo.\n"
            "Set it via\n  export TIINGO_API_KEY=\"YOUR_TIINGO_KEY\""
        )


def cleanup_artifacts(paths: Iterable[Path]) -> None:
    """Remove stale artifacts so each iteration starts from a clean slate."""

    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue


@contextmanager
def force_offline_execution(enabled: bool) -> Iterator[None]:
    """Patch workflow fetchers so tests never rely on network access."""

    if not enabled:
        yield
        return

    from unittest import mock
    from allora_forge_builder_kit.workflow import AlloraMLWorkflow

    def _offline_fetch(self, ticker: str, from_date: str, *_, **__) -> pd.DataFrame:
        return self._offline_ohlcv_from_local(ticker, from_date)

    patches = [
        mock.patch.object(AlloraMLWorkflow, "fetch_ohlcv_data", _offline_fetch),
        mock.patch.object(AlloraMLWorkflow, "fetch_ohlcv_data_tiingo", _offline_fetch),
        mock.patch.object(AlloraMLWorkflow, "list_ready_buckets", return_value=[]),
    ]

    with contextlib_exitstack(patches):
        yield


@contextmanager
def contextlib_exitstack(patches: Sequence[object]) -> Iterator[None]:
    """Minimal stand-in for ``contextlib.ExitStack`` without extra imports."""

    patch_stack = list(patches)
    try:
        for patch in patch_stack:
            patch.__enter__()
        yield
    finally:
        while patch_stack:
            patch_stack.pop().__exit__(None, None, None)


def invoke_train(train_args: Sequence[str]) -> int:
    """Execute ``train.main`` with temporary ``sys.argv`` overrides."""

    import importlib

    train_module = importlib.import_module("train")
    argv_backup = list(sys.argv)
    sys.argv = ["train.py", *train_args]
    try:
        return train_module.main()
    finally:
        sys.argv = argv_backup


def verify_artifact(path: Path) -> None:
    if not path.exists():
        raise AssertionError(f"Expected artifact missing: {path}")
    if path.stat().st_size <= 0:
        raise AssertionError(f"Artifact is empty: {path}")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def assert_submission_log_schema() -> None:
    if not SUBMISSION_LOG_PATH.exists():
        raise AssertionError("submission_log.csv was not created by train.py")
    with SUBMISSION_LOG_PATH.open("r", encoding="utf-8") as handle:
        header_line = handle.readline().strip()
    header = [column.strip() for column in header_line.split(",") if column]
    if header != CANONICAL_SUBMISSION_HEADER:
        raise AssertionError(
            "submission_log.csv header mismatch.\n"
            f"  expected: {CANONICAL_SUBMISSION_HEADER}\n"
            f"  observed: {header}"
        )


def run_iteration(
    train_args: Sequence[str], *, offline: bool, keep_artifacts: bool, expect_submission: bool
) -> None:
    expect_submission = expect_submission or any(arg == "--submit" for arg in train_args)
    ensure_api_key(offline=offline)
    if not keep_artifacts:
        cleanup_artifacts([METRICS_PATH, PREDICTIONS_PATH, MODEL_PATH])

    with force_offline_execution(offline):
        exit_code = invoke_train(train_args)

    if exit_code != 0:
        raise AssertionError(f"train.py exited with non-zero status {exit_code}")

    verify_artifact(METRICS_PATH)
    verify_artifact(PREDICTIONS_PATH)
    verify_artifact(MODEL_PATH)

    metrics = load_json(METRICS_PATH)
    preds = load_json(PREDICTIONS_PATH)

    if "log10_loss" not in metrics:
        raise AssertionError("metrics.json missing 'log10_loss'")
    if "topic_id" not in preds or "value" not in preds:
        raise AssertionError("predictions.json missing required keys")

    assert_submission_log_schema()

    if expect_submission:
        df = pd.read_csv(SUBMISSION_LOG_PATH)
        if df.empty:
            raise AssertionError("Expected a submission_log.csv row when --submit is used")
        last = df.iloc[-1]
        status = str(last.get("status", ""))
        success_flag = bool(last.get("success", False))
        if not success_flag and status != "skipped_topic_not_ready":
            raise AssertionError(
                "Submission status mismatch. Expected 'skipped_topic_not_ready' for skipped submissions,"
                f" observed '{status}'."
            )

    print(
        "[OK] iteration complete — log10_loss={} topic_id={} value={}".format(
            metrics.get("log10_loss"), preds.get("topic_id"), preds.get("value")
        )
    )


def build_train_args(args: argparse.Namespace) -> List[str]:
    train_args: List[str] = [
        "--from-month",
        args.from_month,
        "--start-utc",
        args.start_utc,
        "--end-utc",
        args.end_utc,
        "--as-of",
        args.as_of,
    ]
    if args.submit:
        train_args.append("--submit")
    if args.extra_train_args:
        train_args.extend(args.extra_train_args)
    return train_args


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test harness for train.py")
    parser.add_argument("--iterations", type=int, default=1, help="Number of times to run train.py")
    parser.add_argument("--from-month", default=DEFAULT_FROM_MONTH, help="Forwarded to train.py --from-month")
    parser.add_argument("--start-utc", default=DEFAULT_START_UTC, help="Forwarded to train.py --start-utc")
    parser.add_argument("--end-utc", default=DEFAULT_END_UTC, help="Forwarded to train.py --end-utc")
    parser.add_argument("--as-of", default=DEFAULT_AS_OF, help="Forwarded to train.py --as-of")
    parser.add_argument("--online", action="store_true", help="Allow network fetches instead of synthetic data")
    parser.add_argument("--keep-artifacts", action="store_true", help="Do not delete artifacts before each run")
    parser.add_argument("--submit", action="store_true", help="Invoke train.py with --submit for submission flow testing")
    parser.add_argument(
        "extra_train_args",
        nargs=argparse.REMAINDER,
        help="Additional raw arguments forwarded to train.py (precede with --)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    train_args = build_train_args(args)
    offline = not args.online
    for idx in range(1, args.iterations + 1):
        print(f"[INFO] Starting iteration {idx}/{args.iterations} (offline={offline})")
        run_iteration(
            train_args,
            offline=offline,
            keep_artifacts=args.keep_artifacts,
            expect_submission=args.submit,
        )
    print("[INFO] All iterations completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
