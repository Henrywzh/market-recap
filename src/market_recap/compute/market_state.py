"""MARKET STATE: how narrow or stressed the market is, and what followed before.

Breadth here is read from price series that carry no survivorship: the
equal-weight fund against the cap-weighted one, small caps against the market,
the share of the sector funds above their moving averages, the market's
distance from its high, and the VIX. Constituent breadth (advancing shares, new
highs) is left to MARKETS: any history of it is built from today's members.

Each named state is a rule over those readings. For the days a rule held, the
market's next-``horizon`` outcome (return, worst drawdown, whether a drawdown of
``floor`` percent or more came) is set against the days it did not hold, with a
95% range from a moving-block bootstrap: the blocks are as long as the horizon
because neighbouring days share most of their forward window, so the days are
not independent samples. The finding that shaped this: narrowness alone has not
been detected to predict anything; the readings that carry information are the
stress ones (high VIX, thin sector breadth, deep drawdown), and they raise both
the later return and the later drawdown -- a risk state, not a direction.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

READINGS = ("rsp_spy", "iwm_spy", "sector_above_200", "sector_above_50", "spy_drawdown", "vix")


def features(closes: pd.DataFrame, *, market: str, equal_weight: str, small_caps: str, vix: str,
             sectors: Sequence[str], relative_sessions: int, high_sessions: int, long_ma: int, short_ma: int) -> pd.DataFrame:
    """The daily readings, one row per session; a reading without enough history
    is NaN. ``rsp_spy`` and ``iwm_spy`` are the percent change of the price
    ratio (fund / market) over ``relative_sessions``, not a return gap in pp; the sector shares are percent of the
    sector funds that have a moving average yet; ``spy_drawdown`` is percent
    from the highest close of the last ``high_sessions``."""
    c = closes.sort_index()
    out = pd.DataFrame(index=c.index)
    out["rsp_spy"] = ((c[equal_weight] / c[market]).pct_change(relative_sessions, fill_method=None)) * 100
    out["iwm_spy"] = ((c[small_caps] / c[market]).pct_change(relative_sessions, fill_method=None)) * 100
    present = [s for s in sectors if s in c.columns]
    for label, window in (("sector_above_200", long_ma), ("sector_above_50", short_ma)):
        ma = c[present].rolling(window).mean()
        known = ma.notna().sum(axis=1)
        above = ((c[present] > ma) & ma.notna()).sum(axis=1)
        out[label] = (above / known.where(known > 0)) * 100
    out["spy_drawdown"] = (c[market] / c[market].rolling(high_sessions, min_periods=high_sessions).max() - 1) * 100
    out["vix"] = c[vix] if vix in c.columns else np.nan
    return out


def forward_outcomes(price: pd.Series, horizon: int, floor_pct: float) -> pd.DataFrame:
    """For each session the next ``horizon`` sessions' return (percent), the
    worst peak-to-trough fall inside that window counting the entry close as
    its first peak (percent, <= 0), and whether that fall reached ``floor_pct``.
    The last ``horizon`` sessions have no outcome yet and are NaN."""
    v = price.to_numpy(dtype=float)
    out = np.full((len(v), 3), np.nan)
    if len(v) > horizon:
        windows = sliding_window_view(v, horizon + 1)           # one window per session that has a full horizon ahead
        peak = np.maximum.accumulate(windows, axis=1)
        worst = (windows / peak - 1).min(axis=1) * 100
        ret = (windows[:, -1] / windows[:, 0] - 1) * 100
        n = len(windows)
        out[:n, 0], out[:n, 1] = ret, worst
        out[:n, 2] = (worst <= -floor_pct).astype(float)
    return pd.DataFrame(out, index=price.index, columns=["ret", "worst_dd", "hit"])


def block_indices(n: int, block: int, resamples: int, seed: int) -> np.ndarray:
    """``resamples`` x ``n`` row indices for a moving-block bootstrap: blocks of
    ``block`` consecutive rows drawn with replacement and joined."""
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(resamples, blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(resamples, -1)[:, :n]
    return idx


def mean_difference(values: np.ndarray, mask: np.ndarray, indices: np.ndarray, *, min_each: int = 20) -> dict:
    """Mean of ``values`` where ``mask`` against where it does not, with a 95%
    range from the resampled rows; the range is None when the state is too
    rare in the resamples to give one."""
    inside, outside = values[mask], values[~mask]
    if len(inside) < min_each or len(outside) < min_each:
        return {"inside": None, "outside": None, "diff": None, "lo": None, "hi": None}
    v, m = values[indices], mask[indices]
    n_in, n_out = m.sum(axis=1), (~m).sum(axis=1)
    ok = (n_in >= min_each) & (n_out >= min_each)
    sums_in = np.where(m, v, 0.0).sum(axis=1)
    sums_out = np.where(~m, v, 0.0).sum(axis=1)
    diffs = (sums_in[ok] / n_in[ok]) - (sums_out[ok] / n_out[ok])
    lo, hi = (float(x) for x in np.percentile(diffs, [2.5, 97.5])) if len(diffs) >= 100 else (None, None)
    return {"inside": float(inside.mean()), "outside": float(outside.mean()), "diff": float(inside.mean() - outside.mean()), "lo": lo, "hi": hi}


def episodes(mask: np.ndarray, gap: int) -> int:
    """Separate stretches of days a state held: runs more than ``gap`` sessions
    apart are different episodes. The honest sample size of a state whose
    neighbouring days are nearly the same day."""
    where = np.flatnonzero(mask)
    if not len(where):
        return 0
    return int(1 + (np.diff(where) > gap).sum())


def holds(frame: pd.DataFrame, conditions: Sequence[dict]) -> pd.Series:
    """True where every condition ({reading, op: 'lt' | 'gt', value}) holds; a
    day with a missing reading is False, not a guess."""
    result = pd.Series(True, index=frame.index)
    for cond in conditions:
        col = frame[cond["reading"]]
        result &= (col < cond["value"]) if cond["op"] == "lt" else (col > cond["value"])
    return result.fillna(False)
