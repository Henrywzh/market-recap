"""OVERVIEW: the one-glance read of the market, and the site's landing page.

Four questions, each answered with a level, its recent changes and a small
line of its last six months: how stocks have done (and how far they sit
from their high), how broad the move is, where rates and credit are, and
what the dollar, commodities, volatility and the latest macro prints say.
Beneath them, the next three sessions and what the Fed is priced to do.

Stocks and breadth come from the build's own closes; nominal yields from
Treasury's daily par curve (published the same evening, so they match the
session); the real yield, credit spreads and macro prints from FRED, a day
later; the cross-asset rows from Yahoo. The Fed line and
the calendar are read from this session's PRICED PATH and CATALYSTS
artifacts; a panel that did not build leaves its line empty rather than
showing another session's numbers.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..compute import periods as P
from ..compute import returns as R
from ..sources import fred, treasury, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

# Panels OVERVIEW reads, all required to be from this session.
INPUTS = ("priced", "catalysts", "risk")
PERIODS = ["1D", "1W", "1M", "YTD"]
SPARK_SESSIONS = 126
SPARK_POINTS = 60
HIGH_WINDOW = 252
BREADTH_WINDOWS = {"1D": 1, "1W": 5, "1M": 21}
# Bucket edges (percent) for the distribution of member returns, per window:
# a month's moves are wider than a day's, so one set of edges would put
# nearly every name in the first bucket or the last.
DISTRIBUTION_EDGES = {"1D": [1, 2, 4], "1W": [2, 5, 10], "1M": [5, 10, 20]}
TIERS = {"high": 0, "medium": 1, "low": 2}

# Stock rows: index levels from the build's index closes, the rest from ETFs.
STOCKS = [
    ("index", "SPX", "S&P 500"),
    ("index", "NDX", "Nasdaq 100"),
    ("etf", "IWM", "Russell 2000 (IWM)"),
    ("etf", "RSP", "S&P 500 equal wt (RSP)"),
]
# Rates and credit. ``unit`` is the display unit of the level; changes are
# always in basis points. Nominal yields come from Treasury's par curve,
# which is published the evening of the session; the rest from FRED.
TREASURY_RATES = [
    ("2Y", "UST 2Y", "pct"),
    ("10Y", "UST 10Y", "pct"),
]
FRED_RATES = [
    ("DFII10", "10Y real (TIPS)", "pct"),
    ("BAMLH0A0HYM2", "High yield OAS", "bp"),
    ("BAMLC0A0CM", "Investment grade OAS", "bp"),
]
CONTRIBUTORS = 5
CROSS_ASSET = [
    ("DX-Y.NYB", "US dollar (DXY)", "pct"),
    ("CL=F", "WTI crude", "pct"),
    ("HG=F", "Copper", "pct"),
    ("GC=F", "Gold", "pct"),
    ("^VIX", "VIX", "pts"),
]
# Macro prints: FRED series, how each is shown, and its unit.
PRINTS = [
    ("CPIAUCSL", "CPI", "yoy", "% y/y"),
    ("PCEPILFE", "Core PCE", "yoy", "% y/y"),
    ("UNRATE", "Unemployment rate", "level", "%"),
    ("PAYEMS", "Payrolls", "diff", "k m/m"),
    ("GDPNOW", "GDPNow (current quarter)", "level", "% saar"),
]


def _spark(series: pd.Series, sessions: int = SPARK_SESSIONS) -> list:
    tail = series.dropna().tail(sessions)
    step = max(1, -(-len(tail) // SPARK_POINTS))
    sampled = tail.iloc[::-step][::-1] if step > 1 else tail
    return [clean_float(v, 4) for v in sampled.to_numpy()]


def _value_days_ago(series: pd.Series, days: int) -> float | None:
    """The last value on or before ``days`` calendar days before the latest."""
    clean = series.dropna()
    if clean.empty:
        return None
    prior = clean[clean.index <= clean.index[-1] - timedelta(days=days)]
    return float(prior.iloc[-1]) if not prior.empty else None


def stock_row(label: str, key: str, series: pd.Series) -> dict:
    clean = series.dropna()
    if clean.empty:
        return {"key": key, "label": label, "last": None}
    high = R.drawdown_from_high(clean.tail(HIGH_WINDOW))
    return {
        "key": key, "label": label,
        "last": clean_float(clean.iloc[-1], 2),
        "date": to_iso_date(clean.index[-1]),
        **{k: clean_float(v, 2) for k, v in R.period_returns(clean, PERIODS).items()},
        "from_high_pct": clean_float(high["drawdown_pct"], 2),
        "high_date": high["high_date"],
        "sessions_since_high": high["trading_days_since_high"],
        "spark": _spark(clean),
    }


def breadth(closes: pd.DataFrame) -> dict:
    """Advancers and decliners over a day, a week and a month; the share
    above the 50- and 200-day averages; and new 52-week highs and lows."""
    closes = closes.dropna(axis=1, how="all")
    out: dict = {"members": int(closes.shape[1])}
    for label, sessions in BREADTH_WINDOWS.items():
        if closes.shape[0] <= sessions:
            out[label] = None
            continue
        change = (closes.iloc[-1] / closes.iloc[-1 - sessions] - 1).replace([np.inf, -np.inf], np.nan).dropna()
        out[label] = {"up": int((change > 0).sum()), "down": int((change < 0).sum())}
    out["above_50d"] = clean_float(R.pct_above_moving_average(closes, 50), 1)
    out["above_200d"] = clean_float(R.pct_above_moving_average(closes, 200), 1)
    if closes.shape[0] >= HIGH_WINDOW:
        window = closes.tail(HIGH_WINDOW)
        last = window.iloc[-1]
        valid = last.notna() & (window.count() >= HIGH_WINDOW * 0.9)
        out["new_highs"] = int(((last >= window.max()) & valid).sum())
        out["new_lows"] = int(((last <= window.min()) & valid).sum())
    else:
        out["new_highs"] = out["new_lows"] = None
    return out


def return_distribution(closes: pd.DataFrame) -> dict:
    """How many members rose and fell by how much, per window: counts in
    buckets bounded by DISTRIBUTION_EDGES (absolute percent, lower edge
    inclusive), mirrored for gains and losses; unchanged names apart."""
    out = {}
    for label, edges in DISTRIBUTION_EDGES.items():
        sessions = BREADTH_WINDOWS[label]
        if closes.shape[0] <= sessions:
            continue
        change = ((closes.iloc[-1] / closes.iloc[-1 - sessions] - 1) * 100).replace([np.inf, -np.inf], np.nan).dropna()
        bounds = [0.0, *edges, np.inf]
        # [lo, hi): the gains and losses passed in are already strictly positive.
        count = lambda values: [int(((values >= lo) & (values < hi)).sum()) for lo, hi in zip(bounds[:-1], bounds[1:])]
        up, down = change[change > 0], -change[change < 0]
        out[label] = {"edges": edges, "up": count(up), "down": count(down), "flat": int((change == 0).sum()),
                      "members": int(change.size)}
    return out


def rate_row(series_id: str, label: str, unit: str, series: pd.Series, source: str = "FRED") -> dict:
    clean = series.dropna()
    if clean.empty:
        return {"key": series_id, "label": label, "unit": unit, "value": None, "source": source}
    # FRED serves yields and spreads in percent; the page shows spreads in bp.
    scale = 100.0 if unit == "bp" else 1.0
    value = float(clean.iloc[-1])

    def change(days: int) -> float | None:
        prior = _value_days_ago(clean, days)
        return None if prior is None else clean_float((value - prior) * 100.0, 1)

    return {
        "key": series_id, "label": label, "unit": unit, "source": source,
        "value": clean_float(value * scale, 2),
        "date": to_iso_date(clean.index[-1]),
        "change_1d_bp": clean_float((value - float(clean.iloc[-2])) * 100.0, 1) if len(clean) >= 2 else None,
        "change_1w_bp": change(7), "change_1m_bp": change(30),
        "spark": _spark(clean * scale),
    }


def cross_row(symbol: str, label: str, unit: str, series: pd.Series) -> dict:
    clean = series.dropna()
    if clean.empty:
        return {"key": symbol, "label": label, "unit": unit, "last": None}
    row = {"key": symbol, "label": label, "unit": unit, "last": clean_float(clean.iloc[-1], 2),
           "date": to_iso_date(clean.index[-1]), "spark": _spark(clean)}
    if unit == "pts":
        # A volatility index moves in points; a percent change of it misleads.
        last = float(clean.iloc[-1])
        sessions = {"1D": 1, "1W": 5, "1M": 21}
        for k, n in sessions.items():
            row[k] = clean_float(last - float(clean.iloc[-1 - n]), 2) if len(clean) > n else None
        ytd = clean[clean.index < pd.Timestamp(year=clean.index[-1].year, month=1, day=1)]
        row["YTD"] = clean_float(last - float(ytd.iloc[-1]), 2) if not ytd.empty else None
    else:
        row |= {k: clean_float(v, 2) for k, v in R.period_returns(clean, PERIODS).items()}
    return row


def equal_vs_cap(equal: pd.Series, cap: pd.Series) -> dict | None:
    """RSP less SPY: the return gap over 1M, 3M and YTD in percentage points
    (both total return, so dividends do not tilt it)."""
    pair = pd.concat([equal, cap], axis=1, keys=["eq", "cap"]).dropna()
    if len(pair) < 30:
        return None
    gaps = {}
    for label in ("1M", "3M", "YTD"):
        eq = R.period_returns(pair["eq"], [label]).get(label)
        cap = R.period_returns(pair["cap"], [label]).get(label)
        gaps[label] = None if eq is None or cap is None else clean_float(eq - cap, 2)
    return {"gap_pp": gaps}


def contributions(closes: pd.DataFrame, members: pd.DataFrame, count: int = CONTRIBUTORS) -> dict | None:
    """Each member's share of the index's last move: weight x its 1-day
    return, in percentage points of the index, and the same by sector."""
    if closes.shape[0] < 2 or members.empty:
        return None
    meta = members.drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")
    symbols = [s for s in meta.index if s in closes.columns]
    change = (closes[symbols].iloc[-1] / closes[symbols].iloc[-2] - 1) * 100
    contrib = (meta.loc[symbols, "weight"].astype(float) / 100 * change).dropna()
    if contrib.empty:
        return None
    by_sector = contrib.groupby(meta.loc[contrib.index, "sector"]).sum().sort_values(ascending=False)
    ranked = contrib.sort_values(ascending=False)
    row = lambda s: {"ticker": s, "contribution_pp": clean_float(contrib[s], 3), "return_pct": clean_float(change[s], 2)}
    return {
        "date": to_iso_date(closes.index[-1]),
        "total_pp": clean_float(contrib.sum(), 3),
        "leaders": [row(s) for s in ranked.index[:count] if contrib[s] > 0],
        "laggards": [row(s) for s in ranked.index[::-1][:count] if contrib[s] < 0],
        "sectors": [{"sector": k, "contribution_pp": clean_float(v, 3)} for k, v in by_sector.items()],
    }


def performance(series: dict[str, pd.Series], sessions: int = HIGH_WINDOW + 10) -> dict | None:
    """Closes of each line on a shared calendar over the last year, for a
    chart the page rebases to 100 at whichever start the reader picks."""
    present = {k: v.dropna() for k, v in series.items() if not v.dropna().empty}
    if not present:
        return None
    frame = pd.concat(present, axis=1).ffill(limit=3).dropna().tail(sessions)
    if frame.empty:
        return None
    return {"dates": [to_iso_date(d) for d in frame.index],
            "series": {k: [clean_float(v, 4) for v in frame[k]] for k in frame.columns}}


def sector_returns(etf_closes: pd.DataFrame, sector_etfs: dict[str, str], members: pd.DataFrame) -> list[dict]:
    """Each sector ETF's return over 1D/1W/1M/YTD, with the sector's index weight."""
    weights = members.groupby("sector")["weight"].sum() if not members.empty else pd.Series(dtype=float)
    out = []
    for sector, symbol in sector_etfs.items():
        if symbol not in etf_closes.columns:
            continue
        returns = R.period_returns(etf_closes[symbol].dropna(), PERIODS)
        out.append({"sector": sector, "etf": symbol, "weight_pct": clean_float(weights.get(sector), 1),
                    **{k: clean_float(v, 2) for k, v in returns.items()}})
    return sorted(out, key=lambda r: -(r["weight_pct"] or 0))


def breadth_history(closes: pd.DataFrame, sessions: int = HIGH_WINDOW) -> dict | None:
    """Share of members above their 50- and 200-day averages, last year."""
    if closes.shape[0] < 200 + 20:
        return None
    out = {}
    for window in (50, 200):
        sma = closes.rolling(window, min_periods=window).mean()
        counted = closes.notna() & sma.notna()
        share = ((closes > sma) & counted).sum(axis=1) / counted.sum(axis=1).replace(0, np.nan) * 100
        out[window] = share.dropna().tail(sessions)
    frame = pd.concat(out, axis=1).dropna()
    return {"dates": [to_iso_date(d) for d in frame.index],
            "above_50d": [clean_float(v, 1) for v in frame[50]],
            "above_200d": [clean_float(v, 1) for v in frame[200]]}


def rates_history(lines: dict[str, pd.Series], sessions: int = HIGH_WINDOW) -> dict | None:
    """The 2Y, 10Y and 10Y real yield over the last year, on the curve's calendar."""
    present = {k: v.dropna() for k, v in lines.items() if not v.dropna().empty}
    if not present:
        return None
    frame = pd.concat(present, axis=1).ffill(limit=3).tail(sessions)
    return {"dates": [to_iso_date(d) for d in frame.index],
            "series": {k: [clean_float(v, 3) for v in frame[k]] for k in frame.columns}}


