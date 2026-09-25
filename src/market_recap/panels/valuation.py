"""VALUATION & QUALITY tab: every index member on one table, from its own filings.

Market cap is the page's closing price times a filed share count; every other
input is the company's latest 10-Q/10-K, trailing twelve months. Nothing here
comes from a data vendor's "key statistics" page, so every number on the tab
can be traced to a filing and a close.

The share count is the one input most likely to be wrong -- a class left off
the cover page, a unit error, a split after the last filing -- so it is
checked against the issuer's own SPY weight: a company's share of the
index's total market cap should roughly match its share of SPY. Float
adjustment moves that by less than the checked factor; a units or split error
moves it by more.
"""

from __future__ import annotations

import math

import pandas as pd

from ..compute import valuation as V
from ..config import VALUATION_ARTIFACT_DIR
from ..sources import sec
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, prune_stale, write_json
from .financials import cik_for, universe

# How far a company's share of index market cap may sit from its share of SPY
# before the share count is flagged. Float adjustment reaches ~2x for closely
# held companies (Walmart, Berkshire); a class missed or a split unrecorded is
# 3x and up.
WEIGHT_CHECK_FACTOR = 2.5

# The table's P/E is market cap over TTM net income; the history's is price
# over TTM diluted EPS, as filed. They reach the same number by different
# roads, so the latest point of one checks the other; a gap wider than this
# means a share count or a split went wrong on one of them.
PE_AGREEMENT_TOLERANCE = 0.25

# Columns the history adds to the table, beside the snapshot metrics.
HISTORY_METRICS = (
    V.Metric("pe_percentile", "P/E percentile, own 10Y", "pct", "valuation", "low"),
    V.Metric("pe_vs_median", "P/E vs own 10Y median", "pct", "valuation", "low"),
)


def _history(symbol: str, data: sec.Filer, prices: pd.Series | None, splits: pd.Series | None) -> dict | None:
    """P/E against its own ten years; writes the ticker's chart artifact."""
    if prices is None or not data.eps_history:
        return None
    steps = V.eps_steps(data.eps_history, splits)
    pe = V.pe_series(prices, steps)
    stats = V.pe_stats(pe) if not pe.empty else None
    if stats is None:
        return None
    window = pe.iloc[-V.HISTORY_SESSIONS:]
    # Weekly for the chart (a decade of daily points is 2,500 per ticker); the
    # statistics above are on every session. Each point keeps the date of the
    # session it is -- resampling labels a week by its Friday, which dated the
    # latest point to a Friday that had not happened yet.
    weekly = window.groupby(window.index.to_period("W-FRI")).tail(1)
    write_json(VALUATION_ARTIFACT_DIR / f"{symbol}.json", {
        "ticker": symbol,
        "dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
        "pe": [clean_float(v, 2) for v in weekly.to_numpy()],
        "stats": {k: clean_float(v, 2) if isinstance(v, float) else v for k, v in stats.items()},
        "eps": [
            {"filed": filed, "period_end": end, "eps": clean_float(eps, 4)}
            for filed, end, eps in steps if filed >= stats["first"]
        ],
    })
    return stats


def _split_factor(splits, symbol: str, after: str | None) -> float:
    """Product of the splits the price has seen since the share count's date.

    The close is on today's share basis; a count filed before a split is not.
    Amphenol split 2:1 a month after its 10-Q, and without this its market
    cap was half its SPY weight.
    """
    if after is None or splits is None or symbol not in splits.columns:
        return 1.0
    ratios = splits[symbol].dropna()
    return float(ratios[ratios.index > after].prod()) if not ratios.empty else 1.0


def _row(symbol: str, meta: dict, data: sec.Filer, price: float | None, indices: list[str], splits,
         history: dict | None) -> dict:
    snapshot = data.trailing
    factor = _split_factor(splits, symbol, snapshot["shares_as_of"])
    shares = snapshot["shares"] * factor if snapshot["shares"] else None
    market_cap = price * shares if price is not None and shares else None
    ev = V.enterprise_value(market_cap, snapshot)
    metrics = V.compute(V.Inputs(snapshot, data.rows, market_cap, ev), sector=meta.get("sector"))
    _, tested = V.piotroski(data.rows)
    _, debt_basis = V.debt(snapshot)
    return {
        "ticker": symbol,
        "name": meta.get("name"),
        "sector": meta.get("sector"),
        "indices": indices,
        "price": clean_float(price, 2),
        "market_cap": clean_float(market_cap, 0),
        "ev": clean_float(ev, 0),
        "period_end": snapshot["period_end"],
        "filed": snapshot["filed"],
        "cik": data.ciks[0],
        "shares_basis": snapshot["shares_basis"] + (f", x{factor:g} for a split since" if factor != 1 else ""),
        "debt_basis": debt_basis,
        # Lines taken from the quarter before the latest, because the latest 10-Q did not tag them.
        "lagged": snapshot.get("lagged") or [],
        "piotroski_tested": tested,
        **{key: clean_float(value, 4) for key, value in metrics.items()},
        # Signed, unlike P/E and P/B: an ETF's look-through multiple is its
        # total earnings over its total price, losses included, as for an index.
        "earnings_yield": clean_float(V._pct(snapshot["ttm"].get("net_income"), market_cap), 4),
        "book_yield": clean_float(V._pct(snapshot["balance"].get("equity"), market_cap), 4),
        "pe_history": history is not None,
        "pe_history_current": clean_float((history or {}).get("current"), 2),
        "pe_percentile": clean_float((history or {}).get("percentile"), 1),
        "pe_vs_median": clean_float((history or {}).get("vs_median"), 1),
    }


