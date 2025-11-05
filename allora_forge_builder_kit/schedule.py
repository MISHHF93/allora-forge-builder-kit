"""Scheduling helpers for the hourly Allora competition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

__all__ = ["WindowSet", "CompetitionSchedule"]


@dataclass(frozen=True)
class WindowSet:
    """Bundle of time ranges used by the training pipeline."""

    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime
    inference_time: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "train_start": _iso(self.train_start),
            "train_end": _iso(self.train_end),
            "validation_start": _iso(self.validation_start),
            "validation_end": _iso(self.validation_end),
            "test_start": _iso(self.test_start),
            "test_end": _iso(self.test_end),
            "inference_time": _iso(self.inference_time),
        }


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CompetitionSchedule:
    """Deterministic schedule for the Allora hourly competition."""

    def __init__(
        self,
        start: datetime,
        end: datetime,
        cadence: timedelta,
        train_span: timedelta,
        validation_span: timedelta,
        test_span: timedelta,
    ) -> None:
        if cadence <= timedelta(0):
            raise ValueError("Cadence must be positive")
        self.start = start.astimezone(timezone.utc)
        self.end = end.astimezone(timezone.utc)
        self.cadence = cadence
        self.train_span = train_span
        self.validation_span = validation_span
        self.test_span = test_span
        self.minimum_span = train_span + validation_span + test_span

        if self.end <= self.start:
            raise ValueError("Schedule end must be after start")
        if self.minimum_span <= timedelta(0):
            raise ValueError("Total span must be positive")

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CompetitionSchedule":
        start = _parse_dt(str(payload.get("start")))
        end = _parse_dt(str(payload.get("end")))
        cadence = _parse_cadence(str(payload.get("cadence", "1h")))
        train_span = _parse_hours(payload, "train_span_hours", default_hours=24 * 28)
        validation_span = _parse_hours(payload, "validation_span_hours", default_hours=24 * 7)
        test_span = _parse_hours(payload, "test_span_hours", default_hours=24)
        return cls(start, end, cadence, train_span, validation_span, test_span)

    def align(self, when: Optional[datetime] = None) -> datetime:
        ts = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if ts < self.start:
            return self.start
        hours = int(((ts - self.start).total_seconds()) // self.cadence.total_seconds())
        aligned = self.start + hours * self.cadence
        if aligned > self.end:
            return self.end
        return aligned

    def windows(self, when: Optional[datetime] = None) -> WindowSet:
        base = self.align(when)
        latest = min(base, self.end)
        total_span = self.minimum_span
        earliest = max(self.start, latest - total_span)

        train_start = earliest
        train_end = train_start + self.train_span
        validation_start = train_end
        validation_end = validation_start + self.validation_span
        test_start = validation_end
        test_end = min(latest, test_start + self.test_span)

        if test_end - train_start < total_span:
            # When near the beginning, stretch the train window forward to honour cadence
            train_start = max(self.start, test_end - total_span)
            train_end = min(train_start + self.train_span, validation_start)

        inference_time = test_end
        return WindowSet(train_start, train_end, validation_start, validation_end, test_start, test_end, inference_time)


def _parse_dt(value: str) -> datetime:
    dt = pd.to_datetime(value, utc=True)
    if not isinstance(dt, pd.Timestamp):  # defensive
        raise ValueError(f"Invalid datetime value: {value}")
    return dt.to_pydatetime()


def _parse_cadence(value: str) -> timedelta:
    text = value.strip().lower()
    if text.endswith("h"):
        return timedelta(hours=float(text[:-1]))
    if text.endswith("m"):
        return timedelta(minutes=float(text[:-1]))
    if text.endswith("s"):
        return timedelta(seconds=float(text[:-1]))
    # Fallback to pandas frequency parsing
    delta = pd.to_timedelta(text)
    if not isinstance(delta, pd.Timedelta):
        raise ValueError(f"Invalid cadence value: {value}")
    return timedelta(seconds=float(delta.total_seconds()))


def _parse_hours(payload: dict[str, object], key: str, default_hours: int) -> timedelta:
    raw = payload.get(key)
    if raw is None:
        return timedelta(hours=default_hours)
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid hour span for {key}: {raw}") from None
    return timedelta(hours=hours)
