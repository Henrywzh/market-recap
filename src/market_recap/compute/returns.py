"""Period returns, drawdown and breadth.

One definition per concept, used by every panel. A "1M return" that means 21
trading days on the heat map and a calendar month on the sector table produces
a page that contradicts itself, which is worse than showing neither.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import PERIOD_TRADING_DAYS


def period_return(closes: pd.Series, trading_days: int) -> float | None:
    """Return over the last ``trading_days`` sessions, in percent.

    Returns None when the history is too short, rather than measuring from the
    first available bar and silently labelling a 4-month return as 1Y.
    """
    clean = closes.dropna()
    if len(clean) < trading_days + 1:
        return None
    start = clean.iloc[-(trading_days + 1)]
    end = clean.iloc[-1]
    if not np.isfinite(start) or start == 0:
        return None
    return float((end / start - 1.0) * 100.0)


def ytd_return(closes: pd.Series) -> float | None:
    clean = closes.dropna()
    if clean.empty:
        return None
    last = clean.index[-1]
    prior_year = clean[clean.index < pd.Timestamp(year=last.year, month=1, day=1)]
    if prior_year.empty:
        return None
    start = prior_year.iloc[-1]
    if not np.isfinite(start) or start == 0:
        return None
    return float((clean.iloc[-1] / start - 1.0) * 100.0)


def all_period_returns(closes: pd.Series, periods: tuple[str, ...] = ("1D", "1W", "1M", "3M", "1Y")) -> dict:
    out: dict[str, float | None] = {}
    for label in periods:
        if label == "YTD":
            out[label] = ytd_return(closes)
        else:
            out[label] = period_return(closes, PERIOD_TRADING_DAYS[label])
    if "YTD" not in out:
        out["YTD"] = ytd_return(closes)
    return out


def drawdown_from_high(closes: pd.Series) -> dict:
    """Current drawdown plus how long ago the running high was set.

    The trading-day count is the number of sessions since the peak, which is
    the figure a desk actually quotes -- not calendar days.
    """
    clean = closes.dropna()
    if clean.empty:
        return {"drawdown_pct": None, "trading_days_since_high": None, "high_date": None, "high": None}
    running_max = clean.cummax()
    peak = float(running_max.iloc[-1])
    last = float(clean.iloc[-1])
    high_positions = np.flatnonzero(clean.to_numpy() >= peak * (1 - 1e-12))
    high_idx = int(high_positions[-1]) if high_positions.size else len(clean) - 1
    return {
        "drawdown_pct": float((last / peak - 1.0) * 100.0) if peak else None,
        "trading_days_since_high": int(len(clean) - 1 - high_idx),
        "high_date": clean.index[high_idx].strftime("%Y-%m-%d"),
        "high": peak,
    }


def advance_decline(closes: pd.DataFrame) -> dict:
    """Advancers / decliners / unchanged on the latest session."""
    if closes.shape[0] < 2:
        return {"advancers": 0, "decliners": 0, "unchanged": 0, "ratio": None}
    change = closes.iloc[-1] / closes.iloc[-2] - 1.0
    change = change.replace([np.inf, -np.inf], np.nan).dropna()
    advancers = int((change > 0).sum())
    decliners = int((change < 0).sum())
    unchanged = int((change == 0).sum())
    total = advancers + decliners
    return {
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "ratio": round(advancers / total, 2) if total else None,
    }


def net_breadth_series(closes: pd.DataFrame, lookback_sessions: int = 504) -> pd.Series:
    """Daily (% advancing - % declining) across the constituent panel."""
    change = closes.pct_change(fill_method=None)
    tail = change.tail(lookback_sessions)
    advancing = (tail > 0).sum(axis=1)
    declining = (tail < 0).sum(axis=1)
    counted = advancing + declining
    net = (advancing - declining) / counted.replace(0, np.nan) * 100.0
    return net.dropna()


def pct_above_moving_average(closes: pd.DataFrame, window: int) -> float | None:
    """Share of names trading above their own ``window``-day simple average."""
    if closes.shape[0] < window:
        return None
    sma = closes.rolling(window, min_periods=window).mean().iloc[-1]
    last = closes.iloc[-1]
    pair = pd.concat([last, sma], axis=1, keys=["last", "sma"]).dropna()
    if pair.empty:
        return None
    return float((pair["last"] > pair["sma"]).mean() * 100.0)


def sma_slope_pct(closes: pd.Series, *, sma_window: int = 200, lookback: int = 20) -> float | None:
    """Percent change in the SMA200 itself over ``lookback`` sessions.

    This measures whether the trend line is turning, which is a different
    question from whether price is above it.
    """
    clean = closes.dropna()
    if len(clean) < sma_window + lookback:
        return None
    sma = clean.rolling(sma_window, min_periods=sma_window).mean().dropna()
    if len(sma) < lookback + 1:
        return None
    start = float(sma.iloc[-(lookback + 1)])
    end = float(sma.iloc[-1])
    if start == 0:
        return None
    return float((end / start - 1.0) * 100.0)


def rebase_to_100(closes: pd.DataFrame, trading_days: int) -> pd.DataFrame:
    window = closes.tail(trading_days + 1).dropna(axis=1, how="any")
    if window.empty:
        return window
    return window / window.iloc[0] * 100.0