def _aggregates(ctx, rows: list[dict], caps: dict[str, pd.Series], earnings: dict[str, pd.Series]) -> dict | None:
    """Each index's and each sector's P/E against its own ten years.

    A company counts at today's share count throughout: its own P/E is exact
    on every date, but the weights between companies are today's, and the
    members are today's (no company that has left the index is in its past).
    """
    if not caps:
        return None
    cap_frame, earnings_frame = pd.DataFrame(caps), pd.DataFrame(earnings)
    groups = [(spec.key, spec.label, "index", [r["ticker"] for r in rows if spec.key in r["indices"]])
              for spec in ctx.indices]
    primary = [r for r in rows if ctx.primary.key in r["indices"] and r["sector"]]
    for sector in sorted({r["sector"] for r in primary}):
        groups.append((sector, sector, "sector", [r["ticker"] for r in primary if r["sector"] == sector]))
    dates, series = None, []
    for key, label, kind, tickers in groups:
        columns = [t for t in tickers if t in cap_frame.columns]
        if not columns:
            continue
        frame = V.aggregate_pe(cap_frame[columns], earnings_frame[columns]).iloc[-V.HISTORY_SESSIONS:]
        stats = V.pe_stats(frame["pe"])
        weekly = frame.groupby(frame.index.to_period("W-FRI")).tail(1)
        dates = dates or [d.strftime("%Y-%m-%d") for d in weekly.index]
        series.append({
            "key": key,
            "label": label,
            "kind": kind,
            "companies": len(columns),
            "coverage": clean_float(frame["coverage"].iloc[-1], 3),
            "stats": {k: clean_float(v, 2) if isinstance(v, float) else v for k, v in stats.items()} if stats else None,
            "pe": [clean_float(v, 2) for v in weekly["pe"].to_numpy()],
        })
    return {
        "dates": dates,
        "series": series,
        "window_sessions": V.HISTORY_SESSIONS,
        "min_coverage": V.AGGREGATE_MIN_COVERAGE,
    }


def _weight_check(rows: list[dict], weights: dict[str, float]) -> dict:
    """Each checked company's share of total market cap over its share of SPY.

    By company, not by listing: GOOG and GOOGL are one market cap and two SPY
    lines, and comparing each line with the whole company flagged News Corp.
    """
    companies: dict[int, tuple[dict, float]] = {}
    for row in rows:
        if row["market_cap"] and weights.get(row["ticker"]):
            first, weight = companies.get(row["cik"], (row, 0.0))
            companies[row["cik"]] = (first, weight + weights[row["ticker"]])
    pairs = list(companies.values())
    if not pairs:
        return {"checked": 0, "flagged": []}
    total_cap = sum(r["market_cap"] for r, _ in pairs)
    total_weight = sum(w for _, w in pairs)
    flagged = []
    ratios = {}
    for row, weight in pairs:
        ratio = (row["market_cap"] / total_cap) / (weight / total_weight)
        ratios[row["cik"]] = clean_float(ratio, 3)
        if abs(math.log(ratio)) > math.log(WEIGHT_CHECK_FACTOR):
            flagged.append({"ticker": row["ticker"], "ratio": clean_float(ratio, 2), "shares_basis": row["shares_basis"]})
    for row in rows:
        row["weight_ratio"] = ratios.get(row["cik"])
    return {"checked": len(pairs), "factor": WEIGHT_CHECK_FACTOR, "flagged": sorted(flagged, key=lambda f: f["ratio"])}


