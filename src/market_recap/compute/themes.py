"""THEMES: bellwether impact, report-date projection and data due dates.

A theme's proxy is an ETF where one isolates it, otherwise an equal-weight
basket of its members. A bellwether's impact is scored like EVENTS'
read-through (compute.events.co_move): the proxy's move beyond the S&P 500
on the bellwether's own reaction sessions, per 1% of the bellwether's
excess move. When the bellwether is itself in a basket, it is left out of
the basket for its own score; an ETF cannot be split that way, so an ETF's
score includes the bellwether's own weight in it, and the page says so.
"""

from __future__ import annotations

from datetime import date, timedelta
import statistics

import pandas as pd

GAP_BOUNDS = (80, 100)


def basket_excess(excess: pd.DataFrame, members: list[str], leave_out: str | None = None) -> pd.Series:
    """Equal-weight mean of the members' daily excess moves."""
    cols = [m for m in members if m in excess.columns and m != leave_out]
    return excess[cols].mean(axis=1, skipna=True) if cols else pd.Series(dtype=float)


def project_next(past: list[date], as_of: date) -> date | None:
    """The next report from the median gap between past ones, clipped to a
    quarter's range, rolled forward past ``as_of``."""
    past = sorted(set(past))
    if len(past) < 2:
        return None
    gap = int(min(max(statistics.median((b - a).days for a, b in zip(past, past[1:])), GAP_BOUNDS[0]), GAP_BOUNDS[1]))
    nxt = past[-1] + timedelta(days=gap)
    while nxt <= as_of:
        nxt += timedelta(days=gap)
    return nxt


def monthly_due(latest_month: str | None, day_of_month: int, as_of: date) -> dict | None:
    """When the month after ``latest_month`` is due (published by
    ``day_of_month`` of the month after it), and whether it is late."""
    if not latest_month:
        return None
    year, month = (int(p) for p in latest_month.split("-"))
    month += 1
    if month == 13:
        year, month = year + 1, 1
    pub_year, pub_month = (year, month + 1) if month < 12 else (year + 1, 1)
    due = date(pub_year, pub_month, day_of_month)
    return {"month": f"{year:04d}-{month:02d}", "due": due.isoformat(), "late": as_of > due}


def run_in(series: pd.Series, market: pd.Series) -> dict:
    """1M and 3M return of a price series and against the S&P 500."""
    out = {}
    s, m = series.dropna(), market.dropna()
    for label, n in (("1m", 21), ("3m", 63)):
        if len(s) > n and len(m) > n:
            r = 100 * (s.iloc[-1] / s.iloc[-1 - n] - 1)
            rm = 100 * (m.iloc[-1] / m.iloc[-1 - n] - 1)
            out[f"ret_{label}"] = round(float(r), 2)
            out[f"vs_spx_{label}"] = round(float(r - rm), 2)
    return out


def basket_index(closes: pd.DataFrame, members: list[str]) -> pd.Series:
    """Equal-weight index of the members' closes (daily rebalanced), = 100 at start."""
    cols = [m for m in members if m in closes.columns]
    returns = closes[cols].pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0)
    return 100 * (1 + returns).cumprod()


def yoy_monthly(rows: list[dict], value: str) -> list[dict]:
    """Adds y/y growth to monthly rows keyed by 'YYYY-MM'."""
    by_month = {r["month"]: r for r in rows}
    out = []
    for r in rows:
        y, m = (int(p) for p in r["month"].split("-"))
        prior = by_month.get(f"{y - 1:04d}-{m:02d}")
        yoy = round(100 * (r[value] / prior[value] - 1), 1) if prior and prior.get(value) and r.get(value) is not None else None
        out.append({**r, "yoy_pct": r.get("yoy_pct") if r.get("yoy_pct") is not None else yoy})
    return out
