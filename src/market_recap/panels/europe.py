"""EUROPE: index levels, supersector funds, index members and named groups.

Prices are Yahoo's (an index, a fund or a stock), returns are measured on each
series' own trading days (a London holiday is not a Paris holiday), in local
currency, and in dollars for the indices and the supersector funds. Members of
the FTSE 100 and EURO STOXX 50 come from Wikipedia's current tables; named
groups (luxury, UK financials) come from the config. Multiples are Yahoo's own
forward and trailing P/E and the consensus growth of this fiscal year's EPS.
A name Yahoo cannot price or value shows what it has and a dash for the rest.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..compute import europe as E
from ..compute import returns as R
from ..config import period_sessions
from ..context import YAHOO_URL
from ..sources import estimates, yahoo
from ..sources import europe as src
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

HIGH_SESSIONS = 252
SPARK_SESSIONS = 126


def _own(closes: pd.DataFrame, symbol: str) -> pd.Series:
    """A symbol's closes on its own trading days."""
    return closes[symbol].dropna() if symbol in closes.columns else pd.Series(dtype=float)


def _flags(series: pd.Series, windows: list[int]) -> dict:
    out = {}
    for n in windows:
        out[f"above_{n}"] = bool(series.iloc[-1] > series.iloc[-n:].mean()) if len(series) >= n else None
    return out


def _stats(series: pd.Series, cfg: dict, digits: int = 2) -> dict:
    """Last close, returns over each window, the drawdown from the 52-week high and
    whether the last close is above its moving averages."""
    if series.empty:
        return {"last": None, "date": None, "returns": {p: None for p in cfg["periods"]}, "drawdown_pct": None, "high_date": None,
                **{f"above_{n}": None for n in cfg["above_sessions"]}}
    year = series.iloc[-HIGH_SESSIONS:]
    dd = R.drawdown_from_high(year)
    return {
        "last": clean_float(series.iloc[-1], digits), "date": to_iso_date(series.index[-1]),
        "returns": {p: clean_float(v, 2) for p, v in R.period_returns(series, cfg["periods"]).items()},
        "drawdown_pct": clean_float(dd["drawdown_pct"], 2), "high_date": dd["high_date"],
        **_flags(series, list(cfg["above_sessions"])),
    }


def _fx(closes: pd.DataFrame, cfg: dict) -> dict[str, pd.Series]:
    return {row["currency"]: _own(closes, row["symbol"]) for row in cfg["fx"]}


def _usd_stats(series: pd.Series, currency: str | None, fx: dict[str, pd.Series], cfg: dict, *, pence: bool = False) -> dict | None:
    if currency == "USD":
        return {p: clean_float(v, 2) for p, v in R.period_returns(series, cfg["periods"]).items()}
    rate = fx.get(currency or "")
    if rate is None or rate.empty or series.empty:
        return None
    usd = E.in_dollars(series, rate, pence=pence).dropna()
    return {p: clean_float(v, 2) for p, v in R.period_returns(usd, cfg["periods"]).items()}


def _spark(series: pd.Series) -> list[float | None]:
    tail = series.iloc[-SPARK_SESSIONS:]
    return [clean_float(v, 2) for v in (100 * tail / tail.iloc[0])] if len(tail) > 1 else []


def _index_rows(closes: pd.DataFrame, fx: dict[str, pd.Series], cfg: dict) -> list[dict]:
    rows = []
    for spec in cfg["indices"]:
        s = _own(closes, spec["symbol"])
        rows.append({"key": spec["key"], "label": spec["label"], "symbol": spec["symbol"], "currency": spec["currency"],
                     **_stats(s, cfg), "returns_usd": _usd_stats(s, spec["currency"], fx, cfg), "spark": _spark(s)})
    return rows


def _chart(closes: pd.DataFrame, fx: dict[str, pd.Series], cfg: dict) -> dict:
    """Each index in dollars, rebased to 100 at the start of the chart window, so
    markets of different currencies and holidays can be drawn together."""
    years = int(cfg["chart_years"])
    frame = {}
    for spec in cfg["indices"]:
        s = _own(closes, spec["symbol"])
        rate = fx.get(spec["currency"])
        if s.empty or rate is None or rate.empty:
            continue
        frame[spec["label"]] = E.in_dollars(s, rate)
    bench = _own(closes, cfg["benchmark"])
    if not bench.empty:
        frame[cfg["benchmark"]] = bench
    if not frame:
        return {"dates": [], "series": {}}
    df = pd.DataFrame(frame).sort_index().ffill().dropna(how="all")
    start = df.index[-1] - pd.DateOffset(years=years)
    df = df[df.index >= start].dropna()
    df = 100 * df / df.iloc[0]
    weekly = pd.concat([df.iloc[:1], df.groupby(df.index.to_period("W-FRI")).tail(1)])      # the 100 the rest is measured from stays
    weekly = weekly[~weekly.index.duplicated(keep="last")]
    return {"dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
            "series": {k: [clean_float(v, 2) for v in weekly[k]] for k in weekly.columns}}


