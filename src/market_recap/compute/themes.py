"""THEMES: bellwether impact, report-date projection and data due dates.

A theme's proxy is an ETF where one isolates it, otherwise an equal-weight
basket of its members. A bellwether's impact is scored like EVENTS'
read-through (compute.events.co_move): the proxy's move beyond the S&P 500
on the bellwether's own reaction sessions, per 1% of the bellwether's
excess move. When the bellwether is itself in a basket, it is left out of
the basket for its own score; an ETF cannot be split that way, so an ETF's
score includes the bellwether's own weight in it, and the page says so.
"""

from __future__ import annotations

from datetime import date, timedelta
import re
import statistics

import pandas as pd

GAP_BOUNDS = (80, 100)


def basket_excess(excess: pd.DataFrame, members: list[str], leave_out: str | None = None) -> pd.Series:
    """Equal-weight mean of the members' daily excess moves."""
    cols = [m for m in members if m in excess.columns and m != leave_out]
    return excess[cols].mean(axis=1, skipna=True) if cols else pd.Series(dtype=float)


def project_next(past: list[date], as_of: date) -> date | None:
    """The next report from the median gap between past ones, clipped to a
    quarter's range, rolled forward past ``as_of``."""
    past = sorted(set(past))
    if len(past) < 2:
        return None
    gap = int(min(max(statistics.median((b - a).days for a, b in zip(past, past[1:])), GAP_BOUNDS[0]), GAP_BOUNDS[1]))
    nxt = past[-1] + timedelta(days=gap)
    while nxt <= as_of:
        nxt += timedelta(days=gap)
    return nxt


def monthly_due(latest_month: str | None, day_of_month: int, as_of: date) -> dict | None:
    """When the month after ``latest_month`` is due (published by
    ``day_of_month`` of the month after it), and whether it is late."""
    if not latest_month:
        return None
    year, month = (int(p) for p in latest_month.split("-"))
    month += 1
    if month == 13:
        year, month = year + 1, 1
    pub_year, pub_month = (year, month + 1) if month < 12 else (year + 1, 1)
    due = date(pub_year, pub_month, day_of_month)
    return {"month": f"{year:04d}-{month:02d}", "due": due.isoformat(), "late": as_of > due}


def run_in(series: pd.Series, market: pd.Series) -> dict:
    """1M and 3M return of a price series and against the S&P 500."""
    out = {}
    s, m = series.dropna(), market.dropna()
    for label, n in (("1m", 21), ("3m", 63)):
        if len(s) > n and len(m) > n:
            r = 100 * (s.iloc[-1] / s.iloc[-1 - n] - 1)
            rm = 100 * (m.iloc[-1] / m.iloc[-1 - n] - 1)
            out[f"ret_{label}"] = round(float(r), 2)
            out[f"vs_spx_{label}"] = round(float(r - rm), 2)
    return out


def basket_index(closes: pd.DataFrame, members: list[str]) -> pd.Series:
    """Equal-weight index of the members' closes (daily rebalanced), = 100 at start."""
    cols = [m for m in members if m in closes.columns]
    returns = closes[cols].pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0)
    return 100 * (1 + returns).cumprod()


def yoy_monthly(rows: list[dict], value: str) -> list[dict]:
    """Adds y/y growth to monthly rows keyed by 'YYYY-MM'."""
    by_month = {r["month"]: r for r in rows}
    out = []
    for r in rows:
        y, m = (int(p) for p in r["month"].split("-"))
        prior = by_month.get(f"{y - 1:04d}-{m:02d}")
        yoy = round(100 * (r[value] / prior[value] - 1), 1) if prior and prior.get(value) and r.get(value) is not None else None
        out.append({**r, "yoy_pct": r.get("yoy_pct") if r.get("yoy_pct") is not None else yoy})
    return out


# --- What moves a basket ------------------------------------------------------------

def sensitivity(excess: pd.Series, driver: pd.Series, *, sessions: int = 252, min_sessions: int = 150) -> dict | None:
    """How a name's daily excess return has moved with a driver's daily change
    over the last ``sessions``: beta (excess % per unit of driver change),
    correlation, and the sessions both had."""
    both = pd.concat([excess.rename("y"), driver.rename("x")], axis=1).dropna().iloc[-sessions:]
    if len(both) < min_sessions or both["x"].var() == 0:
        return None
    beta = float(both["x"].cov(both["y"]) / both["x"].var())
    return {"beta": round(beta, 3), "corr": round(float(both["x"].corr(both["y"])), 2), "n": int(len(both))}


def crack_321(crude: pd.Series, gasoline: pd.Series, heating_oil: pd.Series) -> pd.Series:
    """The 3-2-1 crack, $/bbl: two barrels of gasoline and one of heating oil
    (quoted $/gal, 42 gal a barrel) less three barrels of crude, per barrel."""
    return ((2 * gasoline * 42 + heating_oil * 42 - 3 * crude) / 3).dropna()


# A forecast must cover this share of the releases for the study to be scored
# on it rather than on the trend.
FORECAST_COVERAGE = 0.7


