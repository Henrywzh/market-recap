"""Federal Reserve Z.1 corporate equity purchases: quarters, groups and percentiles.

Pure arithmetic on quarterly series that the panel has already fetched. Units
go in as millions of dollars for one quarter (or as a seasonally adjusted annual
rate, where a series is one) and come out as billions of dollars for one quarter.
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd

from ..util import clean_float

# Trailing four quarters, the window the page reads a holder's pace over.
WINDOW = 4
# Percentiles are taken against trailing sums since this date (window ends).
PERCENTILE_SINCE = pd.Timestamp("1990-01-01")
# A percentile of fewer windows than this is noise, not a ranking.
MIN_WINDOWS = 20
# Quarterly observations the chart keeps: ten years.
CHART_QUARTERS = 40


def to_quarter_bn(values_mn: pd.Series, basis: str) -> pd.Series:
    """Millions of dollars to billions for one quarter.

    A SAAR value is an annual rate, so it is divided by four first. An NSA value
    is already the quarter's own total. An unknown basis is an error, not a guess.
    """
    divisor = {"NSA": 1.0, "SAAR": 4.0}[basis]
    return pd.to_numeric(values_mn, errors="coerce") / divisor / 1000.0


def decompose(lines: pd.DataFrame, total: pd.Series, groups: Sequence[tuple[str, tuple[str, ...]]]) -> pd.DataFrame:
    """Each group's quarterly flow, plus ``other`` as the total less every named group.

    A group is missing in a quarter if any of its lines is missing: a partial
    sum would read as a smaller buyer, not as a gap. ``other`` therefore keeps the
    groups summing to the total in every quarter the total exists.
    """
    out = pd.DataFrame(index=lines.index)
    named: list[str] = []
    for key, members in groups:
        out[key] = lines[list(members)].sum(axis=1, min_count=len(members))
        named.append(key)
    out["other"] = total.reindex(lines.index) - out[named].sum(axis=1, min_count=len(named))
    return out


def trailing_sum(quarterly: pd.Series, window: int = WINDOW) -> pd.Series:
    """Sum over the last ``window`` quarters, missing if any of them is missing."""
    return quarterly.rolling(window, min_periods=window).sum()


def percentile_of(latest: float | None, history: pd.Series) -> float | None:
    """Share of the history at or below ``latest``, in 0-100.

    None when there is no latest value or too few windows to rank it against.
    """
    clean = pd.to_numeric(history, errors="coerce").dropna()
    if latest is None or pd.isna(latest) or len(clean) < MIN_WINDOWS:
        return None
    return clean_float(100.0 * float((clean <= latest).mean()), 1)


def quarter_label(start: pd.Timestamp) -> str:
    """The quarter a FRED observation date (its first day) belongs to: 2026-04-01 is 2026Q2."""
    stamp = pd.Timestamp(start)
    return f"{stamp.year}Q{(stamp.month - 1) // 3 + 1}"


def quarter_end(start: pd.Timestamp) -> pd.Timestamp:
    """Last day of the quarter that begins on ``start``."""
    return pd.Timestamp(start) + pd.DateOffset(months=3) - pd.Timedelta(days=1)


def summary(quarterly: pd.Series) -> dict:
    """Latest quarter, trailing four-quarter sum and its percentile since 1990, for one line."""
    sums = trailing_sum(quarterly)
    latest_sum = sums.dropna()
    latest_sum = latest_sum.iloc[-1] if not latest_sum.empty else None
    since = sums[sums.index >= PERCENTILE_SINCE]
    return {
        "q_bn": clean_float(quarterly.dropna().iloc[-1], 2) if quarterly.dropna().size else None,
        "trailing_4q_bn": clean_float(latest_sum, 1),
        "pctile_4q": percentile_of(latest_sum, since),
    }


def history(quarterly: pd.Series, quarters: int = CHART_QUARTERS, digits: int = 2) -> dict:
    """Dates and values of the last ``quarters`` observations, missing kept as None."""
    tail = quarterly.tail(quarters)
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
        "values": [clean_float(v, digits) for v in tail],
    }
