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

from ..compute import valuation as V
from ..sources import sec
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float
from .financials import cik_for, universe

# How far a company's share of index market cap may sit from its share of SPY
# before the share count is flagged. Float adjustment reaches ~2x for closely
# held companies (Walmart, Berkshire); a class missed or a split unrecorded is
# 3x and up.
WEIGHT_CHECK_FACTOR = 2.5


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


def _row(symbol: str, meta: dict, data: sec.Filer, price: float | None, indices: list[str], splits) -> dict:
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

    rows, skipped = [], {}
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
        rows.append(_row(symbol, meta.get(symbol, {}), data, price, indices.get(symbol, []), ctx.splits))

    primary = ctx.members[ctx.primary.key].drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")["weight"]
    check = _weight_check([r for r in rows if ctx.primary.key in r["indices"]], primary.to_dict())
    without_cap = sorted(r["ticker"] for r in rows if r["market_cap"] is None)

    ctx.log.add(SourceRecord(
        "sec_trailing", "SEC XBRL company facts (trailing twelve months)",
        "https://data.sec.gov/api/xbrl/companyfacts/",
        rows=len(rows),
        status="ok" if not skipped else "partial",
        error=None if not skipped else f"{len(skipped)} of {len(symbols)} not extracted",
    ))
    return {
        "as_of": ctx.as_of,
        "indices": list(ctx.config["financials"]["indices"]),
        "universe": len(symbols),
        "metrics": [
            {"key": m.key, "label": m.label, "unit": m.unit, "group": m.group, "better": m.better, "banks": m.banks}
            for m, _ in V.METRICS
        ],
        "rows": rows,
        "skipped": skipped,
        "without_market_cap": without_cap,
        "weight_check": check,
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