def print_row(series_id: str, label: str, how: str, unit: str, series: pd.Series) -> dict:
    clean = series.dropna().sort_index()
    shown = {"yoy": lambda s: P.transform(s, "yoy"), "diff": lambda s: s.diff(), "level": lambda s: s}[how](clean).dropna()
    if shown.empty:
        return {"key": series_id, "label": label, "unit": unit, "value": None}
    digits = 0 if how == "diff" else 1 if series_id in ("UNRATE", "GDPNOW") else 2
    return {
        "key": series_id, "label": label, "unit": unit,
        "value": clean_float(shown.iloc[-1], digits),
        "prior": clean_float(shown.iloc[-2], digits) if len(shown) >= 2 else None,
        "period": to_iso_date(shown.index[-1]),
        "monthly": series_id != "GDPNOW",
    }


def _sessions_after(as_of: str, count: int) -> list[str]:
    day = date.fromisoformat(as_of)
    out = []
    while len(out) < count:
        day += timedelta(days=1)
        if day.weekday() < 5:
            out.append(day.isoformat())
    return out


def ahead(catalysts: dict | None, top: set[str], as_of: str, sessions: int = 3) -> list[dict]:
    """High- and medium-importance releases (not speeches) and the earnings of
    watchlist names and the largest index weights, over the next sessions."""
    if not catalysts:
        return []
    window = set(_sessions_after(as_of, sessions))
    items = []
    for event in catalysts.get("events") or []:
        if event.get("date") not in window:
            continue
        if event.get("lane") == "macro":
            importance = event.get("importance")
            if importance not in ("high", "medium") or (importance == "medium" and event.get("event_type") == "central_bank"):
                continue
            market = next((x for x in event.get("expectations") or [] if x.get("kind") == "market"), None)
            items.append({"kind": "macro", "date": event["date"], "time": event.get("time"), "title": event.get("title"),
                          "importance": importance, "market": market})
        else:
            symbol = event.get("symbol")
            if not symbol or (symbol not in top and not event.get("watchlist")):
                continue
            items.append({"kind": "earnings", "date": event["date"], "time": event.get("timing") or event.get("time"),
                          "symbol": symbol, "watchlist": bool(event.get("watchlist")),
                          "weight": (event.get("index_weights") or {}).get("SPX")})
    items.sort(key=lambda i: (i["date"], i["kind"] != "macro", TIERS.get(i.get("importance") or "low", 3)))
    return items


