"""Read back what the snapshot job recorded (src/market_recap/snapshots).

The nightly workflow checks the ``snapshots`` branch out at ``[snapshots]
root``; a local build without it simply has no recorded history, and every
page that reads it says "not recorded yet" rather than guessing.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..config import load_config
from ..snapshots import store


def root() -> Path:
    return store.root_dir(None)


def available() -> bool:
    return any((root() / kind).exists() for kind in ("expectations", "options", "risk"))


def _risk_rows() -> pd.DataFrame:
    """Every row the risk snapshots wrote, read once per build."""
    key = str(root())
    if key not in _RISK_ROWS:
        base = root() / "risk"
        files = sorted(base.glob("baseline/*.csv.gz")) + sorted(base.glob("[0-9][0-9][0-9][0-9]/*.csv.gz"))
        frames = []
        for path in files:
            try:
                frames.append(pd.read_csv(path, compression="gzip"))
            except (OSError, ValueError):
                continue
        _RISK_ROWS[key] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["fetched_at", "source", "series", "date", "value"])
    return _RISK_ROWS[key]


_RISK_ROWS: dict[str, pd.DataFrame] = {}


def risk_archive(source: str, series: str) -> pd.Series:
    """Every value the risk snapshots recorded for one series: the baseline
    (current-vintage history at the time it was written) and each evening's
    tail. Where two files give a date, the later fetch wins. Empty when
    nothing was recorded."""
    rows = _risk_rows()
    rows = rows[(rows["source"] == source) & (rows["series"] == series)]
    if rows.empty:
        return pd.Series(dtype=float)
    rows = rows.sort_values(["date", "fetched_at"]).drop_duplicates("date", keep="last")
    return pd.Series(rows["value"].to_numpy(dtype=float), index=pd.to_datetime(rows["date"]), name=series)


def expectation_runs(since: date, until: date) -> list[Path]:
    """Every expectations run file between two dates, oldest first."""
    base = root() / "expectations"
    out: list[Path] = []
    day = since
    while day <= until:
        folder = base / f"{day:%Y}" / f"{day:%Y-%m-%d}"
        if folder.exists():
            out.extend(sorted(folder.glob("*.csv.gz")))
        day += timedelta(days=1)
    return out


def expectation_run_on_or_before(day: date, *, lookback_days: int = 6) -> pd.DataFrame | None:
    """The last recorded expectations run on or before ``day``, if one exists
    within ``lookback_days`` of it."""
    runs = expectation_runs(day - timedelta(days=lookback_days), day)
    if not runs:
        return None
    return pd.read_csv(runs[-1], compression="gzip")


def latest_options_summary(until: date, *, lookback_days: int = 7) -> tuple[date, pd.DataFrame] | None:
    """The most recent options summary file on or before ``until``."""
    base = root() / "options"
    for offset in range(lookback_days + 1):
        day = until - timedelta(days=offset)
        path = base / f"{day:%Y}" / f"{day:%Y-%m-%d}-summary.csv"
        if path.exists():
            return day, pd.read_csv(path)
    return None


def options_summaries(since: date, until: date) -> pd.DataFrame:
    """All options summary rows between two dates (IV history)."""
    base = root() / "options"
    frames = []
    day = since
    while day <= until:
        path = base / f"{day:%Y}" / f"{day:%Y-%m-%d}-summary.csv"
        if path.exists():
            frame = pd.read_csv(path)
            frame["day"] = day.isoformat()
            frames.append(frame)
        day += timedelta(days=1)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def configured_root() -> str:
    return str(load_config().get("snapshots", {}).get("root", "data/snapshots"))
