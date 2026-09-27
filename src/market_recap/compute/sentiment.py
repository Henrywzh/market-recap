"""A self-computed Fear & Greed gauge after CNN's seven components.

CNN publishes its method only in outline: seven indicators, each scored by
how far it sits from its average relative to how far it normally strays,
then weighted equally into 0 (extreme fear) to 100 (extreme greed). This
module follows that outline with the site's own data and says where it has
to differ:

- each component is z-scored against its own trailing year (252
  observations, at least 126) and mapped to 0-100 through the normal CDF,
  flipped where a high reading is fear (put/call, VIX, junk spread);
- stock price strength counts S&P 500 members at 52-week highs and lows, not
  the whole NYSE;
- breadth is a McClellan summation index of S&P 500 advances and declines by
  count -- CNN's uses NYSE volume, which this build does not have;
- junk bond demand is the ICE BofA high-yield OAS less the investment-grade
  OAS, and safe-haven demand is the S&P 500's 20-day return less IEF's.

The result will sit near CNN's number, not on it. It is labelled as
self-computed wherever it appears.
"""

from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd

WINDOW = 252
MIN_PERIODS = 126
MIN_COMPONENTS = 6
# Days a component's last score is carried onto the index calendar: FRED and
# Cboe keep holidays the equity calendar does not.
CARRY_DAYS = 5

# key, label, whether a high reading is fear
COMPONENTS = [
    ("momentum", "Market momentum · SPX vs 125-day average", False),
    ("strength", "Stock price strength · 52-week highs − lows", False),
    ("breadth", "Stock price breadth · McClellan summation", False),
    ("put_call", "Put/call options · 5-day total", True),
    ("volatility", "Market volatility · VIX vs 50-day average", True),
    ("safe_haven", "Safe-haven demand · stocks − Treasuries, 20 days", False),
    ("junk_bond", "Junk bond demand · HY − IG spread", True),
]
BANDS = [(25, "EXTREME FEAR"), (45, "FEAR"), (55, "NEUTRAL"), (75, "GREED"), (100.1, "EXTREME GREED")]

_cdf = np.vectorize(lambda z: 0.5 * (1.0 + erf(z / sqrt(2.0))) if np.isfinite(z) else np.nan)


