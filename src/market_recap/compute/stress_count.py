"""STRESS COUNT: how many of a fixed list of stress conditions are on today.

Nine yes/no votes in five groups, written in ``[risk.stress]`` before they were
tested (research/risk_environment_v2). The count describes a stressed market. In
that test it was early in slow bear markets, late in fast declines, and added
nothing to a price-and-volatility forecast, so it is shown as a description,
with each group and each vote visible, and never as a signal or probability.

A vote whose input is missing is unknown, not off. The raw count exists only
when every vote is known; the page still shows how many known votes are on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PERIOD_TRADING_DAYS, TRADING_DAYS_PER_YEAR

WEEKLY_TOLERANCE_DAYS = 14
SPREAD_FILL_SESSIONS = 5
OPERATORS = {"gt": lambda s, t: s > t, "lt": lambda s, t: s < t, "le": lambda s, t: s <= t}
INPUTS = ("price_vs_ma", "drawdown", "sector_breadth", "spread_level", "spread_change",
          "vix", "realised_vol", "anfci", "anfci_change")


def weekly_on_sessions(weekly: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """A weekly series carried onto sessions: the latest value dated on or before
    each session, kept for at most ``WEEKLY_TOLERANCE_DAYS`` calendar days."""
    weekly = weekly.dropna().sort_index()
    if weekly.empty:
        return pd.Series(np.nan, index=sessions)
    right = pd.DataFrame({"date": pd.DatetimeIndex(weekly.index).astype("datetime64[ns]"), "value": weekly.values})
    left = pd.DataFrame({"session": pd.DatetimeIndex(sessions).astype("datetime64[ns]")})
    merged = pd.merge_asof(left, right, left_on="session", right_on="date",
                           tolerance=pd.Timedelta(days=WEEKLY_TOLERANCE_DAYS))
    return pd.Series(merged["value"].values, index=sessions)


def input_series(*, spx: pd.Series, sectors: pd.DataFrame, vix: pd.Series, spread: pd.Series,
                 anfci: pd.Series, long_ma: int) -> dict[str, pd.Series]:
    """Each vote's measured series on the index's sessions. ``spread`` is BAA - 10Y
    in percentage points; ``anfci`` is weekly."""
    spx = spx.dropna()
    sessions = spx.index
    month = PERIOD_TRADING_DAYS["1M"]
    average = sectors.reindex(sessions).rolling(long_ma).mean()
    known = average.notna().all(axis=1) & sectors.reindex(sessions).notna().all(axis=1)
    above = (sectors.reindex(sessions) > average).mean(axis=1).where(known) * 100 if not sectors.empty else pd.Series(np.nan, index=sessions)
    filled = spread.reindex(sessions).ffill(limit=SPREAD_FILL_SESSIONS)
    anfci = anfci.dropna()
    return {
        "price_vs_ma": 100 * (spx / spx.rolling(long_ma).mean() - 1),
        "drawdown": 100 * (spx / spx.rolling(TRADING_DAYS_PER_YEAR).max() - 1),
        "sector_breadth": above,
        "spread_level": filled,
        "spread_change": filled.diff(month),
        "vix": vix.reindex(sessions),
        "realised_vol": spx.pct_change(fill_method=None).rolling(month).std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100,
        "anfci": weekly_on_sessions(anfci, sessions),
        "anfci_change": weekly_on_sessions(anfci.diff(4), sessions),
    }


def votes_frame(series: dict[str, pd.Series], specs: list[dict]) -> pd.DataFrame:
    """1.0 on, 0.0 off, NaN unknown, one column per vote."""
    out = {}
    for spec in specs:
        s = series[spec["input"]]
        out[spec["key"]] = OPERATORS[spec["op"]](s, spec["threshold"]).astype(float).where(s.notna())
    return pd.DataFrame(out)


def score(votes: pd.DataFrame, groups: dict[str, list[str]]) -> tuple[pd.Series, pd.Series]:
    """Raw count and number of groups with a vote on; unknown unless every vote is known."""
    columns = [c for members in groups.values() for c in members]
    known = votes[columns].notna().all(axis=1)
    raw = votes[columns].sum(axis=1).where(known)
    grouped = pd.concat([votes[m].max(axis=1) for m in groups.values()], axis=1).sum(axis=1).where(known)
    return raw, grouped


def _number(value, digits: int = 2):
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


def evaluate(series: dict[str, pd.Series], settings: dict, *, history_sessions: int,
             observed: dict[str, str | None] | None = None) -> dict:
    """The page's STRESS COUNT block from the configured votes. ``observed`` gives each
    input's last real observation date (a weekly series is carried onto sessions, so
    its session-dated tail would overstate how fresh it is)."""
    observed = observed or {}
    specs, group_specs = settings["votes"], settings["groups"]
    votes = votes_frame(series, specs)
    groups = {g["key"]: [s["key"] for s in specs if s["group"] == g["key"]] for g in group_specs}
    raw, grouped = score(votes, groups)
    last = votes.index[-1]
    week = PERIOD_TRADING_DAYS["1W"]
    spec_of = {s["key"]: s for s in specs}
    out_groups = []
    for g in group_specs:
        rows = []
        for key in groups[g["key"]]:
            spec = spec_of[key]
            state = votes[key].iloc[-1]
            rows.append({
                "key": key, "label": spec["label"], "unit": spec.get("unit"), "op": spec["op"],
                "threshold": spec["threshold"], "frequency": spec.get("frequency", "daily"),
                "value": _number(series[spec["input"]].iloc[-1]),
                "on": None if pd.isna(state) else bool(state),
                "as_of": observed.get(spec["input"]),
            })
        known = [r for r in rows if r["on"] is not None]
        out_groups.append({"key": g["key"], "label": g["label"], "votes": rows,
                           "on": sum(1 for r in known if r["on"]), "known": len(known), "total": len(rows)})
    known_votes = [r for g in out_groups for r in g["votes"] if r["on"] is not None]
    history = pd.DataFrame({"raw": raw}).iloc[-history_sessions:]
    ago = raw.iloc[-1 - week] if len(raw) > week else np.nan
    return {
        "as_of": to_date(last),
        "reference": settings.get("reference"),
        "groups": out_groups,
        "raw": None if pd.isna(raw.iloc[-1]) else int(raw.iloc[-1]),
        "groups_on": None if pd.isna(grouped.iloc[-1]) else int(grouped.iloc[-1]),
        "known": len(known_votes),
        "total": len(specs),
        "on_known": sum(1 for r in known_votes if r["on"]),
        "week_ago": None if pd.isna(ago) else int(ago),
        "history": {"dates": [to_date(d) for d in history.index],
                    "raw": [None if pd.isna(v) else int(v) for v in history["raw"]]},
    }


def to_date(value) -> str:
    return pd.Timestamp(value).date().isoformat()
