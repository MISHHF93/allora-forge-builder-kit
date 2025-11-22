#!/usr/bin/env python3
"""
Allora Competition Submission Entry Point
Wrapper for train.py with validation, error handling, and cron compatibility
"""

import sys
import os
import argparse
import logging
from typing import Optional
import subprocess
import json
import traceback
from pathlib import Path
import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%SZ'
)
logger = logging.getLogger(__name__)


def validate_environment():
    """Verify required environment and files are present."""
    logger.info("Validating environment...")
    
    # Check required files
    required_files = [
        'train.py',
        '.env',
        '.allora_key',
        'config/pipeline.yaml'
    ]
    
    for file in required_files:
        if not os.path.exists(file):
            logger.warning(f"Missing {file}")
    
    # Check environment variables
    api_key = os.getenv('ALLORA_API_KEY')
    if not api_key:
        logger.warning("ALLORA_API_KEY not set - data fetching may fail")
    
    logger.info("✅ Environment validation complete")
    return True


def validate_predictions(predictions) -> bool:
    """Validate prediction array before submission."""
    logger.info("Validating predictions...")
    
    try:
        import numpy as np
        import pandas as pd
        
        # Type check
        if not isinstance(predictions, (np.ndarray, list, pd.Series)):
            raise ValueError(f"Predictions must be list/array/Series, got {type(predictions)}")
        
        # Convert to numpy for checks
        pred_array = np.asarray(predictions, dtype=float)
        
        # Check for NaNs
        if np.isnan(pred_array).any():
            raise ValueError("Predictions contain NaNs")
        
        # Check for infinities
        if np.isinf(pred_array).any():
            raise ValueError("Predictions contain infinite values")
        
        # Warn if predictions are out of typical log-return range
        # Log-returns for BTC typically in range [-5, 5]
        if np.any(np.abs(pred_array) > 10):
            logger.warning(f"⚠️  Predictions may be out of expected range: min={np.min(pred_array):.4f}, max={np.max(pred_array):.4f}")
        
        # Basic statistics
        logger.info(f"✅ Predictions valid: shape={pred_array.shape}, mean={np.mean(pred_array):.6f}, std={np.std(pred_array):.6f}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Prediction validation failed: {e}")
        raise


def ensure_logs_directory():
    """Ensure logs directory exists."""
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)
    return logs_dir


def run_train_pipeline(once_mode: bool = True, submit: bool = True) -> int:
    """Execute train.py with appropriate arguments."""
    logger.info("Starting training pipeline...")
    
    cmd = [
        sys.executable,
        'train.py',
        '--schedule-mode', 'loop',
    ]
    
    if once_mode:
        cmd.append('--once')
    else:
        cmd.append('--loop')
    
    if submit:
        cmd.append('--submit')
    
    cmd.extend([
        '--as-of-now'
    ])
    
    logger.info(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=False)
        return result.returncode
    except Exception as e:
        logger.error(f"Failed to run pipeline: {e}")
        logger.error(traceback.format_exc())
        return 1


def check_submission_success(lookback_minutes: int = 5) -> bool:
    """Check if recent submission was successful."""
    logger.info("Checking submission status...")
    
    submission_log = Path('submission_log.csv')
    if not submission_log.exists():
        logger.warning("Submission log not found")
        return False
    
    try:
        import pandas as pd
        df = pd.read_csv(submission_log)
        
        # Get recent entries (last 5 minutes)
        df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], errors='coerce')
        now = pd.Timestamp.now(tz='UTC')
        recent = df[df['timestamp_utc'] > (now - pd.Timedelta(minutes=lookback_minutes))]
        
        if recent.empty:
            logger.warning("No recent submission attempts found")
            return False
        
        # Check for successful submissions
        last_attempt = recent.iloc[-1]
        status = last_attempt.get('status', '')
        success = str(last_attempt.get('success', '')).lower() == 'true'
        
        logger.info(f"Last attempt: status={status}, success={success}")
        
        if success and status == 'submitted':
            logger.info("✅ Submission successful")
            return True
        else:
            logger.info(f"⚠️  Submission skipped or failed: {status}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking submission: {e}")
        return False


def main():
    """Main entry point for cron-based submission."""
    parser = argparse.ArgumentParser(
        description='Allora competition submission wrapper'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        default=True,
        help='Run single iteration (default for cron)'
    )
    parser.add_argument(
        '--loop',
        action='store_true',
        help='Run continuous loop (not recommended for cron)'
    )
    parser.add_argument(
        '--no-submit',
        action='store_true',
        help='Skip submission (training only)'
    )
    parser.add_argument(
        '--check-health',
        action='store_true',
        help='Check submission health and exit'
    )
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Validate environment and exit'
    )
    
    args = parser.parse_args()
    
    logger.info("="*80)
    logger.info(f"ALLORA COMPETITION SUBMISSION - {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%SZ')}")
    logger.info("="*80)
    
    try:
        # Ensure directories
        ensure_logs_directory()
        
        # Validate environment
        if not validate_environment():
            return 1
        
        if args.validate_only:
            logger.info("Validation complete, exiting")
            return 0
        
        if args.check_health:
            success = check_submission_success()
            return 0 if success else 1
        
        # Determine mode
        once_mode = not args.loop
        submit = not args.no_submit
        
        # Run pipeline
        rc = run_train_pipeline(once_mode=once_mode, submit=submit)
        
        if rc == 0:
            # Check if submission was successful
            if submit:
                check_submission_success()
            logger.info("✅ Pipeline execution complete")
        else:
            logger.error(f"❌ Pipeline failed with return code {rc}")
        
        logger.info("="*80)
        return rc
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.error(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())
