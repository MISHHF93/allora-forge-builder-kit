"""Centralised logging helpers for the training/submission pipeline."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict

_LOGGER_NAME = "allora_pipeline"
_STAGE_HANDLERS: Dict[str, RotatingFileHandler] = {}
_LOG_DIR: Path | None = None


def initialise_logging(root: Path, max_bytes: int = 5_000_000, backups: int = 5) -> None:
    """Configure the shared pipeline logger.

    Parameters
    ----------
    root:
        Repository root used to place ``data/artifacts/logs``.
    max_bytes:
        Maximum number of bytes to keep per log file before rotation.
    backups:
        Number of rotated log files to retain per handler.
    """

    global _LOG_DIR  # noqa: PLW0603 - module level cache on purpose

    log_dir = root / "data" / "artifacts" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_DIR = log_dir

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Reset existing handlers so that repeated invocations (e.g. unit tests) do not duplicate output
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    pipeline_file = log_dir / "pipeline.log"
    file_handler = RotatingFileHandler(pipeline_file, maxBytes=max_bytes, backupCount=backups)
    file_handler.setFormatter(_formatter())

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_formatter(include_name=False))

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.debug("Pipeline logging initialised at %s", pipeline_file)


def _formatter(include_name: bool = True) -> logging.Formatter:
    fmt = "%(asctime)sZ %(levelname)s"
    if include_name:
        fmt += " [%(name)s]"
    fmt += " %(message)s"
    return logging.Formatter(fmt=fmt, datefmt="%Y-%m-%dT%H:%M:%S")


def get_stage_logger(stage: str) -> logging.Logger:
    """Return a stage specific logger that writes into ``data/artifacts/logs``.

    The returned logger propagates into the shared pipeline logger so a single
    call emits both the stage log file and the aggregated ``pipeline.log``.
    """

    if _LOG_DIR is None:
        raise RuntimeError("Logging has not been initialised. Call initialise_logging() first.")

    stage_key = stage.strip().lower() or "general"
    logger = logging.getLogger(f"{_LOGGER_NAME}.{stage_key}")
    logger.setLevel(logging.INFO)
    logger.propagate = True

    if stage_key not in _STAGE_HANDLERS:
        log_path = _LOG_DIR / f"{stage_key}.log"
        handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3)
        handler.setFormatter(_formatter())
        logger.addHandler(handler)
        _STAGE_HANDLERS[stage_key] = handler

    return logger