def release_study(releases: pd.DataFrame, excess: pd.Series, *, headline: str, trend: int = 12, min_trend: int = 6,
                  recent: int = 8, forecasts: pd.DataFrame | None = None) -> dict | None:
    """How a theme's proxy moved, beyond the S&P 500, on the session of each
    release of one series.

    ``releases``: one row per release -- released (the day), value (the new
    print as first published) and prior (its predecessor as known that day).
    ``headline``: 'pct' (the change in percent, as a level series reports it)
    or 'diff' (the change in units). With no free history of consensus, the
    surprise is the headline less the median of the ``trend`` headlines before
    it -- an above-trend print, not a beat.

    ``forecasts`` (tv_surprises' frame), when it covers most releases, puts
    the real surprise -- actual less the published forecast -- in the
    trend's place, matched by release day (up to two days later: a holiday
    week moves a weekly report), and its day becomes the release's.

    The session is the first one on or after the release day: these all come
    out before or during the session they move. Every other session in the
    same span is the baseline, so ``attention`` near 1 means the release day
    looks like any other day for the proxy."""
    move = excess.dropna()
    if move.empty or releases.empty:
        return None
    sessions = move.index
    rows = []
    by_day = forecasts.set_index("released") if forecasts is not None and not forecasts.empty else None
    for r in releases.sort_values("released").itertuples(index=False):
        if r.prior is None or pd.isna(r.prior) or (headline == "pct" and not r.prior):
            continue
        day, real = pd.Timestamp(r.released), None
        if by_day is not None:
            near = by_day.loc[day - pd.Timedelta(days=1):day + pd.Timedelta(days=2)]
            if not near.empty:
                day, real = near.index[0], float(near["surprise"].iloc[0])
        at = sessions.searchsorted(day)
        if at >= len(sessions) or (sessions[at] - day).days > 3:
            continue
        value = (r.value / r.prior - 1) * 100 if headline == "pct" else r.value - r.prior
        rows.append({"period": pd.Timestamp(r.date).strftime("%Y-%m-%d"), "released": day.strftime("%Y-%m-%d"),
                     "session": sessions[at], "headline": value, "move": float(move.iloc[at]), "vs_forecast": real})
    if not rows:
        return None
    frame = pd.DataFrame(rows).drop_duplicates("session", keep="last").reset_index(drop=True)
    base = frame["headline"].shift(1).rolling(trend, min_periods=min_trend).median()
    frame["vs_trend"] = frame["headline"] - base
    covered = int(frame["vs_forecast"].notna().sum())
    basis = "forecast" if covered >= FORECAST_COVERAGE * len(frame) else "trend"
    frame["surprise"] = frame["vs_forecast"] if basis == "forecast" else frame["vs_trend"]
    scored = frame.dropna(subset=["surprise"])
    span = move.loc[frame["session"].min():]
    other = span.drop(index=frame["session"], errors="ignore")
    release_abs, other_abs = float(frame["move"].abs().mean()), float(other.abs().mean()) if len(other) else None
    above, below = scored[scored["surprise"] > 0], scored[scored["surprise"] < 0]
    share = lambda part: None if part.empty else round(float((part["move"] > 0).mean()) * 100)  # noqa: E731
    varied = scored["surprise"].nunique() > 1 and scored["move"].nunique() > 1      # no spread: no correlation to read
    corr = scored["surprise"].rank().corr(scored["move"].rank()) if len(scored) >= 12 and varied else None
    tail = frame.iloc[-recent:][::-1]
    return {
        "n": int(len(frame)), "scored": int(len(scored)), "since": frame["released"].iloc[0],
        "basis": basis, "with_forecast": covered,
        "abs_move": round(release_abs, 2), "abs_other": None if other_abs is None else round(other_abs, 2),
        "attention": None if not other_abs else round(release_abs / other_abs, 2),
        "corr": None if corr is None or pd.isna(corr) else round(float(corr), 2),
        "up_above": share(above), "n_above": int(len(above)), "up_below": share(below), "n_below": int(len(below)),
        "recent": [{"period": r["period"], "released": r["released"], "headline": round(float(r["headline"]), 3),
                    "surprise": None if pd.isna(r["surprise"]) else round(float(r["surprise"]), 3), "move": round(r["move"], 2),
                    "vs_trend": None if pd.isna(r["vs_trend"]) else round(float(r["vs_trend"]), 3),
                    "vs_forecast": None if r["vs_forecast"] is None or pd.isna(r["vs_forecast"]) else round(float(r["vs_forecast"]), 3)}
                   for _, r in tail.iterrows()],
    }


def tv_surprises(rows: list[dict], title: str, mode: str) -> pd.DataFrame:
    """Each release of one TradingView calendar line: its day in New York,
    actual, forecast and surprise. ``mode`` 'diff': actual less forecast, in
    the line's own unit (pp for a % change, thousands for claims); 'pct': the
    actual's distance from the forecast in percent, for a level whose scale
    TradingView has changed over the years (housing starts in millions, then
    thousands). Rows without both numbers are left out."""
    pattern = re.compile(title, re.I)
    out = []
    for r in rows:
        if not pattern.search((r.get("title") or "").strip()):
            continue
        actual, forecast = r.get("actual"), r.get("forecast")
        if actual is None or forecast is None or not r.get("date"):
            continue
        if mode == "pct":
            if not forecast:
                continue
            surprise = (float(actual) / float(forecast) - 1) * 100
        else:
            surprise = float(actual) - float(forecast)
        day = pd.Timestamp(r["date"]).tz_convert("America/New_York").normalize().tz_localize(None)
        out.append({"released": day, "actual": float(actual), "forecast": float(forecast), "surprise": surprise})
    frame = pd.DataFrame(out, columns=["released", "actual", "forecast", "surprise"])
    return frame.drop_duplicates("released", keep="last").sort_values("released").reset_index(drop=True)