def build(ctx, *, use_cache: bool = True) -> dict:
    symbols = universe(ctx)
    try:
        cik_map = sec.fetch_ticker_cik_map(use_cache=use_cache)
    except Exception as exc:
        ctx.log.fail("valuation:cik_map", exc)
        return {"as_of": ctx.as_of, "rows": [], "error": str(exc)[:ERROR_DETAIL_CHARS]}

    meta, indices = {}, {}
    for key, frame in ctx.members.items():
        for row in frame.drop_duplicates("yahoo_symbol").itertuples():
            meta.setdefault(row.yahoo_symbol, {"name": str(row.name).title(), "sector": row.sector})
            indices.setdefault(row.yahoo_symbol, []).append(key)

    if use_cache:
        sec.check_filings(cik_for(symbol, cik_map) for symbol in symbols)
    rows, skipped = [], {}
    # Market cap and TTM earnings through time, one listing per company: a
    # second share class carries the whole company's cap again.
    caps, earnings, companies = {}, {}, set()
    for symbol in symbols:
        cik = cik_for(symbol, cik_map)
        if cik is None:
            skipped[symbol] = "no CIK in SEC's ticker map"
            continue
        try:
            data = sec.filer(cik, use_cache)
        except Exception as exc:
            skipped[symbol] = str(exc)[:ERROR_DETAIL_CHARS]
            continue
        if not data.rows or data.trailing is None:
            skipped[symbol] = sec.unextracted_reason(data.taxonomies)
            continue
        closes = ctx.closes[symbol].dropna() if symbol in ctx.closes.columns else None
        price = float(closes.iloc[-1]) if closes is not None and not closes.empty else None
        symbol_splits = ctx.splits[symbol] if symbol in ctx.splits.columns else None
        history = _history(symbol, data, ctx.prices.get(symbol), symbol_splits)
        row = _row(symbol, meta.get(symbol, {}), data, price, indices.get(symbol, []), ctx.splits, history)
        rows.append(row)
        prices = ctx.prices.get(symbol)
        if prices is not None and data.eps_history and row["market_cap"] and price and row["cik"] not in companies:
            companies.add(row["cik"])
            shares = row["market_cap"] / price
            caps[symbol] = prices * shares
            earnings[symbol] = V.plausible_eps(prices, V.eps_steps(data.eps_history, symbol_splits)) * shares

    primary = ctx.members[ctx.primary.key].drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")["weight"]
    check = _weight_check([r for r in rows if ctx.primary.key in r["indices"]], primary.to_dict())
    prune_stale(VALUATION_ARTIFACT_DIR, (r["ticker"] for r in rows if r["pe_history"]))
    without_cap = sorted(r["ticker"] for r in rows if r["market_cap"] is None)
    disagree = sorted(
        r["ticker"] for r in rows
        if r["pe"] and r["pe_history_current"]
        and abs(r["pe_history_current"] / r["pe"] - 1) > PE_AGREEMENT_TOLERANCE
    )

    ctx.log.add(SourceRecord(
        "sec_trailing", "SEC XBRL company facts (trailing twelve months)",
        "https://data.sec.gov/api/xbrl/companyfacts/",
        observed_date=max((r["filed"] for r in rows if r["filed"]), default=None),
        rows=len(rows),
        policy="filings",
        status="ok" if not skipped else "partial",
        error=None if not skipped else f"{len(skipped)} of {len(symbols)} not extracted",
    ))
    return {
        "as_of": ctx.as_of,
        "indices": list(ctx.config["financials"]["indices"]),
        "universe": len(symbols),
        "metrics": [
            {"key": m.key, "label": m.label, "unit": m.unit, "group": m.group, "better": m.better, "banks": m.banks}
            for m in [m for m, _ in V.METRICS] + list(HISTORY_METRICS)
        ],
        "rows": rows,
        "skipped": skipped,
        "without_market_cap": without_cap,
        "pe_history": {
            "companies": sum(1 for r in rows if r["pe_history"]),
            "window_sessions": V.HISTORY_SESSIONS,
            "min_sessions": V.MIN_HISTORY_SESSIONS,
            "agreement_tolerance": PE_AGREEMENT_TOLERANCE,
            "disagree": disagree,
        },
        "weight_check": check,
        "aggregates": _aggregates(ctx, rows, caps, earnings),
        "financials_sector": V.FINANCIALS_SECTOR,
        "note": (
            "Market cap is the closing price times a filed share count: the latest cover-page count "
            "when it covers every class, otherwise the latest quarter's diluted weighted average. "
            "Flows are trailing twelve months from the company's own 10-Qs and 10-K (last fiscal year "
            "+ year to date - the same span a year earlier); balances are at the latest quarter end, "
            "shown per row. A loss, negative equity or negative EBITDA leaves the multiple blank. "
            "EV-based multiples, gross profit, FCF and accruals are not computed for the Financials "
            "sector. Debt excludes operating leases; a company that tags no debt is taken as "
            "debt-free and marked so. Percentiles are within sector."
        ),
    }
