"""Timestamps, freshness labelling, provenance and JSON output.

The dashboard's credibility rests on saying where a number came from and how
old it is. These helpers exist so that no panel can ship a value without a
source and an observation date attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import FRESHNESS


# How much of an exception message is carried into an artifact. Long enough to
# name the cause, short enough that a stack-trace-shaped string cannot push a
# panel's real content off the page.
ERROR_DETAIL_CHARS = 200


def describe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:ERROR_DETAIL_CHARS]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    return stamp.strftime("%Y-%m-%d")


def clean_float(value: Any, digits: int | None = None) -> float | None:
    """Return a JSON-safe float, or None. NaN and inf are absences, not zeros."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return round(out, digits) if digits is not None else out


def freshness_status(observed: Any, policy: str) -> str:
    """Label an observation against its policy without inventing a reason.

    ``unknown`` is a real answer: a missing observation date must not be
    rendered as if the value were current.
    """
    iso = to_iso_date(observed)
    if iso is None:
        return "unknown"
    limit = FRESHNESS.get(policy, {}).get("stale_after_calendar_days", 7)
    age = (date.today() - date.fromisoformat(iso)).days
    if age <= 1:
        return "current"
    if age <= limit:
        return "recent"
    return "stale"


@dataclass
class SourceRecord:
    """One attributable fetch. This is what the footer and the status pill read."""

    source_id: str
    label: str
    url: str
    observed_date: str | None = None
    retrieved_at: str = field(default_factory=utc_now_iso)
    rows: int = 0
    policy: str = "daily_close"
    status: str = "ok"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["freshness"] = freshness_status(self.observed_date, self.policy)
        return out


class BuildLog:
    """Collects source records and panel failures across one build.

    A panel that fails must leave a visible gap rather than silently dropping
    out of the page: an empty tab with no explanation reads like working
    software showing a true "nothing happened", which is the one thing a
    market dashboard must never do.
    """

    def __init__(self) -> None:
        self.sources: list[SourceRecord] = []
        self.errors: dict[str, str] = {}

    def add(self, record: SourceRecord) -> SourceRecord:
        self.sources.append(record)
        return record

    def fail(self, panel: str, exc: BaseException) -> None:
        self.errors[panel] = describe_error(exc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [record.to_dict() for record in self.sources],
            "errors": self.errors,
        }


def _default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return clean_float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return to_iso_date(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if pd.isna(obj):
        return None
    raise TypeError(f"Not JSON serialisable: {type(obj)!r}")


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, default=_default, separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return path
