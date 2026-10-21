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


def etf_units(ticker: str) -> pd.DataFrame:
    """(date, nav, shares_outstanding) as the evening snapshots recorded them
    for a fund whose issuer publishes only today's units. Empty when fewer
    than two days are recorded: one day of units is not yet a flow."""
    shares = risk_archive("invesco", f"{ticker} shares_outstanding")
    nav = risk_archive("invesco", f"{ticker} nav")
    frame = pd.concat({"shares_outstanding": shares, "nav": nav}, axis=1).dropna()
    if len(frame) < 2:
        return pd.DataFrame(columns=["date", "nav", "shares_outstanding"])
    return frame.rename_axis("date").reset_index()[["date", "nav", "shares_outstanding"]]


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


def consensus_history(since: date, until: date) -> dict[str, dict[str, dict]]:
    """{day: {symbol: trend}} from the recorded consensus files, each trend in
    estimates.parse_trend's shape (end, eps, low, high and revenue per period)."""
    base = root() / "consensus"
    out: dict[str, dict[str, dict]] = {}
    day = since
    while day <= until:
        path = base / f"{day:%Y}" / f"{day:%Y-%m-%d}.csv.gz"
        if path.exists():
            try:
                frame = pd.read_csv(path, compression="gzip")
            except (OSError, ValueError):
                frame = None
            if frame is not None:
                trends: dict[str, dict] = {}
                for row in frame.itertuples(index=False):
                    trends.setdefault(row.symbol, {})[row.period] = {
                        "end": None if pd.isna(row.end) else str(row.end),
                        "eps": None if pd.isna(row.eps) else float(row.eps),
                        "low": None if pd.isna(row.eps_low) else float(row.eps_low),
                        "high": None if pd.isna(row.eps_high) else float(row.eps_high),
                        "revenue": None if pd.isna(getattr(row, "revenue", None)) else float(row.revenue)}
                out[day.isoformat()] = trends
        day += timedelta(days=1)
    return out


CONSENSUS_COLUMNS = ("date", "symbol", "period", "end", "eps", "analysts", "revenue", "up_30d", "down_30d", "up_7d", "down_7d")


def consensus_table(since: date, until: date) -> pd.DataFrame:
    """Every recorded consensus row between two dates, one row per day, company
    and fiscal period, with the day as an ISO string in ``date``. A file written
    before the 7-day revision counts were recorded has them as NaN. Empty
    (with the columns) when nothing was recorded."""
    base = root() / "consensus"
    frames = []
    day = since
    while day <= until:
        path = base / f"{day:%Y}" / f"{day:%Y-%m-%d}.csv.gz"
        if path.exists():
            try:
                frame = pd.read_csv(path, compression="gzip")
            except (OSError, ValueError):
                frame = None
            if frame is not None and not frame.empty:
                frame["date"] = day.isoformat()
                frames.append(frame.reindex(columns=list(CONSENSUS_COLUMNS)))
        day += timedelta(days=1)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(CONSENSUS_COLUMNS))
