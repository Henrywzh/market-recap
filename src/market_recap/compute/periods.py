"""Period-over-period changes of a dated series, matched by date, not by row.

FRED has no October 2025 CPI: the shutdown cancelled it. Counting rows, a
"year over year" figure for August 2026 then compared it with July 2025 --
3.71% on a page where the release said 3.35%. Each value is compared with the
observation dated exactly one period earlier; where that one is missing, the
change is missing too.
"""

from __future__ import annotations

import pandas as pd

OFFSETS = {
    "yoy": pd.DateOffset(years=1),
    "mom": pd.DateOffset(months=1),
    "change": pd.DateOffset(months=1),
}


def _prior(series: pd.Series, offset: pd.DateOffset) -> pd.Series:
    """Each date's value one period earlier, NaN where none was published."""
    prior = series.copy()
    prior.index = prior.index + offset
    return prior[~prior.index.duplicated()].reindex(series.index)


def transform(series: pd.Series, how: str) -> pd.Series:
    """``how``: level, yoy or mom (percent), change (difference)."""
    series = series.sort_index()
    if how == "level":
        return series
    prior = _prior(series, OFFSETS[how])
    if how == "change":
        return series - prior
    return (series / prior - 1.0) * 100.0