def _clean(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    out.index = pd.to_datetime(out.index)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.replace([np.inf, -np.inf], np.nan).dropna()


def rating(score: float | None) -> str | None:
    if score is None or not np.isfinite(score):
        return None
    return next(label for bound, label in BANDS if score < bound)


def score(series: pd.Series, *, fear_when_high: bool, window: int = WINDOW, min_periods: int = MIN_PERIODS) -> pd.Series:
    """0-100: the normal CDF of the z-score against the trailing window."""
    s = _clean(series)
    mean = s.rolling(window, min_periods=min_periods).mean()
    std = s.rolling(window, min_periods=min_periods).std(ddof=1)
    z = ((s - mean) / std.replace(0, np.nan)).dropna()
    out = pd.Series(100.0 * _cdf(z.to_numpy(dtype=float)), index=z.index, dtype=float)
    return (100.0 - out) if fear_when_high else out


# --- raw components ---------------------------------------------------------------

def momentum(close: pd.Series, window: int = 125) -> pd.Series:
    c = _clean(close)
    return (c / c.rolling(window, min_periods=window).mean() - 1).mul(100).dropna()


def strength(closes: pd.DataFrame, window: int = 252) -> pd.Series:
    """Members at a 52-week high less members at a 52-week low, % of members."""
    high = closes.rolling(window, min_periods=int(window * 0.9)).max()
    low = closes.rolling(window, min_periods=int(window * 0.9)).min()
    valid = closes.notna() & high.notna()
    counted = valid.sum(axis=1)
    net = ((closes >= high) & valid).sum(axis=1) - ((closes <= low) & valid).sum(axis=1)
    return (net / counted.replace(0, np.nan) * 100).dropna()


def mcclellan_summation(closes: pd.DataFrame) -> pd.Series:
    """Summation of the ratio-adjusted McClellan oscillator (19/39-day EMAs of
    net advances as a share of names that moved), by count of members."""
    change = closes.pct_change(fill_method=None)
    adv, dec = (change > 0).sum(axis=1), (change < 0).sum(axis=1)
    moved = (adv + dec).replace(0, np.nan)
    rana = ((adv - dec) / moved * 1000).dropna()
    oscillator = rana.ewm(span=19, adjust=False).mean() - rana.ewm(span=39, adjust=False).mean()
    return oscillator.cumsum()


def vs_average(series: pd.Series, window: int = 50) -> pd.Series:
    s = _clean(series)
    return (s / s.rolling(window, min_periods=window).mean() - 1).mul(100).dropna()


def safe_haven(stocks: pd.Series, bonds: pd.Series, window: int = 20) -> pd.Series:
    pair = pd.concat([_clean(stocks), _clean(bonds)], axis=1, keys=["s", "b"]).dropna()
    return ((pair["s"] / pair["s"].shift(window) - 1) - (pair["b"] / pair["b"].shift(window) - 1)).mul(100).dropna()


def junk_spread(hy_oas: pd.Series, ig_oas: pd.Series) -> pd.Series:
    pair = pd.concat([_clean(hy_oas), _clean(ig_oas)], axis=1, keys=["hy", "ig"]).dropna()
    return (pair["hy"] - pair["ig"]).mul(100).dropna()   # FRED serves percent; bp here


# --- the gauge --------------------------------------------------------------------

def gauge(raw: dict[str, pd.Series], calendar: pd.DatetimeIndex, *, history_sessions: int = WINDOW) -> dict:
    """Component scores and their equal-weighted mean on ``calendar``.

    A day needs at least MIN_COMPONENTS scored components; the count is kept
    so the page can say when one was missing.
    """
    calendar = pd.DatetimeIndex(calendar).sort_values()
    scores, components = {}, []
    for key, label, fear_when_high in COMPONENTS:
        series = raw.get(key, pd.Series(dtype=float))
        s = score(series, fear_when_high=fear_when_high) if not _clean(series).empty else pd.Series(dtype=float)
        aligned = s.reindex(calendar.union(s.index)).ffill(limit=CARRY_DAYS).reindex(calendar) if not s.empty else pd.Series(np.nan, index=calendar)
        scores[key] = aligned
        clean_raw = _clean(series)
        last = aligned.dropna()
        components.append({
            "key": key, "label": label, "fear_when_high": fear_when_high,
            "value": None if clean_raw.empty else round(float(clean_raw.iloc[-1]), 2),
            "date": None if clean_raw.empty else clean_raw.index[-1].strftime("%Y-%m-%d"),
            "score": None if last.empty else round(float(last.iloc[-1]), 1),
            "rating": None if last.empty else rating(float(last.iloc[-1])),
        })
    frame = pd.DataFrame(scores, index=calendar)
    counted = frame.notna().sum(axis=1)
    composite = frame.mean(axis=1).where(counted >= MIN_COMPONENTS).dropna()
    if composite.empty:
        return {"score": None, "rating": None, "components": components, "history": {"dates": [], "score": []}}
    tail = composite.tail(history_sessions)
    now = float(composite.iloc[-1])

    def ago(days: int) -> float | None:
        prior = composite[composite.index <= composite.index[-1] - pd.Timedelta(days=days)]
        return round(float(prior.iloc[-1]), 1) if not prior.empty else None

    return {
        "score": round(now, 1), "rating": rating(now),
        "date": composite.index[-1].strftime("%Y-%m-%d"),
        "components_counted": int(counted.loc[composite.index[-1]]),
        "week_ago": ago(7), "month_ago": ago(30), "year_ago": ago(365),
        "components": components,
        "history": {"dates": [d.strftime("%Y-%m-%d") for d in tail.index], "score": [round(float(v), 1) for v in tail]},
    }