def _sector_rows(closes: pd.DataFrame, fx: dict[str, pd.Series], cfg: dict) -> list[dict]:
    base = _own(closes, cfg["rotation_benchmark"])
    base_returns = R.period_returns(base, cfg["periods"]) if not base.empty else {}
    rows = []
    for spec in cfg["sectors"]:
        s = _own(closes, spec["symbol"])
        st = _stats(s, cfg)
        rel = {p: (clean_float(st["returns"][p] - base_returns[p], 2) if st["returns"].get(p) is not None and base_returns.get(p) is not None else None)
               for p in cfg["periods"]}
        rows.append({"key": spec["key"], "label": spec["label"], "symbol": spec["symbol"], "currency": "EUR", **st, "relative": rel,
                     "spark": _spark(s)})
    return rows


def _name_row(symbol: str, name: str | None, sector_source: str | None, closes: pd.DataFrame, cfg: dict,
              multiples: dict, trends: dict) -> dict:
    s = _own(closes, symbol)
    m = multiples.get(symbol) or {}
    growth, out_of_range = None, False
    y0 = (trends.get(symbol) or {}).get("0y") or {}
    if y0.get("eps") is not None and y0.get("year_ago_eps") and y0["year_ago_eps"] > 0:
        growth = (y0["eps"] / y0["year_ago_eps"] - 1) * 100
        if abs(growth) > cfg["eps_growth_cap"]:             # off a profit near zero: not a growth rate
            growth, out_of_range = None, True
    sector = E.broad_sector(sector_source, cfg["sector_map"])
    return {"symbol": symbol, "name": name or symbol, "sector": sector, "sector_source": sector_source,
            "currency": E.currency_of(symbol), **_stats(s, cfg),
            "forward_pe": clean_float(m.get("forward_pe"), 1), "trailing_pe": clean_float(m.get("trailing_pe"), 1),
            "eps_growth": clean_float(growth, 1), "eps_growth_out_of_range": out_of_range, "market_cap": clean_float(m.get("market_cap"), 0),
            "first_price": to_iso_date(s.index[0]) if len(s) else None}


def _sector_summary(names: list[dict], periods: list[str]) -> list[dict]:
    out = []
    frame = pd.DataFrame(names)
    if frame.empty:
        return out
    for sector, g in frame.groupby("sector"):
        row = {"sector": sector, "n": int(len(g)),
               "median_returns": {p: clean_float(pd.Series([r.get(p) for r in g["returns"]], dtype=float).median(), 2) for p in periods},
               "above_50_share": clean_float(g["above_50"].dropna().astype(float).mean() * 100, 0) if g["above_50"].notna().any() else None,
               "median_forward_pe": clean_float(pd.to_numeric(g["forward_pe"], errors="coerce").median(), 1)}
        out.append(row)
    return sorted(out, key=lambda r: -r["n"])


