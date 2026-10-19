"""How much risk the market is pricing: one reading per series, never a score.

Every tile is one series with its own threshold, written in
``config/dashboard.toml`` before the series was drawn (principle 5 of
docs/information_architecture.md). A tile reports its level, where that level
sits in its last year and in all the history the source serves, its change
over a week and a month, and whether it is past its threshold -- and whether
it crossed it within the last week, which is what BRIEF lists as changed.

The derived series (term-structure ratios, realised volatility, realised
correlation and dispersion of the index members, net liquidity) are built
here from their inputs; nothing is combined across tiles.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RV_WINDOW = 20
CORR_WINDOW = 21
CREDIT_TREND_WINDOW = 50
LIQUIDITY_CHANGE_WEEKS = 13
PUT_CALL_SMOOTHING = 5
# A weekly history is drawn for charts; ten years of it.
HISTORY_YEARS = 10
# The chart's last year is drawn from daily observations; ``history`` stays
# weekly, as the MOVE/VIX ratio's percentile on OVERVIEW is taken over it.
RECENT_DAYS = 365
SPARK_POINTS = 130
EXTREME_DEFAULT_PCT = 5.0


def _clean(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    out.index = pd.to_datetime(out.index)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.replace([np.inf, -np.inf], np.nan).dropna()


# --- derived series ---------------------------------------------------------------

def ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    frame = pd.concat([_clean(a), _clean(b)], axis=1, join="inner").dropna()
    return (frame.iloc[:, 0] / frame.iloc[:, 1].where(frame.iloc[:, 1] != 0)).dropna()


def realised_vol(close: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    """Annualised close-to-close volatility, in vol points."""
    returns = np.log(_clean(close)).diff()
    return (returns.rolling(window, min_periods=window).std() * np.sqrt(TRADING_DAYS) * 100).dropna()


def vs_moving_average(series: pd.Series, window: int) -> pd.Series:
    """Percent above (+) or below (-) its own moving average."""
    clean = _clean(series)
    average = clean.rolling(window, min_periods=window).mean()
    return (100 * (clean / average - 1)).dropna()


def drawdown_from_high(close: pd.Series, window: int = TRADING_DAYS) -> pd.Series:
    clean = _clean(close)
    high = clean.rolling(window, min_periods=1).max()
    return (100 * (clean / high - 1)).dropna()


def share_above_average(closes: pd.DataFrame, window: int = 200) -> pd.Series:
    """Percent of members above their own moving average, among members with one."""
    average = closes.rolling(window, min_periods=window).mean()
    known = average.notna() & closes.notna()
    above = (closes > average) & known
    count = known.sum(axis=1)
    return (100 * above.sum(axis=1) / count.where(count > 0)).dropna()


def correlation_and_dispersion(closes: pd.DataFrame, weights: pd.Series,
                               window: int = CORR_WINDOW) -> tuple[pd.Series, pd.Series]:
    """Realised average correlation and dispersion of the index members.

    From the members' own daily returns over ``window`` sessions, weighted by
    today's official weights (renormalised over members with a full window):

        correlation = (s_I^2 - sum w^2 s^2) / ((sum w s)^2 - sum w^2 s^2)
        dispersion  = sqrt(sum w s^2 - s_I^2), annualised, in vol points

    where s_I is the volatility of the weighted basket. The first is the
    realised counterpart of Cboe's implied correlation (COR1M); the second of
    its dispersion index.
    """
    returns = np.log(closes).diff()
    w = weights.reindex(closes.columns).fillna(0.0)
    sigma = returns.rolling(window, min_periods=window).std()
    have = sigma.notna()
    weight = have.mul(w, axis=1)
    total = weight.sum(axis=1)
    weight = weight.div(total.where(total > 0), axis=0)
    # Today's weights applied to each day's member returns; a member with no
    # return that day contributes nothing and the rest are renormalised.
    live = returns.notna().mul(w, axis=1)
    live_total = live.sum(axis=1)
    basket = (returns.fillna(0.0).mul(w, axis=1).sum(axis=1) / live_total.where(live_total > 0))
    sigma_index = basket.rolling(window, min_periods=window).std()
    s = sigma.fillna(0.0)
    sum_ws = (weight * s).sum(axis=1)
    sum_w2s2 = (weight ** 2 * s ** 2).sum(axis=1)
    sum_ws2 = (weight * s ** 2).sum(axis=1)
    corr = (sigma_index ** 2 - sum_w2s2) / (sum_ws ** 2 - sum_w2s2).where((sum_ws ** 2 - sum_w2s2) > 0)
    disp = np.sqrt((sum_ws2 - sigma_index ** 2).clip(lower=0)) * np.sqrt(TRADING_DAYS) * 100
    valid = total > 0.5  # at least half the index by weight has a full window
    return corr.where(valid).dropna().clip(-1, 1), disp.where(valid).dropna()


def net_liquidity(assets: pd.Series, tga: pd.Series, rrp: pd.Series) -> pd.Series:
    """Fed total assets - Treasury General Account - reverse repo, in $bn.

    WALCL and WTREGEN are weekly (Wednesday) in $mn; RRPONTSYD is daily in $bn.
    Read on each Wednesday of the balance sheet, with the reverse repo of the
    same day (or the last one before it).
    """
    a = _clean(assets) / 1000
    t = _clean(tga).reindex(a.index, method="ffill") / 1000
    r = _clean(rrp).reindex(a.index.union(_clean(rrp).index)).ffill().reindex(a.index)
    return (a - t - r.fillna(0.0)).dropna()


def change_over(series: pd.Series, periods: int) -> pd.Series:
    clean = _clean(series)
    return (clean - clean.shift(periods)).dropna()


def pct_change_over(series: pd.Series, periods: int) -> pd.Series:
    """Percent change over ``periods`` observations."""
    clean = _clean(series)
    return ((clean / clean.shift(periods) - 1) * 100).dropna()


def excess_cape_yield(spx: pd.Series, gs10: pd.Series, shiller: pd.DataFrame) -> pd.Series:
    """Shiller's excess CAPE yield, each session: 1/CAPE less the real 10-year rate, in %.

    His own monthly figure is 100 / CAPE - (GS10 - the CPI's ten-year annualised
    change), which this reproduces exactly at his month's average price. A
    session reads its month's row (or the latest one before it): CAPE scaled by
    the day's close against that month's average price, and the day's 10-year
    yield less that month's inflation.
    """
    rows = shiller[["price", "cape", "infl_10y"]].dropna()
    days = pd.concat([_clean(spx).rename("spx"), _clean(gs10).rename("gs10")], axis=1).dropna()
    if rows.empty or days.empty:
        return pd.Series(dtype=float)
    month = rows.reindex(days.index.union(rows.index)).ffill().reindex(days.index)
    cape = month["cape"] * days["spx"] / month["price"]
    return (100 / cape - (days["gs10"] - month["infl_10y"])).dropna()


def smoothed(series: pd.Series, window: int) -> pd.Series:
    return _clean(series).rolling(window, min_periods=window).mean().dropna()


# --- one tile -------------------------------------------------------------------------

def _value_at(series: pd.Series, when: pd.Timestamp) -> float | None:
    before = series[series.index <= when]
    return float(before.iloc[-1]) if not before.empty else None


def _percentile(sample: pd.Series, value: float) -> float | None:
    if sample.empty:
        return None
    return float((sample <= value).mean() * 100)


def breach(value: float | None, *, risk_when: str, threshold: float | None,
           percentile: float | None = None) -> bool | None:
    """Whether a reading is on the risk side of its configured line.

    ``extreme`` series (positioning, sentiment) are read at either tail of
    their own history: ``threshold`` is then the tail size in percent.
    """
    if value is None:
        return None
    if risk_when == "extreme":
        if percentile is None:
            return None
        tail = threshold if threshold is not None else EXTREME_DEFAULT_PCT
        return percentile <= tail or percentile >= 100 - tail
    if threshold is None:
        return None
    return value >= threshold if risk_when == "high" else value <= threshold


def _weekly(series: pd.Series, years: int) -> pd.Series:
    start = series.index[-1] - pd.DateOffset(years=years)
    recent = series[series.index >= start]
    return recent.groupby(recent.index.to_period("W-FRI")).last()


def tile(series: pd.Series, *, risk_when: str, threshold: float | None, digits: int = 2,
         daily: bool = True) -> dict:
    """Level, percentiles, changes and threshold state of one series.

    ``daily``: the source publishes every session, so the change since the
    previous observation is a one-session change and the last year is kept
    day by day. A weekly series gets neither.
    """
    clean = _clean(series)
    if clean.empty:
        return {"value": None, "date": None}
    last_date = clean.index[-1]
    value = float(clean.iloc[-1])
    year = clean[clean.index > last_date - timedelta(days=365)]
    pct_1y = _percentile(year, value)
    pct_long = _percentile(clean, value)
    week_ago = _value_at(clean, last_date - timedelta(days=7))
    month_ago = _value_at(clean, last_date - timedelta(days=30))
    now = breach(value, risk_when=risk_when, threshold=threshold, percentile=pct_long)
    before = None
    if week_ago is not None:
        prior = clean[clean.index <= last_date - timedelta(days=7)]
        before = breach(week_ago, risk_when=risk_when, threshold=threshold,
                        percentile=_percentile(prior, week_ago))
    crossed = None
    if now is not None and before is not None and now != before:
        crossed = "into" if now else "out"
    step = max(1, len(year) // SPARK_POINTS)
    spark = year.iloc[::-step][::-1] if step > 1 else year
    weekly = _weekly(clean, HISTORY_YEARS)
    round_ = lambda v: None if v is None or not np.isfinite(v) else round(float(v), digits)
    previous = clean.iloc[-2] if daily and len(clean) > 1 else None
    recent = clean[clean.index > last_date - timedelta(days=RECENT_DAYS)] if daily else None
    return {
        "value": round_(value),
        "date": last_date.strftime("%Y-%m-%d"),
        "pct_1y": None if pct_1y is None else round(pct_1y),
        "pct_long": None if pct_long is None else round(pct_long),
        "since": clean.index[0].strftime("%Y-%m-%d"),
        "observations": int(len(clean)),
        "change_1d": round_(value - float(previous)) if previous is not None else None,
        "previous_date": clean.index[-2].strftime("%Y-%m-%d") if previous is not None else None,
        "change_1w": round_(value - week_ago) if week_ago is not None else None,
        "change_1m": round_(value - month_ago) if month_ago is not None else None,
        "breach": now,
        "crossed": crossed,
        "spark": [round_(v) for v in spark.to_numpy()],
        "history": {
            "dates": [p.end_time.strftime("%Y-%m-%d") for p in weekly.index],
            "values": [round_(v) for v in weekly.to_numpy()],
        },
        "recent": None if recent is None else {
            "dates": [d.strftime("%Y-%m-%d") for d in recent.index],
            "values": [round_(v) for v in recent.to_numpy()],
        },
    }


def term_structure(points: dict[str, pd.Series], *, lags_days: tuple[int, ...] = (0, 7, 30)) -> dict:
    """A curve across tenors (label -> series), today and ``lags_days`` ago."""
    labels = list(points)
    last = max((_clean(s).index[-1] for s in points.values() if not _clean(s).empty), default=None)
    if last is None:
        return {"labels": labels, "curves": []}
    curves = []
    for lag in lags_days:
        when = last - timedelta(days=lag)
        values = [_value_at(_clean(points[label]), when) for label in labels]
        curves.append({
            "lag_days": lag,
            "date": when.strftime("%Y-%m-%d"),
            "values": [None if v is None else round(v, 2) for v in values],
        })
    return {"labels": labels, "curves": curves}


# --- the matrix: one lead series per cell -----------------------------------------
#
# A cell is coloured by its lead alone, never averaged with another, on one of
# three scales its config names. "bands": fixed lines set from past drawdowns
# (quantamental-lab docs/risk_matrix_bands_v1.md), for series whose level has a
# meaning of its own (VIX 35 is stress in any decade). "percentile": where the
# lead sits in its own last ten years, for changes and spreads with no outside
# anchor. "none": shown, not coloured (a lead that failed its test). The
# percentile is reported on every scale, as a description. "valuation": how
# thin the compensation is, by its percentile in the lead's whole history from
# `since` (not ten years: a decade of zero rates would set the norm), read as
# cheap / fair / rich / very rich. A valuation reading describes the cushion,
# not the timing: it does not separate the next three months' drawdowns
# (quantamental-lab docs/erp_history_v1.md).

def risk_percentile(series: pd.Series, value: float, risk_when: str) -> float | None:
    """Where ``value`` sits in ``series``, 0-100, in the risk direction.

    ``high``: the share of the sample at or below the value. ``low``: the share
    at or above it. ``extreme``: distance from the median, so both tails read
    high (2 * |pct - 50|). Ties count as at-or-below / at-or-above.
    """
    clean = _clean(series)
    if clean.empty or value is None or not np.isfinite(value):
        return None
    below = 100 * float((clean <= value).mean())
    if risk_when == "high":
        return below
    if risk_when == "low":
        return 100 * float((clean >= value).mean())
    if risk_when == "extreme":
        return 2 * abs(below - 50)
    raise ValueError(f"unknown risk_when {risk_when!r}")


def cell_state(pct: float | None, thresholds: dict) -> str:
    """calm below the elevated line, elevated up to the stressed line, stressed from it on."""
    if pct is None:
        return "grey"
    if pct >= thresholds["stressed"]:
        return "stressed"
    if pct >= thresholds["elevated"]:
        return "elevated"
    return "calm"


def band_state(value: float | None, bands: dict, risk_when: str) -> str:
    """calm short of the elevated line, elevated up to the stressed line, stressed from it on.

    A ``low`` series crosses a line by falling to it, a ``high`` one by rising to it.
    """
    if value is None or not np.isfinite(value):
        return "grey"
    sign = -1 if risk_when == "low" else 1
    if sign * value >= sign * bands["stressed"]:
        return "stressed"
    if sign * value >= sign * bands["elevated"]:
        return "elevated"
    return "calm"


def valuation_state(pct: float | None, thresholds: dict) -> str:
    """A thin-premium percentile in words: rich from the 75th, very rich from the 90th, cheap to the 25th."""
    if pct is None:
        return "grey"
    if pct >= thresholds["very_rich"]:
        return "very_rich"
    if pct >= thresholds["rich"]:
        return "rich"
    if pct <= thresholds["cheap"]:
        return "cheap"
    return "fair"


def _last_years(series: pd.Series, years: int) -> pd.Series:
    """The observations in the ``years`` up to and including the last one."""
    return series[series.index > series.index[-1] - pd.DateOffset(years=years)]


def _observation_state(clean: pd.Series, *, risk_when: str, years: int, min_years: float,
                       thresholds: dict, scale: str = "percentile", bands: dict | None = None,
                       since: str | None = None, valuation: dict | None = None) -> tuple[float | None, str]:
    """Percentile and state of the last observation.

    The percentile needs ``min_years`` of history before that observation; a
    fixed band does not, as its lines were set elsewhere.
    """
    last = clean.index[-1]
    value = float(clean.iloc[-1])
    long_enough = (last - clean.index[0]).days / 365.25 >= min_years
    if scale == "valuation":
        window = clean[clean.index >= pd.Timestamp(since)] if since else clean
        pct = risk_percentile(window, value, risk_when) if long_enough else None
        return pct, valuation_state(pct, valuation)
    pct = risk_percentile(_last_years(clean, years), value, risk_when) if long_enough else None
    if scale == "bands":
        return pct, band_state(value, bands, risk_when)
    if scale == "none":
        return pct, "unrated"
    return pct, cell_state(pct, thresholds)


def _month_change(clean: pd.Series, *, risk_when: str, years: int) -> tuple[float | None, bool | None]:
    """The change over the last month, and whether it moved toward risk.

    The base is the last observation at least 30 calendar days earlier. For an
    ``extreme`` series "toward risk" means further from the ten-year median.
    """
    last = clean.index[-1]
    value = float(clean.iloc[-1])
    before = _value_at(clean, last - timedelta(days=30))
    if before is None:
        return None, None
    change = value - before
    if risk_when == "high":
        return change, change > 0
    if risk_when == "low":
        return change, change < 0
    median = float(_last_years(clean, years).median())
    return change, abs(value - median) > abs(before - median)


def matrix_reading(series: pd.Series, *, risk_when: str, as_of: str | None, years: int,
                   min_years: float, stale_days: int, thresholds: dict, scale: str = "percentile",
                   bands: dict | None = None, since: str | None = None, valuation: dict | None = None) -> dict:
    """One matrix cell's reading from its lead series, on its ``scale``.

    Grey (no percentile, state, change or previous state) when the series is
    empty, its last observation is older than ``stale_days`` before ``as_of``,
    or, on the percentile scale, it has less than ``min_years`` of history. The
    value and date still show so the page can say what the last reading was.
    """
    clean = _clean(series)
    reading = {"value": None, "date": None, "percentile": None, "state": "grey", "state_prev": None,
               "change_1m": None, "worse_1m": None, "years_used": None}
    if clean.empty:
        return reading
    last = clean.index[-1]
    reading["value"] = float(clean.iloc[-1])
    reading["date"] = last.strftime("%Y-%m-%d")
    stale = as_of is not None and (pd.Timestamp(as_of) - last).days > stale_days
    how = {"risk_when": risk_when, "years": years, "min_years": min_years, "thresholds": thresholds,
           "scale": scale, "bands": bands, "since": since, "valuation": valuation}
    pct, state = _observation_state(clean, **how)
    if stale or state == "grey":
        return reading
    reading["state"] = state
    if pct is not None:
        reading["percentile"] = round(pct, 1)
        # The span the percentile was read over: up to ``years`` (a valuation
        # reading: from ``since``), less where the source is shorter.
        if scale == "valuation":
            start = clean.index[0] if not since else max(clean.index[0], pd.Timestamp(since))
            reading["years_used"] = round((last - start).days / 365.25, 1)
        else:
            window = clean[clean.index >= last - pd.DateOffset(years=years)]
            reading["years_used"] = round(min(years, (last - window.index[0]).days / 365.25), 1)
    if len(clean) > 1:
        # The same test one observation earlier: the window ends there.
        reading["state_prev"] = _observation_state(clean.iloc[:-1], **how)[1]
    change, worse = _month_change(clean, risk_when=risk_when, years=years)
    reading["change_1m"], reading["worse_1m"] = change, worse
    return reading
