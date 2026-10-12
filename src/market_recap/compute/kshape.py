"""K-SHAPE: a high-income leg against a low-income leg, within an industry.

The two legs are named in the config, by hand: a name is in the top leg when
its customers are mostly the wealthy (luxury, premium cabins, premium
resorts), in the bottom leg when they are mostly low-income households. The
middle -- the squeezed, aspirational customer -- is left out of the spread.
Every figure is a ratio of the top leg to the bottom leg, with where today's
ratio sits in its own history. Nothing here says which leg is right: the page
shows the divergence and what has been paid for it.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def leg_index(closes: pd.DataFrame, members: Sequence[str]) -> pd.Series:
    """Equal-weight index of the members' closes (rebalanced daily), 100 on the
    first session any member traded. A member joins when it first prices: a
    leg of one recent listing starts at its listing. Empty when none priced."""
    cols = [m for m in members if m in closes.columns and closes[m].notna().any()]
    if not cols:
        return pd.Series(dtype=float)
    frame = closes[cols]
    start = frame.apply(pd.Series.first_valid_index).min()
    returns = frame.loc[start:].pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0)
    return 100 * (1 + returns).cumprod()


def period_return(index: pd.Series, sessions: int | None) -> float | None:
    """Percent change over the last ``sessions``; None when the index is shorter."""
    if sessions is None or len(index) <= sessions:
        return None
    return float((index.iloc[-1] / index.iloc[-1 - sessions] - 1) * 100)


def spread_table(top: pd.Series, bottom: pd.Series, periods: dict[str, int]) -> list[dict]:
    """Each leg's return over each window and the gap (top less bottom, in
    percentage points); a window longer than both legs' common history is
    absent, never a shorter one under its name."""
    both = pd.concat([top.rename("t"), bottom.rename("b")], axis=1).dropna()
    rows = []
    for label, sessions in periods.items():
        t, b = period_return(both["t"], sessions), period_return(both["b"], sessions)
        rows.append({"period": label, "top": t, "bottom": b, "spread": None if t is None or b is None else t - b})
    return rows


def percentile(series: pd.Series, value: float | None, *, min_n: int = 52) -> float | None:
    """Share of the series' own observations at or below ``value``, in percent;
    None when there are fewer than ``min_n`` of them."""
    clean = series.dropna()
    if value is None or len(clean) < min_n or not math.isfinite(value):
        return None
    return float((clean <= value).mean() * 100)


def median_multiple(by_name: dict[str, pd.Series], members: Iterable[str], *, min_share: float = 0.5,
                    cap: float = 60.0) -> pd.Series:
    """The members' median P/E on each date, counting only the meaningful ones
    (positive and at most ``cap``: a P/E of 900 is a profit near zero, not a
    price). A date is kept only where at least ``min_share`` of the members that
    have a history that day are meaningful: a leg whose earnings vanished in a
    year is blank that year, not the median of the one name that still earned."""
    names = [m for m in members if m in by_name and by_name[m] is not None and not by_name[m].dropna().empty]
    if not names:
        return pd.Series(dtype=float)
    frame = pd.concat([by_name[m].rename(m) for m in names], axis=1).sort_index()
    present = frame.notna().sum(axis=1)
    meaningful = frame.where((frame > 0) & (frame <= cap))
    keep = meaningful.notna().sum(axis=1) >= np.ceil(min_share * present).clip(lower=1)
    out = meaningful.median(axis=1, skipna=True)
    return out.where(keep & (present > 0)).dropna()


def ratio(top: pd.Series, bottom: pd.Series) -> pd.Series:
    """Top over bottom on the dates both have a value, bottom above zero."""
    both = pd.concat([top.rename("t"), bottom.rename("b")], axis=1).dropna()
    both = both[both["b"] > 0]
    return both["t"] / both["b"]


def eps_growth(eps_rows: Sequence[dict], key: str = "operating", *, cap: float = 150.0) -> pd.Series:
    """Year-on-year growth (%) of a name's trailing-twelve-month EPS as filed,
    by period end, where the figure a year earlier was positive (growth off a
    loss or a near-zero is not a growth rate) and at most ``cap`` percent in
    size: +2,700% off a profit of a few cents is not a figure either. Rows are
    the valuation artifact's ``eps`` list."""
    rows = [(pd.Timestamp(r["period_end"]), r.get(key)) for r in eps_rows if r.get(key) is not None and r.get("period_end")]
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series(dict(rows)).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    out = {}
    for date, value in s.items():
        prior = s[(s.index >= date - pd.Timedelta(days=380)) & (s.index <= date - pd.Timedelta(days=350))]
        if not prior.empty and prior.iloc[-1] > 0:
            growth = (value / prior.iloc[-1] - 1) * 100
            if abs(growth) <= cap:
                out[date] = growth
    return pd.Series(out, dtype=float)


def median_growth(by_name: dict[str, pd.Series], members: Iterable[str], *, min_names: int = 1) -> pd.Series:
    """The members' median growth by period end, where at least ``min_names``
    have one."""
    names = [m for m in members if m in by_name and not by_name[m].empty]
    if not names:
        return pd.Series(dtype=float)
    frame = pd.concat([by_name[m].rename(m) for m in names], axis=1).sort_index()
    return frame.median(axis=1, skipna=True).where(frame.notna().sum(axis=1) >= min_names).dropna()


def median_of(values: Iterable[float | None]) -> float | None:
    """The median of the figures that exist; None when none does."""
    v = [x for x in values if x is not None and isinstance(x, (int, float)) and math.isfinite(x)]
    return float(np.median(v)) if v else None