def fed(priced: dict | None) -> dict | None:
    if not priced or not priced.get("meetings"):
        return None
    meeting = priced["meetings"][0]
    year = meeting["date"][:4]
    year_end = [m for m in priced["meetings"] if m["date"][:4] == year][-1]
    return {
        "date": meeting["date"], "change_bp": meeting["change_bp"], "step": meeting["step"],
        "change_1w_bp": meeting.get("change_1w_bp"),
        "kalshi_p_hike": (meeting.get("kalshi") or {}).get("p_hike"),
        "polymarket_p_hike": (meeting.get("polymarket") or {}).get("value"),
        "year_end": {"date": year_end["date"], "cumulative_bp": year_end["cumulative_bp"]},
    }


def risk_line(risk: dict | None) -> dict | None:
    """The core RISK series past their lines, for one line pointing there."""
    if not risk:
        return None
    core = [t for s in risk["sections"] for t in s["tiles"] if t.get("core")]
    sentiment = risk.get("sentiment") or {}
    return {
        "core": len(core),
        "past": [{"label": t["label"], "value": t["value"], "unit": t["unit"]} for t in core if t.get("breach")],
        "fear_greed": {"score": sentiment.get("score"), "rating": sentiment.get("rating")} if sentiment.get("score") is not None else None,
    }


