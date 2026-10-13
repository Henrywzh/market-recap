"""CATALYST LOG: did consensus estimates follow a price move?

For a dated event (a report, a competitor's announcement, a leak) and the
names it bears on: how far each name's price has moved since the close before
the event, and how far each consensus estimate (EPS and revenue, current
quarter, current year, next year) has moved since the evening snapshot taken
at that close. A basket reads as one of three states on each axis -- down,
flat, up -- from the median of its names against a threshold set in the config.

What it can say is bounded. The snapshots are Yahoo's consensus *averages*,
which move days to weeks after analysts do; a flat estimate soon after an
event is a statement about those days, not about what analysts will conclude.
Nothing here predicts: it separates a move in what investors pay (price down,
estimates flat) from a move in what they expect to earn (estimates down).
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

FLAT_PCT = 0.05          # a change smaller than this is "no change" when counting names up and down


def last_on_or_before(series: pd.Series, day: date) -> tuple[pd.Timestamp, float] | None:
    """The last non-missing observation on or before ``day``."""
    s = series.dropna()
    s = s[s.index <= pd.Timestamp(day)]
    if s.empty:
        return None
    return s.index[-1], float(s.iloc[-1])


def reference_day(event_day: date, after_close: bool) -> date:
    """The close an event's moves are measured from: the last close before the
    event's date, or the event date's own close when it broke after the close."""
    return event_day if after_close else date.fromordinal(event_day.toordinal() - 1)


def pct_change(before: float | None, after: float | None) -> float | None:
    """Percent change where the starting figure is positive; None otherwise
    (a change off a loss or a missing figure is not a rate)."""
    if before is None or after is None or not (isinstance(before, (int, float)) and isinstance(after, (int, float))):
        return None
    if not (math.isfinite(before) and math.isfinite(after)) or before <= 0:
        return None
    return (after / before - 1) * 100


def state(value: float | None, threshold: float) -> str | None:
    """down / flat / up against a symmetric threshold; None for no figure."""
    if value is None or not math.isfinite(value):
        return None
    return "down" if value <= -threshold else "up" if value >= threshold else "flat"


def summarize(values: list[float | None]) -> dict:
    """Median and how many names are up, down or unchanged, of those with a figure."""
    v = [x for x in values if x is not None and math.isfinite(x)]
    return {"n": len(v), "median": float(np.median(v)) if v else None,
            "up": sum(x > FLAT_PCT for x in v), "down": sum(x < -FLAT_PCT for x in v), "flat": sum(abs(x) <= FLAT_PCT for x in v)}


def snapshot_days(table: pd.DataFrame, ref: date) -> tuple[str | None, str | None]:
    """(the last snapshot dated on or before ``ref``, the latest snapshot)."""
    if table.empty:
        return None, None
    days = sorted(table["date"].unique())
    before = [d for d in days if d <= ref.isoformat()]
    return (before[-1] if before else None), days[-1]


def estimate_changes(table: pd.DataFrame, symbol: str, periods: list[str], ref_day: str | None, latest_day: str | None) -> dict:
    """{period: {"eps": pct, "revenue": pct}} between two snapshot days for one
    symbol; every figure None when the symbol has no snapshot on either day."""
    out = {p: {"eps": None, "revenue": None} for p in periods}
    if ref_day is None or latest_day is None or ref_day == latest_day:
        return out
    sub = table[table["symbol"] == symbol]
    for period in periods:
        a = sub[(sub["date"] == ref_day) & (sub["period"] == period)]
        b = sub[(sub["date"] == latest_day) & (sub["period"] == period)]
        if a.empty or b.empty:
            continue
        for field in ("eps", "revenue"):
            out[period][field] = pct_change(_num(a.iloc[0][field]), _num(b.iloc[0][field]))
    return out


def _num(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def basket_path(closes: pd.DataFrame, names: list[str], ref: date, *, end: pd.Timestamp | None = None) -> pd.Series:
    """Median of the names' closes rebased to 100 at the reference close, by
    date from the reference on. A name with no close on or before the
    reference is left out; a holiday in one market carries its last close."""
    rebased = {}
    for name in names:
        if name not in closes.columns:
            continue
        s = closes[name].dropna()
        base = last_on_or_before(s, ref)
        if base is None:
            continue
        rebased[name] = 100 * s[s.index >= base[0]] / base[1]
    if not rebased:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(rebased).sort_index().ffill()
    if end is not None:
        frame = frame[frame.index <= end]
    return frame.median(axis=1)
