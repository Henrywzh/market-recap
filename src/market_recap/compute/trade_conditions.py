"""TRADE DESK conditions: the market backdrop on each past session, as it was known then.

The Trade Desk's event study can keep only the signals that fired in a backdrop
like a chosen one (rates rising, the Fed cutting, a stressed VIX...). Each
condition here is a daily state built from what the market could see at that
session's close, never from a later revision or a label fitted afterwards:

- Fed cycle: the target rate (upper bound since December 2008) against its
  level ``fed_lookback_days`` calendar days earlier.
- 10-year yield against its own ``long_ma``-session average.
- The market fund against its ``long_ma``-session average.
- The VIX in fixed bands, not in percentiles of a history that includes the future.
- The equal-weight fund against the cap-weighted one: the z-score of their log
  price ratio against its trailing ``z_window`` sessions.
- The growth / inflation quadrant: the month-end real-time archive (ADS +
  Cleveland, config/regime_quadrant_history.json) then the MACRO tab's daily
  nowcast ledger. It applies from the session after it was read.

A state is written as runs, ``[first_date, state]`` whenever it changes, so the
browser can look up any session without a row per day.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

QUADRANTS = ("GOLDILOCKS", "REFLATION", "STAGFLATION", "SLOWDOWN")


def runs(states: pd.Series) -> list[list]:
    """``[[date, state], ...]`` at each change; an unknown session ends a run as ``None``."""
    out: list[list] = []
    last = object()
    for day, value in states.items():
        value = None if value is None or (isinstance(value, float) and np.isnan(value)) else value
        if value != last:
            out.append([day.strftime("%Y-%m-%d"), value])
            last = value
    while out and out[0][1] is None:
        out.pop(0)
    return out


def fed_cycle(target: pd.Series, sessions: pd.DatetimeIndex, lookback_days: int) -> pd.Series:
    """HIKING / HOLD / CUTTING on each session from the target's change over ``lookback_days``."""
    daily = target.sort_index().groupby(level=0).last()
    calendar = pd.date_range(daily.index[0], max(daily.index[-1], sessions[-1]), freq="D")
    level = daily.reindex(calendar).ffill()
    change = level - level.shift(lookback_days)
    state = pd.Series(np.select([change > 1e-9, change < -1e-9], ["HIKING", "CUTTING"], "HOLD"), index=calendar)
    state[change.isna()] = None
    return state.reindex(sessions)


def above_average(series: pd.Series, sessions: pd.DatetimeIndex, window: int, up: str, down: str) -> pd.Series:
    s = series.dropna().sort_index()
    ma = s.rolling(window, min_periods=window).mean()
    state = pd.Series(np.where(s > ma, up, down), index=s.index, dtype=object)
    state[ma.isna()] = None
    # A session the series did not print (a bond-market holiday) keeps the last state.
    return state.reindex(sessions, method="ffill")


def vix_band(vix: pd.Series, sessions: pd.DatetimeIndex, calm: float, stressed: float) -> pd.Series:
    v = vix.dropna().sort_index()
    state = pd.Series(np.select([v < calm, v > stressed], ["CALM", "STRESSED"], "NORMAL"), index=v.index, dtype=object)
    return state.reindex(sessions, method="ffill", limit=3)


def equal_weight_z(equal: pd.Series, market: pd.Series, window: int, band: float) -> tuple[pd.Series, pd.Series]:
    """(z-score, state) of log(equal / market) against its trailing ``window`` sessions."""
    ratio = np.log(equal / market).dropna()
    mean = ratio.rolling(window, min_periods=window).mean()
    std = ratio.rolling(window, min_periods=window).std()
    z = (ratio - mean) / std
    state = pd.Series(np.select([z > band, z < -band], ["EW LEADING", "EW LAGGING"], "IN LINE"), index=z.index, dtype=object)
    state[z.isna()] = None
    return z, state


def quadrant_events(history: Iterable[dict], ledger: Iterable[dict]) -> list[tuple[pd.Timestamp, str]]:
    """(first session date it applies, quadrant): archive rows from the day after
    ``known``, ledger rows from the day after their build date. Later wins."""
    events = {}
    for row in history:
        if row.get("quadrant") in QUADRANTS:
            events[pd.Timestamp(row["known"]) + pd.Timedelta(days=1)] = row["quadrant"]
    for row in ledger or []:
        if row.get("quadrant") in QUADRANTS and row.get("date"):
            events[pd.Timestamp(row["date"]) + pd.Timedelta(days=1)] = row["quadrant"]
    return sorted(events.items())


def quadrant_states(events: list[tuple[pd.Timestamp, str]], sessions: pd.DatetimeIndex) -> pd.Series:
    if not events:
        return pd.Series(None, index=sessions, dtype=object)
    s = pd.Series([q for _, q in events], index=[d for d, _ in events], dtype=object)
    return s.reindex(sessions.union(s.index)).ffill().reindex(sessions)
