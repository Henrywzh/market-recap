"""Where snapshots are written, and the rules every writer shares."""

from __future__ import annotations

import csv
from datetime import datetime, time
import gzip
import io
import json
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from ..config import MARKET_TIMEZONE, REPO_ROOT, load_config

NEW_YORK = ZoneInfo(MARKET_TIMEZONE)
DEFAULT_ROOT = "data/snapshots"


def root_dir(override: str | Path | None = None) -> Path:
    value = override or load_config().get("snapshots", {}).get("root") or DEFAULT_ROOT
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def day_dir(root: Path, kind: str, stamp: datetime) -> Path:
    path = root / kind / f"{stamp:%Y}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_clock(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def in_window(now: datetime, window: Sequence[str]) -> bool:
    """A weekday New York wall-clock time inside [start, end)."""
    local = now.astimezone(NEW_YORK)
    if local.weekday() >= 5:
        return False
    start, end = (parse_clock(value) for value in window)
    return start <= local.time() < end


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def write_csv(path: Path, rows: Sequence[Mapping], columns: Sequence[str], *, compress: bool = False) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(row.get(key)) for key in columns})
    data = buffer.getvalue().encode()
    if compress:
        # mtime=0 so an identical snapshot produces identical bytes in git.
        data = gzip.compress(data, mtime=0)
    path.write_bytes(data)


def append_jsonl(path: Path, record: Mapping) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


def utc_stamp(now: datetime) -> str:
    return now.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
