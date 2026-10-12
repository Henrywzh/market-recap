"""SIZE K: the large, cap-weighted arm against the equal-weight or smaller arm.

Each pair is two price series that hold much the same market, weighted or
sized differently: the S&P 500 by market cap (SPY) and with every name equal
(RSP); the Nasdaq-100 likewise; large caps against small and mid caps. Every
figure is a ratio or a gap between the two arms: how far the biggest companies
have run ahead of the rest, and where that sits in the series' own history.
Nothing here says which arm is right, and a ratio that has risen for years
says only that it has, not that it must turn.
"""

from __future__ import annotations

import pandas as pd


def rolling_gap(big: pd.Series, small: pd.Series, sessions: int) -> pd.Series:
    """Return of ``big`` less return of ``small`` over each trailing window of
    ``sessions``, in percentage points, on the dates both are priced."""
    both = pd.concat([big.rename("b"), small.rename("s")], axis=1).dropna()
    if len(both) <= sessions:
        return pd.Series(dtype=float)
    return ((both["b"] / both["b"].shift(sessions) - 1) - (both["s"] / both["s"].shift(sessions) - 1)).dropna() * 100


def calendar_years(big: pd.Series, small: pd.Series) -> list[dict]:
    """Each calendar year's return of both arms and the gap (big less small),
    from the last close of the year before to the last close of the year. The
    first year runs from the first close both were priced, and is flagged
    ``partial_start`` when that was after the first week of January; the
    current year is flagged ``to_date``."""
    both = pd.concat([big.rename("b"), small.rename("s")], axis=1).dropna()
    if both.empty:
        return []
    first = both.index[0]
    ends = both.groupby(both.index.year).tail(1)
    rows, prev = [], both.iloc[0]
    for date, row in ends.iterrows():
        big_r, small_r = float(row["b"] / prev["b"] - 1) * 100, float(row["s"] / prev["s"] - 1) * 100
        rows.append({"year": int(date.year), "big": big_r, "small": small_r, "gap": big_r - small_r,
                     "partial_start": bool(date.year == first.year and (first.month, first.day) > (1, 7)),
                     "to_date": bool(date == both.index[-1] and (date.month, date.day) < (12, 24))})
        prev = row
    return rows


def ratio_extremes(ratio: pd.Series) -> dict | None:
    """Where the ratio stands against its own high and low: the highest and
    lowest value with their dates, and today's distance from each (percent)."""
    r = ratio.dropna()
    if r.empty:
        return None
    hi, lo, now = r.idxmax(), r.idxmin(), float(r.iloc[-1])
    return {"high": float(r[hi]), "high_date": hi, "low": float(r[lo]), "low_date": lo,
            "from_high_pct": (now / float(r[hi]) - 1) * 100, "from_low_pct": (now / float(r[lo]) - 1) * 100}


def share_of_windows(gap: pd.Series) -> float | None:
    """Percent of the rolling windows in which the big arm beat the small arm."""
    g = gap.dropna()
    return None if g.empty else float((g > 0).mean() * 100)


def longest_run(gap: pd.Series, *, positive: bool = True) -> int:
    """The longest stretch (in observations) the rolling gap stayed on one side of zero."""
    g = gap.dropna()
    if g.empty:
        return 0
    flag = (g > 0) if positive else (g < 0)
    best = run = 0
    for v in flag.to_numpy():
        run = run + 1 if v else 0
        best = max(best, run)
    return int(best)
