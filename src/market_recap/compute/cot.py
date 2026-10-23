"""Futures positioning by trader type: the arithmetic behind flows_cot.

Net positions are long minus short contracts. Each category is also read as a
share of open interest, because open interest grows over the years and a
contract count from 2012 is not comparable with one from 2024. Percentiles
and z-scores look back over the last three years of weekly reports only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Weekly reports in three years. A window with fewer observations has no
# percentile: the sample is too short to say where a reading sits.
WINDOW = 156
# Weekly reports a trend-check needs before a correlation means anything.
MIN_PAIRS = 52
# Trend-model readings are matched to a report Tuesday within this many days.
TREND_TOLERANCE = pd.Timedelta(days=7)

# The four contracts. ``symbol`` is the index close the contract is valued at; the
# VIX future is valued at the spot VIX, which the page labels approximate.
CONTRACTS = (
    {"key": "es", "label": "S&P 500 E-MINI", "code": "13874A", "symbol": "^GSPC", "multiplier": 50,
     "index_label": "S&P 500"},
    {"key": "nq", "label": "NASDAQ-100 E-MINI", "code": "209742", "symbol": "^NDX", "multiplier": 20,
     "index_label": "Nasdaq-100"},
    {"key": "rty", "label": "RUSSELL 2000 E-MINI", "code": "239742", "symbol": "^RUT", "multiplier": 50,
     "index_label": "Russell 2000"},
    {"key": "vx", "label": "VIX FUTURES", "code": "1170E1", "symbol": "^VIX", "multiplier": 1000,
     "index_label": "VIX", "approximate": True},
)

# Category key, label, the CATEGORY_FIELDS prefix it reads. The four named in the
# chart come first; non-reportables are reported in the table only.
CATEGORIES = (
    ("dealer", "Dealers"),
    ("asset_mgr", "Asset managers"),
    ("lev_money", "Leveraged money"),
    ("other", "Other reportables"),
    ("nonrept", "Non-reportables"),
)


def net(long: pd.Series, short: pd.Series) -> pd.Series:
    """Long minus short contracts; a side that is missing makes the net missing."""
    return long - short


def net_pct_oi(net_contracts: pd.Series, open_interest: pd.Series) -> pd.Series:
    """Net position as a percentage of open interest; missing where OI is not positive."""
    return 100 * net_contracts / open_interest.where(open_interest > 0)


def trailing(series: pd.Series, window: int = WINDOW) -> pd.Series:
    """The last ``window`` observations, with missing values dropped first."""
    return series.dropna().tail(window)


def percentile_3y(series: pd.Series, window: int = WINDOW) -> float | None:
    """Share of the trailing window at or below the latest value, 0-100."""
    sample = trailing(series, window)
    if len(sample) < window:
        return None
    return float((sample <= sample.iloc[-1]).mean() * 100)


def z_3y(series: pd.Series, window: int = WINDOW) -> float | None:
    """Latest value against the trailing window's mean and standard deviation."""
    sample = trailing(series, window)
    if len(sample) < window:
        return None
    spread = sample.std(ddof=1)
    if not np.isfinite(spread) or spread == 0:
        return None
    return float((sample.iloc[-1] - sample.mean()) / spread)


def change_1w(net_contracts: pd.Series) -> float | None:
    """Change over the last week in contracts; None unless the last two reports are seven days apart."""
    clean = net_contracts.dropna()
    if len(clean) < 2:
        return None
    if (clean.index[-1] - clean.index[-2]) != pd.Timedelta(days=7):
        return None
    return float(clean.iloc[-1] - clean.iloc[-2])


def dollar_net_bn(net_contracts: float | None, multiplier: float, price: float | None) -> float | None:
    """Notional of a net position in $ billions: contracts times the multiplier times the price."""
    if net_contracts is None or price is None or not np.isfinite(net_contracts) or not np.isfinite(price):
        return None
    return float(net_contracts * multiplier * price / 1e9)


def price_on(close: pd.Series, when: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    """(session, close) of the last close on or before ``when``; None if the series starts later."""
    clean = close.dropna()
    before = clean[clean.index <= when]
    return (before.index[-1], float(before.iloc[-1])) if not before.empty else None


def trend_check(lev_pct: pd.Series, position: pd.Series, window: int = WINDOW) -> dict:
    """Correlation of one category's net % OI series with a trend-model position.

    Each report date takes the model's last reading on or before it, within a
    week. Levels and four-week changes are correlated over the trailing window.
    This is a check of how the two co-move, not a test of either's signal.
    """
    lev = trailing(lev_pct, window)
    position = position.dropna().sort_index()
    if lev.empty or position.empty:
        return {"n": 0, "corr_levels": None, "corr_changes_4w": None}
    aligned = pd.merge_asof(
        pd.DataFrame({"date": lev.index, "lev": lev.to_numpy()}),
        pd.DataFrame({"date": position.index, "position": position.to_numpy()}),
        on="date", direction="backward", tolerance=TREND_TOLERANCE,
    ).dropna()
    n = int(len(aligned))
    if n < MIN_PAIRS:
        return {"n": n, "corr_levels": None, "corr_changes_4w": None}
    changes = aligned[["lev", "position"]].diff(4).dropna()
    corr_levels = aligned["lev"].corr(aligned["position"])
    corr_changes = changes["lev"].corr(changes["position"]) if len(changes) >= MIN_PAIRS else None
    return {
        "n": n,
        "corr_levels": _finite(corr_levels),
        "corr_changes_4w": _finite(corr_changes),
    }


def _finite(value) -> float | None:
    return float(value) if value is not None and np.isfinite(value) else None