def build(ctx) -> dict:
    cfg = ctx.config["europe"]
    as_of = date.fromisoformat(ctx.as_of)
    errors: dict[str, str] = {}

    members: dict[str, pd.DataFrame] = {}
    sources: dict[str, str] = {}
    for u in cfg["universes"]:
        try:
            frame, url = (src.fetch_ftse100 if u["source"] == "ftse100" else src.fetch_eurostoxx50)()
            members[u["key"]], sources[u["key"]] = frame, url
        except Exception as exc:  # noqa: BLE001 -- that universe is a named gap, the rest stands
            errors[u["key"]] = describe_error(exc)

    # Groups: explicit symbols, and/or one broad sector of a universe.
    group_members: dict[str, list[tuple[str, str | None, str | None]]] = {}
    for g in cfg["groups"]:
        found: list[tuple[str, str | None, str | None]] = [(m["symbol"], m.get("name"), m.get("sector")) for m in g.get("members") or []]
        if g.get("from_universe") in members:
            frame = members[g["from_universe"]]
            for r in frame.itertuples(index=False):
                if E.broad_sector(r.sector_source, cfg["sector_map"]) == g["sector"]:
                    found.append((r.symbol, r.name, r.sector_source))
        group_members[g["key"]] = found

    index_symbols = [s["symbol"] for s in cfg["indices"]] + [s["symbol"] for s in cfg["sectors"]]
    fx_symbols = [f["symbol"] for f in cfg["fx"]]
    name_symbols = sorted({r.symbol for f in members.values() for r in f.itertuples(index=False)}
                          | {sym for found in group_members.values() for sym, _, _ in found})
    wanted = sorted({*index_symbols, *fx_symbols, *name_symbols, cfg["benchmark"], cfg["rotation_benchmark"]})
    closes = yahoo.fetch_closes(wanted, period=f"{int(cfg['history_years']) + 1}y")
    closes = closes[closes.index <= pd.Timestamp(as_of)]
    missing = sorted(set(wanted) - {c for c in closes.columns if closes[c].notna().any()})
    ctx.log.add(SourceRecord("europe_prices", "Yahoo daily closes: European indices, supersector funds, index members, named groups, currencies",
                             YAHOO_URL, to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if not missing else "partial",
                             error=f"no prices: {', '.join(missing[:12])}{' ...' if len(missing) > 12 else ''}" if missing else None))

    try:
        multiples, mfail = src.fetch_multiples(name_symbols)
    except Exception as exc:  # noqa: BLE001 -- the tables then show prices only
        multiples, mfail = {}, {s: describe_error(exc) for s in name_symbols}
    try:
        trends, _ = estimates.fetch_trends(name_symbols)
    except Exception:  # noqa: BLE001 -- growth is then absent, never zero
        trends = {}
    ctx.log.add(SourceRecord("europe_multiples", "Yahoo forward and trailing P/E and consensus EPS growth for the European names",
                             YAHOO_URL, ctx.as_of, rows=len(multiples), policy="daily_close",
                             status="ok" if len(multiples) >= 0.8 * max(len(name_symbols), 1) else "partial",
                             error=None if len(multiples) >= 0.8 * max(len(name_symbols), 1) else f"{len(mfail)} of {len(name_symbols)} without multiples"))

    fx = _fx(closes, cfg)
    universes = {}
    for u in cfg["universes"]:
        if u["key"] not in members:
            universes[u["key"]] = {"label": u["label"], "unavailable": errors.get(u["key"], "no members")}
            continue
        names = [_name_row(r.symbol, r.name, r.sector_source, closes, cfg, multiples, trends) for r in members[u["key"]].itertuples(index=False)]
        universes[u["key"]] = {"label": u["label"], "source": sources[u["key"]], "names": names,
                               "sectors": _sector_summary(names, cfg["periods"])}
    groups = []
    for g in cfg["groups"]:
        names = [_name_row(sym, nm, ss, closes, cfg, multiples, trends) for sym, nm, ss in group_members[g["key"]]]
        groups.append({"key": g["key"], "label": g["label"], "note": g.get("note"), "names": names,
                       "sectors": _sector_summary(names, cfg["periods"])})

    bench = _own(closes, cfg["benchmark"])
    return {
        "as_of": ctx.as_of,
        "settings": {k: cfg[k] for k in ("periods", "benchmark", "rotation_benchmark", "chart_years", "above_sessions", "eps_growth_cap")},
        "inputs": {"prices_through": to_iso_date(closes.index[-1]) if not closes.empty else None, "no_prices": missing,
                   "universes_unavailable": errors},
        "fx": [{"currency": f["currency"], "symbol": f["symbol"], **_stats(fx[f["currency"]], cfg, digits=4)} for f in cfg["fx"]],
        "benchmark": {"symbol": cfg["benchmark"], **_stats(bench, cfg)},
        "indices": _index_rows(closes, fx, cfg),
        "chart": _chart(closes, fx, cfg),
        "sectors": _sector_rows(closes, fx, cfg),
        "universes": universes,
        "groups": groups,
        "notes": [
            "Returns are measured on each series' own trading days and are in local currency; the indices' dollar returns compound the "
            "local return with the currency's move against the dollar. A London price is in pence.",
            "Members come from Wikipedia's current tables: today's, not what the index held on a past date. Sectors are Wikipedia's industry "
            "labels mapped to broad sectors in the config.",
            "Multiples are Yahoo's own forward and trailing P/E (Yahoo converts between a company's price and reporting currencies, "
            "which this page does not). They are not the next-twelve-months blend the US tabs use; the daily snapshot job records "
            "them so that a history exists from the day it started.",
        ],
        "period_sessions": {p: period_sessions(p) for p in cfg["periods"]},
    }
