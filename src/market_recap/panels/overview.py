"""OVERVIEW: the one-glance read of the market, and the site's landing page.

Four questions, each answered with a level, its recent changes and a small
line of its last six months: how stocks have done (and how far they sit
from their high), how broad the move is, where rates and credit are, and
what the dollar, commodities, volatility and the latest macro prints say.
Beneath them, the next three sessions and what the Fed is priced to do.

Stocks and breadth come from the build's own closes; rates, spreads and
macro prints from FRED; the cross-asset rows from Yahoo. The Fed line and
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
from ..sources import fred, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

# Panels OVERVIEW reads, all required to be from this session.
INPUTS = ("priced", "catalysts", "risk")
PERIODS = ["1D", "1W", "1M", "YTD"]
SPARK_SESSIONS = 126
SPARK_POINTS = 60
HIGH_WINDOW = 252
BREADTH_WINDOWS = {"1D": 1, "1W": 5, "1M": 21}
TIERS = {"high": 0, "medium": 1, "low": 2}

# Stock rows: index levels from the build's index closes, the rest from ETFs.
STOCKS = [
    ("index", "SPX", "S&P 500"),
    ("index", "NDX", "Nasdaq 100"),
    ("etf", "IWM", "Russell 2000 (IWM)"),
    ("etf", "RSP", "S&P 500 equal wt (RSP)"),
]
# Rates and credit, from FRED. ``unit`` is the display unit of the level;
# changes are always in basis points.
RATES = [
    ("DGS2", "UST 2Y", "pct"),
    ("DGS10", "UST 10Y", "pct"),
    ("T10Y2Y", "10Y − 2Y", "bp"),
    ("DFII10", "10Y real (TIPS)", "pct"),
    ("BAMLH0A0HYM2", "High yield OAS", "bp"),
    ("BAMLC0A0CM", "Investment grade OAS", "bp"),
]
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
    # The share above the 50-day average over the last half year, for the line.
    if closes.shape[0] >= 50 + SPARK_SESSIONS:
        sma = closes.rolling(50, min_periods=50).mean()
        counted = closes.notna() & sma.notna()
        share = ((closes > sma) & counted).sum(axis=1) / counted.sum(axis=1).replace(0, np.nan) * 100
        out["above_50d_spark"] = _spark(share)
    else:
        out["above_50d_spark"] = []
    return out


def rate_row(series_id: str, label: str, unit: str, series: pd.Series) -> dict:
    clean = series.dropna()
    if clean.empty:
        return {"key": series_id, "label": label, "unit": unit, "value": None}
    # FRED serves yields and spreads in percent; the page shows spreads in bp.
    scale = 100.0 if unit == "bp" else 1.0
    value = float(clean.iloc[-1])

    def change(days: int) -> float | None:
        prior = _value_days_ago(clean, days)
        return None if prior is None else clean_float((value - prior) * 100.0, 1)

    return {
        "key": series_id, "label": label, "unit": unit,
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
    return {
        "core": len(core),
        "past": [{"label": t["label"], "value": t["value"], "unit": t["unit"]} for t in core if t.get("breach")],
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

    rates = [rate_row(sid, label, unit, fred_series(sid)) for sid, label, unit in RATES]
    prints = [print_row(sid, label, how, unit, fred_series(sid)) for sid, label, how, unit in PRINTS]
    got = sum(r.get("value") is not None for r in rates + prints)
    ctx.log.add(SourceRecord(
        "fred_overview", "FRED: Treasury yields, credit spreads and the latest macro prints", "https://fred.stlouisfed.org",
        max((r["date"] for r in rates if r.get("date")), default=None), rows=got, policy="weekly_release",
        status="ok" if got == len(rates) + len(prints) else ("partial" if got else "error"),
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

    holdings = ctx.holdings
    top = set(holdings.sort_values("weight", ascending=False)["yahoo_symbol"].head(int(settings.get("top_weights", 20)))) \
        if not holdings.empty else set()
    return {
        "as_of": ctx.as_of,
        "missing": sorted(name for name in INPUTS if inputs.get(name) is None),
        "stocks": stocks,
        "breadth": breadth_blocks,
        "rates": rates,
        "cross_asset": cross,
        "prints": prints,
        "fed": fed(inputs.get("priced")),
        "ahead": ahead(inputs.get("catalysts"), top, ctx.as_of),
        "risk": risk_line(inputs.get("risk")),
        "failed": failed,
    }
