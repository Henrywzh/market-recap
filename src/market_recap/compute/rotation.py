"""Relative strength of GICS groups against the index they belong to.

A group is a basket of today's members. Cap-weighted, each member is held at
today's official weight turned into units (weight / today's price) and kept
there, so the basket drifts with prices the way an index does between
rebalances. Equal-weighted, it is the mean daily return of the members priced
on both days. The benchmark is the whole index built the same way, from the
same (dividend-adjusted) closes, so dividends and the weighting scheme cancel
and a sector's excess return is its members' contributions summed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}
# Relative-rotation-graph smoothing, in weeks. RS-Ratio is relative strength
# against its own 10-week mean; RS-Momentum is RS-Ratio against its 4-week mean.
RATIO_WEEKS = 10
MOMENTUM_WEEKS = 4
# A session this thinly priced is a gap row, not a session: skipping it keeps
# the next day's return measured against the last real close.
MIN_SESSION_COVERAGE = 0.5


def sessions(closes: pd.DataFrame) -> pd.DataFrame:
    """Drop rows too thinly priced to be a session."""
    if closes.empty:
        return closes
    coverage = closes.notna().sum(axis=1) / closes.shape[1]
    return closes.loc[coverage >= MIN_SESSION_COVERAGE]


def units(closes: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Today's weight as a holding: the share count that makes it that weight."""
    last = closes.ffill().iloc[-1]
    return (weights.reindex(closes.columns) / last).where(last > 0)


def basket(closes: pd.DataFrame, held: pd.Series | None) -> pd.Series:
    """Daily level of a basket, starting at 1.

    ``held`` is units per member (cap-weighted); None means equal-weighted.
    Each day uses only members priced on that day and the one before, so a
    listing or a missing print changes the basket, not its level.
    """
    previous = closes.shift(1)
    both = closes.notna() & previous.notna()
    returns = (closes / previous - 1).where(both)
    if held is None:
        daily = returns.mean(axis=1)
    else:
        value = previous.mul(held.reindex(closes.columns), axis=1).where(both)
        weight = value.div(value.sum(axis=1), axis=0)
        daily = (weight * returns).sum(axis=1, min_count=1)
    return (1 + daily.fillna(0.0)).cumprod()


def window_return(level: pd.Series, sessions_back: int) -> float | None:
    clean = level.dropna()
    if len(clean) <= sessions_back:
        return None
    start = clean.iloc[-1 - sessions_back]
    return float(clean.iloc[-1] / start - 1) if start else None


def start_weights(closes: pd.DataFrame, held: pd.Series | None, sessions_back: int) -> pd.Series:
    """Each member's share of its basket at the start of a window."""
    if len(closes) <= sessions_back:
        return pd.Series(dtype=float)
    row = closes.iloc[-1 - sessions_back]
    priced = row.notna() & closes.iloc[-1].notna()
    if held is None:
        count = int(priced.sum())
        return (priced.astype(float) / count) if count else pd.Series(dtype=float)
    value = (row * held.reindex(closes.columns)).where(priced)
    total = value.sum()
    return value / total if total else pd.Series(dtype=float)


def member_returns(closes: pd.DataFrame, sessions_back: int) -> pd.Series:
    if len(closes) <= sessions_back:
        return pd.Series(dtype=float)
    return closes.iloc[-1] / closes.iloc[-1 - sessions_back] - 1


def rrg(group: pd.Series, bench: pd.Series) -> pd.DataFrame:
    """Weekly RS-Ratio and RS-Momentum, 100 = neutral.

    Weeks end on their last session, so the current week is today's close.
    """
    rs = (group / bench).dropna()
    if rs.empty:
        return pd.DataFrame(columns=["date", "ratio", "momentum"])
    week = rs.index.to_period("W-FRI")
    weekly = rs.groupby(week).last()
    ends = pd.Series(rs.index, index=rs.index).groupby(week).last()
    ratio = 100 * weekly / weekly.rolling(RATIO_WEEKS).mean()
    momentum = 100 * ratio / ratio.rolling(MOMENTUM_WEEKS).mean()
    out = pd.DataFrame({"date": ends.to_numpy(), "ratio": ratio.to_numpy(), "momentum": momentum.to_numpy()})
    return out.dropna().reset_index(drop=True)


def quadrant(ratio: float | None, momentum: float | None) -> str | None:
    if ratio is None or momentum is None or np.isnan(ratio) or np.isnan(momentum):
        return None
    if ratio >= 100:
        return "leading" if momentum >= 100 else "weakening"
    return "improving" if momentum >= 100 else "lagging"