def build(ctx, *, inputs: dict[str, dict | None]) -> dict:
    settings = ctx.config.get("overview", {})
    as_of = pd.Timestamp(ctx.as_of)
    failed: dict[str, str] = {}

    stocks = []
    specs = {s.key: s for s in ctx.indices}
    for kind, key, label in STOCKS:
        if kind == "index":
            spec = specs.get(key)
            series = ctx.index_closes[spec.symbol] if spec and spec.symbol in ctx.index_closes.columns else pd.Series(dtype=float)
            label = spec.label if spec else label
        else:
            series = ctx.etf_closes[key] if key in ctx.etf_closes.columns else pd.Series(dtype=float)
        stocks.append(stock_row(label, key, series))

    breadth_blocks = []
    for spec in ctx.indices:
        symbols = [s for s in ctx.symbols_for(spec.key) if s in ctx.closes.columns]
        if symbols:
            breadth_blocks.append({"key": spec.key, "label": spec.label, **breadth(ctx.closes[symbols])})

    def fred_series(series_id: str) -> pd.Series:
        try:
            frame, _ = fred.fetch_series(series_id)
            series = frame.set_index("date")["value"].sort_index()
            return series[series.index <= as_of]
        except Exception as exc:
            failed[f"fred {series_id}"] = describe_error(exc)
            return pd.Series(dtype=float)

    try:
        curve, _ = treasury.fetch_par_yield_curve()
        wide = curve.pivot(index="date", columns="tenor", values="yield_pct")
        wide.index = pd.to_datetime(wide.index)
        wide = wide.sort_index().loc[:as_of]
    except Exception as exc:
        failed["treasury par curve"] = describe_error(exc)
        wide = pd.DataFrame()
    tenor = lambda t: wide[t] if t in wide.columns else pd.Series(dtype=float)
    rates = [rate_row(t, label, unit, tenor(t), "Treasury") for t, label, unit in TREASURY_RATES]
    # The slope from the same curve, so it agrees with the two rows above it.
    rates.append(rate_row("2s10s", "10Y − 2Y", "bp", tenor("10Y") - tenor("2Y"), "Treasury"))
    rates += [rate_row(sid, label, unit, fred_series(sid)) for sid, label, unit in FRED_RATES]
    prints = [print_row(sid, label, how, unit, fred_series(sid)) for sid, label, how, unit in PRINTS]
    got = sum(r.get("value") is not None for r in rates + prints if r.get("source") != "Treasury")
    ctx.log.add(SourceRecord(
        "fred_overview", "FRED: real yield, credit spreads and the latest macro prints", "https://fred.stlouisfed.org",
        max((r["date"] for r in rates if r.get("date") and r.get("source") == "FRED"), default=None), rows=got, policy="weekly_release",
        status="ok" if got == len(FRED_RATES) + len(PRINTS) else ("partial" if got else "error"),
    ))

    try:
        closes = yahoo.fetch_closes([s for s, _, _ in CROSS_ASSET], period="2y")
        closes = closes.loc[:as_of]
    except Exception as exc:
        failed["yahoo cross-asset"] = describe_error(exc)
        closes = pd.DataFrame()
    cross = [cross_row(symbol, label, unit, closes[symbol] if symbol in closes.columns else pd.Series(dtype=float))
             for symbol, label, unit in CROSS_ASSET]
    ctx.log.add(SourceRecord(
        "yahoo_overview", "Yahoo: dollar index, crude, copper, gold and VIX", "https://finance.yahoo.com",
        to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
        status="ok" if closes.shape[1] == len(CROSS_ASSET) else ("partial" if not closes.empty else "error"),
    ))

    etf = lambda symbol: ctx.etf_closes[symbol] if symbol in ctx.etf_closes.columns else pd.Series(dtype=float)

    def section(name: str, build_section):
        """A chart or line the page can do without: a failure is named in
        ``failed`` and leaves that card empty instead of failing the page."""
        try:
            return build_section()
        except Exception as exc:
            failed[name] = describe_error(exc)
            return None
    primary = ctx.priced(ctx.primary.key)
    members = [s for s in primary["yahoo_symbol"].drop_duplicates() if s in ctx.closes.columns] if not primary.empty else []

    holdings = ctx.holdings
    top = set(holdings.sort_values("weight", ascending=False)["yahoo_symbol"].head(int(settings.get("top_weights", 20)))) \
        if not holdings.empty else set()
    return {
        "as_of": ctx.as_of,
        "missing": sorted(name for name in INPUTS if inputs.get(name) is None),
        "stocks": stocks,
        "equal_vs_cap": section("equal vs cap weight", lambda: equal_vs_cap(etf("RSP"), etf("SPY"))),
        # ETFs, all four on Yahoo's dividend-adjusted closes: an index level
        # beside an adjusted ETF would credit the ETF with its dividends.
        "performance": section("performance", lambda: performance({
            "SPY": etf("SPY"), "QQQ": etf("QQQ"), "IWM": etf("IWM"), "RSP": etf("RSP")})),
        "sectors": section("sectors", lambda: sector_returns(ctx.etf_closes, ctx.sector_etfs, primary)) or [],
        "breadth_history": section("breadth history", lambda: breadth_history(ctx.closes[members]) if members else None),
        "rates_history": section("rates history", lambda: rates_history(
            {"UST 2Y": tenor("2Y"), "UST 10Y": tenor("10Y"), "10Y real": fred_series("DFII10")})),
        "contributions": section("contributions", lambda: contributions(ctx.closes[members], primary) if members else None),
        "breadth": breadth_blocks,
        "distribution": section("return distribution", lambda: return_distribution(ctx.closes[members]) if members else None),
        "rates": rates,
        "cross_asset": cross,
        "prints": prints,
        "fed": fed(inputs.get("priced")),
        "ahead": ahead(inputs.get("catalysts"), top, ctx.as_of),
        "risk": risk_line(inputs.get("risk")),
        "failed": failed,
    }
