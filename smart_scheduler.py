#!/usr/bin/env python3
"""Scheduler that aligns submissions with on-chain inference windows."""

from __future__ import annotations

import os
import time
from pathlib import Path

from pipeline_utils import setup_logging
import submit_prediction

LOG_FILE = Path("logs/scheduler.log")


def run_loop():
    logger = setup_logging("scheduler", log_file=LOG_FILE)
    delay_ok = int(os.getenv("SUBMISSION_OK_SLEEP", "900"))  # 15 minutes
    delay_blocked = int(os.getenv("SUBMISSION_BLOCKED_SLEEP", "600"))  # 10 minutes
    logger.info("Smart scheduler started with ok_sleep=%ss blocked_sleep=%ss", delay_ok, delay_blocked)

    while True:
        result = submit_prediction.main()
        if result == 0:
            logger.info("Submission preparation succeeded; sleeping %ss", delay_ok)
            time.sleep(delay_ok)
        elif result == 2:
            logger.info("Window not ready; rechecking in %ss", delay_blocked)
            time.sleep(delay_blocked)
        else:
            logger.warning("Submission attempt failed (code %s); retrying in %ss", result, delay_blocked)
            time.sleep(delay_blocked)


if __name__ == "__main__":
    run_loop()
