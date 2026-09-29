"""Who is forced to trade: a trend-follower proxy and short interest.

Trend followers (CTAs, vol-control and risk-parity books that run trend
rules) buy or sell on rules, not views, so the levels at which their rules
flip are knowable in advance. Their exact models are private; this is the
textbook stand-in: the sign of the index's return over several lookbacks,
averaged. +1 means every lookback is up (fully long), -1 every lookback
down. A lookback's sign flips tomorrow if tomorrow's close crosses the close
it will be compared with -- the close ``n - 1`` sessions before today -- so
each flip level is a known price, not a forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACKS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}


def trend_score(close: pd.Series, lookbacks: dict[str, int] = LOOKBACKS) -> pd.Series:
    """Mean sign of the return over each lookback, in [-1, 1]."""
    close = close.dropna()
    signs = pd.concat({label: np.sign(close / close.shift(n) - 1) for label, n in lookbacks.items()}, axis=1)
    return signs.dropna().mean(axis=1)


def flip_levels(close: pd.Series, lookbacks: dict[str, int] = LOOKBACKS) -> list[dict]:
    """For each lookback: today's return and sign, and the close tomorrow must
    cross to flip it. Tomorrow's n-session return compares with the close n
    sessions before tomorrow, which is ``close.iloc[-n]`` today."""
    close = close.dropna()
    last = float(close.iloc[-1])
    rows = []
    for label, n in lookbacks.items():
        if len(close) <= n:
            continue
        today_base = float(close.iloc[-1 - n])
        tomorrow_base = float(close.iloc[-n])
        ret = last / today_base - 1
        rows.append({
            "lookback": label,
            "sessions": n,
            "return_pct": ret * 100,
            "signal": 1 if ret > 0 else -1 if ret < 0 else 0,
            "flip_level": tomorrow_base,
            "distance_pct": (tomorrow_base / last - 1) * 100,
        })
    return rows


def ma_levels(close: pd.Series, windows=(50, 100, 200)) -> list[dict]:
    """The moving averages trend rules also watch, and the distance to each."""
    close = close.dropna()
    last = float(close.iloc[-1])
    out = []
    for w in windows:
        if len(close) < w:
            continue
        level = float(close.tail(w).mean())
        out.append({"window": w, "level": level, "distance_pct": (level / last - 1) * 100, "above": last > level})
    return out


def label(score: float | None) -> str | None:
    """LONG / SHORT when three of four lookbacks agree, else MIXED."""
    if score is None or not np.isfinite(score):
        return None
    return "LONG" if score >= 0.5 else "SHORT" if score <= -0.5 else "MIXED"
