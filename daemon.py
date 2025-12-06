#!/usr/bin/env python3
"""
🛠️ Allora Forge Kit: Permanent Daemon for Hourly Prediction Submission

Version: Numbered Reference Format (Clean & Focused)
Purpose: Run an automated loop to train and submit predictions for Topic 67 every hour until Dec 15, 2025.

Author: GitHub Copilot
Date: December 6, 2025
"""

import asyncio
import datetime
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Configuration
END_TIME = datetime.datetime(2025, 12, 15, 13, 0, 0, tzinfo=datetime.timezone.utc)
CYCLE_INTERVAL_SECONDS = 3600  # 1 hour
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 300  # 5 minutes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/daemon.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global shutdown flag
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    signal_name = signal.Signals(signum).name
    logger.info(f"🛑 Received signal {signal_name} ({signum}), initiating graceful shutdown...")
    shutdown_requested = True

def run_command(cmd: list[str], description: str, timeout: int = 1800) -> tuple[bool, Optional[str]]:
    """
    Run a subprocess command with proper error handling and logging.

    Args:
        cmd: Command to run as list
        description: Human-readable description for logging
        timeout: Timeout in seconds (default 30 minutes)

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    try:
        logger.info(f"🚀 Starting: {description}")
        logger.debug(f"Command: {' '.join(cmd)}")

        # Run the command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path.cwd()
        )

        if result.returncode == 0:
            logger.info(f"✅ Completed: {description}")
            if result.stdout.strip():
                logger.debug(f"Output: {result.stdout.strip()}")
            return True, None
        else:
            error_msg = result.stderr.strip() or f"Command failed with return code {result.returncode}"
            logger.error(f"❌ Failed: {description} - {error_msg}")
            if result.stdout.strip():
                logger.debug(f"Stdout: {result.stdout.strip()}")
            return False, error_msg

    except subprocess.TimeoutExpired:
        error_msg = f"Command timed out after {timeout} seconds"
        logger.error(f"⏰ Timeout: {description} - {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"💥 Exception: {description} - {error_msg}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return False, error_msg

def run_training_cycle() -> bool:
    """Run a single training cycle."""
    logger.info("🤖 Starting training cycle...")

    # Run training
    success, error = run_command(
        ["python", "train.py"],
        "Model training",
        timeout=1200  # 20 minutes timeout for training
    )

    if not success:
        logger.error(f"Training failed: {error}")
        return False

    logger.info("✅ Training cycle completed successfully")
    return True

def run_submission_cycle() -> bool:
    """Run a single submission cycle."""
    logger.info("📤 Starting submission cycle...")

    # Run submission
    success, error = run_command(
        ["python", "submit_prediction.py"],
        "Prediction submission",
        timeout=600  # 10 minutes timeout for submission
    )

    if not success:
        logger.error(f"Submission failed: {error}")
        return False

    logger.info("✅ Submission cycle completed successfully")
    return True

async def run_single_cycle() -> tuple[bool, bool]:
    """
    Run a single complete cycle: training + submission.

    Returns:
        Tuple of (training_success, submission_success)
    """
    cycle_start = datetime.datetime.now(datetime.timezone.utc)
    logger.info(f"⏱️ Starting cycle at: {cycle_start.isoformat()}")

    # Check if we should still be running
    if cycle_start >= END_TIME:
        logger.info("🎯 Competition end time reached, stopping daemon")
        return False, False

    # Run training
    training_success = run_training_cycle()

    # Run submission (even if training failed, try to submit with existing model)
    submission_success = run_submission_cycle()

    cycle_end = datetime.datetime.now(datetime.timezone.utc)
    cycle_duration = (cycle_end - cycle_start).total_seconds()

    logger.info(f"⏱️ Cycle completed in {cycle_duration:.2f} seconds")
    return training_success, submission_success

async def run_daemon_loop():
    """Main daemon loop that runs hourly cycles until end time."""
    global shutdown_requested

    logger.info("🚀 Starting Allora Forge Kit Daemon")
    logger.info(f"📅 End time: {END_TIME.isoformat()}")
    logger.info(f"⏰ Cycle interval: {CYCLE_INTERVAL_SECONDS} seconds")
    logger.info(f"🔄 Max retries: {MAX_RETRIES}")
    logger.info("=" * 60)

    cycle_count = 0
    consecutive_failures = 0

    while not shutdown_requested:
        current_time = datetime.datetime.now(datetime.timezone.utc)

        # Check if competition has ended
        if current_time >= END_TIME:
            logger.info("🎯 Competition deadline reached. Daemon shutting down.")
            break

        cycle_count += 1
        cycle_start_time = time.time()

        logger.info(f"\n{'='*60}")
        logger.info(f"🔄 CYCLE #{cycle_count} - {current_time.isoformat()}")
        logger.info(f"{'='*60}")

        try:
            # Run the cycle
            training_success, submission_success = await run_single_cycle()

            # Log cycle results
            if training_success and submission_success:
                logger.info("✅ Cycle completed successfully")
                consecutive_failures = 0
            elif training_success and not submission_success:
                logger.warning("⚠️ Training succeeded but submission failed")
                consecutive_failures = 0  # Training success resets failure count
            else:
                logger.error("❌ Cycle failed (training and/or submission)")
                consecutive_failures += 1

            # If too many consecutive failures, add extra delay
            if consecutive_failures >= 3:
                logger.warning(f"⚠️ {consecutive_failures} consecutive failures, adding extra delay")
                await asyncio.sleep(RETRY_DELAY_SECONDS)

        except Exception as e:
            logger.error(f"💥 Unexpected error in cycle: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            consecutive_failures += 1

        # Calculate wait time for next cycle
        cycle_end_time = time.time()
        cycle_duration = cycle_end_time - cycle_start_time
        wait_time = max(0, CYCLE_INTERVAL_SECONDS - cycle_duration)

        if wait_time > 0:
            logger.info(f"🛌 Sleeping for {wait_time:.0f} seconds until next cycle...")
            await asyncio.sleep(wait_time)
        else:
            logger.warning(f"⚠️ Cycle took {cycle_duration:.2f} seconds (longer than interval), starting next cycle immediately")
    logger.info("🛑 Daemon loop ended")
    logger.info(f"📊 Total cycles completed: {cycle_count}")

def validate_environment():
    """Validate that required environment variables and files are present."""
    required_vars = ["ALLORA_WALLET_ADDR", "TOPIC_ID"]
    missing_vars = []

    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set them in .env file or export them in your shell")
        return False

    # Check for required files
    required_files = ["train.py", "submit_prediction.py"]
    missing_files = []

    for file in required_files:
        if not Path(file).exists():
            missing_files.append(file)

    if missing_files:
        logger.error(f"❌ Missing required files: {', '.join(missing_files)}")
        return False

    # Check for artifacts directory
    Path("artifacts").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    logger.info("✅ Environment validation passed")
    return True

def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Validate environment
    if not validate_environment():
        sys.exit(1)

    # Run the daemon
    try:
        asyncio.run(run_daemon_loop())
    except KeyboardInterrupt:
        logger.info("🛑 Keyboard interrupt received, shutting down...")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

    logger.info("👋 Daemon shutdown complete")

if __name__ == "__main__":
    main()