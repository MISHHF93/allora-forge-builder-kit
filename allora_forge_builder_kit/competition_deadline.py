"""
Competition Deadline Management Module

Provides time-bound control logic to ensure pipeline stops gracefully 
when competition deadline is reached (December 15, 2025, 13:00 UTC).

This module handles:
- Deadline parsing and validation
- Time-until-deadline calculations
- Graceful shutdown with logging
- Last-eligible-submission detection
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import logging

# Competition constants
COMPETITION_START_UTC = "2025-09-16T13:00:00Z"  # September 16, 2025, 13:00 UTC
COMPETITION_END_UTC = "2025-12-15T13:00:00Z"    # December 15, 2025, 13:00 UTC

logger = logging.getLogger(__name__)


def parse_iso_utc(iso_string: str) -> datetime:
    """Parse ISO 8601 UTC datetime string to timezone-aware datetime.
    
    Args:
        iso_string: ISO format datetime (e.g., "2025-12-15T13:00:00Z")
    
    Returns:
        timezone-aware datetime in UTC
    
    Raises:
        ValueError: If string format is invalid
    """
    # Handle Z suffix (UTC)
    if iso_string.endswith("Z"):
        iso_string = iso_string[:-1] + "+00:00"
    
    try:
        dt = datetime.fromisoformat(iso_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except ValueError as e:
        raise ValueError(f"Invalid ISO 8601 datetime: {iso_string}") from e


def get_current_utc() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def is_competition_active() -> bool:
    """Check if competition is currently active.
    
    Returns:
        True if current UTC time is within [START, END), False otherwise
    """
    now = get_current_utc()
    start = parse_iso_utc(COMPETITION_START_UTC)
    end = parse_iso_utc(COMPETITION_END_UTC)
    
    return start <= now < end


def time_until_deadline() -> timedelta:
    """Calculate time remaining until competition deadline.
    
    Returns:
        timedelta until deadline. Negative if deadline has passed.
    """
    now = get_current_utc()
    end = parse_iso_utc(COMPETITION_END_UTC)
    
    return end - now


def seconds_until_deadline() -> float:
    """Get seconds until deadline as a float.
    
    Returns:
        Seconds remaining. Negative if deadline has passed.
    """
    delta = time_until_deadline()
    return delta.total_seconds()


def is_deadline_exceeded() -> bool:
    """Check if competition deadline has been exceeded.
    
    Returns:
        True if current UTC time >= END time, False otherwise
    """
    now = get_current_utc()
    end = parse_iso_utc(COMPETITION_END_UTC)
    
    return now >= end


def get_deadline_info() -> dict:
    """Get comprehensive deadline information.
    
    Returns:
        Dictionary with deadline details:
        - deadline: ISO format deadline string
        - current_utc: Current UTC time (ISO format)
        - is_active: Boolean indicating if competition is active
        - is_exceeded: Boolean indicating if deadline has passed
        - time_remaining: Seconds until deadline (negative if exceeded)
        - formatted_remaining: Human-readable time remaining
    """
    deadline = parse_iso_utc(COMPETITION_END_UTC)
    now = get_current_utc()
    delta = deadline - now
    seconds_remaining = delta.total_seconds()
    
    # Format human-readable duration
    if seconds_remaining < 0:
        hours, remainder = divmod(abs(seconds_remaining), 3600)
        minutes, _ = divmod(remainder, 60)
        formatted = f"EXCEEDED by {int(hours)}h {int(minutes)}m"
    else:
        days = int(seconds_remaining // 86400)
        hours, remainder = divmod(int(seconds_remaining % 86400), 3600)
        minutes, _ = divmod(remainder, 60)
        if days > 0:
            formatted = f"{days}d {hours}h {minutes}m remaining"
        else:
            formatted = f"{hours}h {minutes}m remaining"
    
    return {
        "deadline": deadline.isoformat(),
        "current_utc": now.isoformat(),
        "is_active": parse_iso_utc(COMPETITION_START_UTC) <= now < deadline,
        "is_exceeded": now >= deadline,
        "time_remaining": seconds_remaining,
        "formatted_remaining": formatted,
    }


def should_exit_loop(cadence_hours: float = 1.0) -> Tuple[bool, str]:
    """Determine if loop should exit based on deadline and cadence.
    
    This checks if the next cycle would start after the deadline, ensuring
    we don't initiate a cycle that cannot be completed and submitted.
    
    Args:
        cadence_hours: Cycle frequency in hours (default: 1.0 for hourly)
    
    Returns:
        Tuple of (should_exit: bool, reason: str)
        - (True, reason) if next cycle would exceed deadline
        - (False, reason) if still time for next cycle
    """
    now = get_current_utc()
    deadline = parse_iso_utc(COMPETITION_END_UTC)
    next_cycle = now + timedelta(hours=cadence_hours)
    
    info = get_deadline_info()
    
    if now >= deadline:
        return True, f"Deadline exceeded at {now.isoformat()}. Competition ended."
    
    if next_cycle > deadline:
        time_left = (deadline - now).total_seconds()
        hours_left = time_left / 3600
        return (
            True,
            f"Insufficient time for next cycle. "
            f"Next cycle would start at {next_cycle.isoformat()} "
            f"(after deadline {deadline.isoformat()}). "
            f"Only {hours_left:.1f}h remaining. "
            f"Stopping cleanly to preserve final submission opportunity."
        )
    
    return False, f"Next cycle eligible: {hours_left_clean(deadline - now)}"


def hours_left_clean(delta: timedelta) -> str:
    """Format timedelta as clean human-readable string."""
    total_seconds = delta.total_seconds()
    if total_seconds < 0:
        return "EXCEEDED"
    days = int(total_seconds // 86400)
    hours = int((total_seconds % 86400) // 3600)
    minutes = int((total_seconds % 3600) // 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    
    return " ".join(parts) if parts else "< 1m"


def log_deadline_status() -> None:
    """Log comprehensive deadline status for monitoring."""
    info = get_deadline_info()
    logger.info("═" * 70)
    logger.info("COMPETITION DEADLINE STATUS")
    logger.info("═" * 70)
    logger.info(f"Deadline:          {info['deadline']}")
    logger.info(f"Current UTC:       {info['current_utc']}")
    logger.info(f"Status:            {'🟢 ACTIVE' if info['is_active'] else '🔴 INACTIVE'}")
    logger.info(f"Time Remaining:    {info['formatted_remaining']}")
    logger.info("═" * 70)


def validate_deadline_configuration() -> bool:
    """Validate deadline configuration is sensible.
    
    Returns:
        True if configuration is valid, raises ValueError otherwise
    """
    start = parse_iso_utc(COMPETITION_START_UTC)
    end = parse_iso_utc(COMPETITION_END_UTC)
    
    if start >= end:
        raise ValueError(
            f"Invalid deadline configuration: start ({start}) >= end ({end})"
        )
    
    duration = (end - start).total_seconds() / 86400
    if duration < 1:
        raise ValueError(
            f"Competition duration too short: {duration:.1f} days. "
            "Should be >= 1 day."
        )
    
    logger.info(
        f"✅ Deadline configuration valid. "
        f"Competition runs {duration:.0f} days "
        f"from {start.isoformat()} to {end.isoformat()}"
    )
    
    return True


# Initialize and validate on module import
try:
    validate_deadline_configuration()
except ValueError as e:
    logger.error(f"❌ Deadline configuration invalid: {e}")
    raise
