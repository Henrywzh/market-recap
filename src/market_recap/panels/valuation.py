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
from ..sources import estimates, sec, snapshot_store
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

# Columns the history adds to the table, beside the snapshot metrics. The
# percentile is on the history's own basis (operating unless the company has
# no operating history), the table's own P/E stays reported.
HISTORY_METRICS = (
    V.Metric("pe_forward", "P/E forward (NTM consensus)", "x", "valuation", "low"),
    V.Metric("pe_operating", "P/E operating (TTM)", "x", "valuation", "low"),
    V.Metric("pe_percentile", "P/E percentile, own 10Y", "pct", "valuation", "low"),
    V.Metric("pe_vs_median", "P/E vs own 10Y median", "pct", "valuation", "low"),
)


def _weekly(series: pd.Series) -> pd.Series:
    # Weekly for the chart (a decade of daily points is 2,500 per ticker); the
    # statistics are on every session. Each point keeps the date of the
    # session it is -- resampling labels a week by its Friday, which dated the
    # latest point to a Friday that had not happened yet.
    return series.groupby(series.index.to_period("W-FRI")).tail(1)


def _stats_json(stats: dict) -> dict:
    return {k: clean_float(v, 2) if isinstance(v, float) else v for k, v in stats.items()}


def _forward_series(symbol: str, prices: pd.Series | None, recorded: dict[str, dict[str, dict]],
                    today: pd.Timestamp, ntm_today: dict | None) -> dict | None:
    """Forward P/E on every recorded day (the close that day over that day's
    NTM consensus) and today's; the history starts when recording started."""
    if prices is None or prices.dropna().empty:
        return None
    closes = prices.dropna()
    points = {}
    for day, trends in recorded.items():
        stamp = pd.Timestamp(day)
        ntm = V.ntm_eps(trends.get(symbol), stamp)
        at = closes[closes.index <= stamp]
        if ntm and not at.empty:
            points[day] = (V.forward_pe(float(at.iloc[-1]), ntm), ntm["eps"])
    if ntm_today:
        points[today.strftime("%Y-%m-%d")] = (V.forward_pe(float(closes.iloc[-1]), ntm_today), ntm_today["eps"])
    if not points:
        return None
    days = sorted(points)
    return {"dates": days, "pe": [clean_float(points[d][0], 2) for d in days],
            "eps_ntm": [clean_float(points[d][1], 4) for d in days], "recorded_days": len(recorded)}


def _history(symbol: str, data: sec.Filer, prices: pd.Series | None, splits: pd.Series | None,
             sector: str | None, forward: dict | None = None) -> dict | None:
    """P/E against its own ten years, on the operating basis and as reported;
    writes the ticker's chart artifact. Returns {basis, <basis>: stats, ...}."""
    if prices is None or not data.eps_history:
        return None
    reported_steps = V.eps_steps(data.eps_history, splits)
    basis = V.operating_basis(data.eps_history, sector)
    operating = V.operating_steps(data.eps_history, splits, basis)
    series = {V.REPORTED: V.pe_series(prices, reported_steps), basis: V.pe_series(prices, V.as_steps(operating))}
    stats = {key: V.pe_stats(pe) if not pe.empty else None for key, pe in series.items()}
    if stats[V.REPORTED] is None and stats[basis] is None:
        return None
    # The operating basis leads unless it has too little history to rank.
    lead = basis if stats[basis] is not None else V.REPORTED
    first = stats[lead]["first"]
    dates = _weekly(series[lead].iloc[-V.HISTORY_SESSIONS:]).index
    by_filed = {s["filed"]: s for s in operating}

    def payload(key: str) -> dict | None:
        if stats[key] is None:
            return None
        return {
            "basis": key,
            "label": V.BASIS_LABELS[key],
            "pe": [clean_float(v, 2) for v in series[key].reindex(dates).to_numpy()],
            "stats": _stats_json(stats[key]),
        }

    write_json(VALUATION_ARTIFACT_DIR / f"{symbol}.json", {
        "ticker": symbol,
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "basis": lead,
        **payload(lead),
        "alternate": payload(V.REPORTED if lead != V.REPORTED else basis),
        "forward": forward,
        # Each quarter's TTM EPS both ways, and what the operating figure took out.
        "eps": [
            {"filed": filed, "period_end": end, "reported": clean_float(eps, 4),
             "operating": clean_float(by_filed.get(filed, {}).get("eps"), 4),
             "removed": clean_float(by_filed.get(filed, {}).get("removed"), 4),
             "tax_rate": clean_float(by_filed.get(filed, {}).get("tax_rate"), 3)}
            for filed, end, eps in reported_steps if filed >= first
        ],
    })
    return {"basis": lead, **stats}


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


# A market cap from Yahoo stands in only where the filings give no total share
# count; such a row's per-share EPS may be in another class's shares
# (Berkshire's is per Class A), so it is kept out of the index aggregates.
YAHOO_CAP_BASIS = "Yahoo market cap: the filings count shares class by class, never in total"


def _book_fields(snapshot: dict) -> dict:
    now, prior = V.tangible_book(snapshot["balance"]), V.tangible_book(snapshot["balance_prior"])
    average = None
    if now and now["value"] > 0:
        average = now["value"] if prior is None or prior["value"] <= 0 else (now["value"] + prior["value"]) / 2
    return {"tbv": clean_float(now["value"], 0) if now else None, "tbv_avg": clean_float(average, 0),
            "income_common": clean_float(snapshot["ttm"].get("income_to_common"), 0),
            "tbv_assumed_none": now["assumed_none"] if now else None}


def _row(symbol: str, meta: dict, data: sec.Filer, price: float | None, indices: list[str], splits,
         history: dict | None, ntm: dict | None = None, fallback_cap: float | None = None,
         path: dict | None = None) -> dict:
    snapshot = data.trailing
    factor = _split_factor(splits, symbol, snapshot["shares_as_of"])
    shares = snapshot["shares"] * factor if snapshot["shares"] else None
    market_cap = price * shares if price is not None and shares else None
    shares_basis = snapshot["shares_basis"] + (f", x{factor:g} for a split since" if factor != 1 else "")
    if market_cap is None and fallback_cap and price is not None:
        market_cap, shares_basis = fallback_cap, YAHOO_CAP_BASIS
    has_history = history is not None
    ev = V.enterprise_value(market_cap, snapshot)
    metrics = V.compute(V.Inputs(snapshot, data.rows, market_cap, ev), sector=meta.get("sector"))
    _, tested = V.piotroski(data.rows)
    _, debt_basis = V.debt(snapshot)
    history = history or {}
    basis = history.get("basis")
    reported, lead = history.get(V.REPORTED) or {}, history.get(basis) or {}
    return {
        "ticker": symbol,
        "name": meta.get("name"),
        "sector": meta.get("sector"),
        "sub_sector": meta.get("sub_sector"),
        "indices": indices,
        "price": clean_float(price, 2),
        "market_cap": clean_float(market_cap, 0),
        "ev": clean_float(ev, 0),
        "period_end": snapshot["period_end"],
        "filed": snapshot["filed"],
        "cik": data.ciks[0],
        "shares_basis": shares_basis,
        "debt_basis": debt_basis,
        # Lines taken from the quarter before the latest, because the latest 10-Q did not tag them.
        "lagged": snapshot.get("lagged") or [],
        "piotroski_tested": tested,
        **{key: clean_float(value, 4) for key, value in metrics.items()},
        # Signed, unlike P/E and P/B: an ETF's look-through multiple is its
        # total earnings over its total price, losses included, as for an index.
        "earnings_yield": clean_float(V._pct(snapshot["ttm"].get("net_income"), market_cap), 4),
        "book_yield": clean_float(V._pct(snapshot["balance"].get("equity"), market_cap), 4),
        # The raw inputs of P / tangible book and ROTCE, for the group totals.
        **_book_fields(snapshot),
        "pe_forward": clean_float(V.forward_pe(price, ntm), 2),
        "eps_ntm": clean_float(ntm["eps"], 4) if ntm else None,
        # Per-share consensus at the other stages of the valuation path (VALUATION -> aggregates).
        "eps_fy_prev": clean_float((path or {}).get("fy_prev"), 4),
        "eps_fy0": clean_float((path or {}).get("fy0"), 4),
        "eps_fy1": clean_float((path or {}).get("fy1"), 4),
        "pe_history": has_history,
        # The reported history's latest point checks the table's P/E (both are
        # reported); the percentile is on the history's leading basis.
        "pe_history_current": clean_float(reported.get("current"), 2),
        "pe_operating": clean_float(lead.get("current"), 2) if basis != V.REPORTED else None,
        "pe_basis": basis,
        "pe_percentile": clean_float(lead.get("percentile"), 1),
        "pe_vs_median": clean_float(lead.get("vs_median"), 1),
    }


def _forward_aggregate(cap_frame: pd.DataFrame, columns: list[str], forward_earnings: dict[str, dict[str, float]]) -> dict | None:
    """A group's forward P/E on each day consensus was recorded: total cap
    that day over total NTM earnings, where the companies with an estimate
    hold at least AGGREGATE_MIN_COVERAGE of the cap."""
    days = sorted({d for s in columns for d in forward_earnings.get(s, {})})
    out_days, out_pe = [], []
    for day in days:
        at = cap_frame.loc[:pd.Timestamp(day), columns]
        if at.empty:
            continue
        caps = at.iloc[-1].dropna()
        with_estimate = [s for s in caps.index if day in forward_earnings.get(s, {})]
        total = caps.sum()
        if not total or caps[with_estimate].sum() < V.AGGREGATE_MIN_COVERAGE * total:
            continue
        profit = sum(forward_earnings[s][day] for s in with_estimate)
        out_days.append(day)
        out_pe.append(clean_float(caps[with_estimate].sum() / profit, 2) if profit > 0 else None)
    return {"dates": out_days, "pe": out_pe} if out_days else None


# Row field holding each valuation-path stage's per-share EPS.
PATH_FIELDS = {"fy_prev": "eps_fy_prev", "fy0": "eps_fy0", "ntm": "eps_ntm", "fy1": "eps_fy1"}


def _path(members: list[dict]) -> dict | None:
    """The group's multiple at each stage of the valuation path (see
    V.aggregate_path); per-share EPS become total earnings through the share
    count the row's market cap implies."""
    usable = [r for r in members if r.get("price")]
    stages = {key: {r["ticker"]: r[field] * r["market_cap"] / r["price"] for r in usable if r.get(field) is not None}
              for key, field in PATH_FIELDS.items()}
    return V.aggregate_path({r["ticker"]: r["market_cap"] for r in usable}, stages)


def _aggregates(ctx, rows: list[dict], caps: dict[str, pd.Series], earnings: dict[str, dict[str, pd.Series]],
                forward_earnings: dict[str, dict[str, float]] | None = None) -> dict | None:
    """Each index's and each sector's P/E against its own ten years, on
    operating earnings (each company on its own basis) and as reported.

    A company counts at today's share count throughout: its own P/E is exact
    on every date, but the weights between companies are today's, and the
    members are today's (no company that has left the index is in its past).
    """
    if not caps:
        return None
    scenario = ctx.config["valuation"]["scenario"]
    cap_frame = pd.DataFrame(caps)
    frames = {key: pd.DataFrame(values) for key, values in earnings.items()}
    groups = [(spec.key, spec.label, "index", None, [r["ticker"] for r in rows if spec.key in r["indices"]])
              for spec in ctx.indices]
    primary = [r for r in rows if ctx.primary.key in r["indices"] and r["sector"]]
    for sector in sorted({r["sector"] for r in primary}):
        groups.append((sector, sector, "sector", None, [r["ticker"] for r in primary if r["sector"] == sector]))
    # A divided sector's parts, by the config's sub-industry assignment. Companies
    # outside the price/earnings frames drop out below, so the parts can sum to
    # less than the sector; what no group claims is reported on the artifact.
    settings = ctx.config["valuation"]
    split = V.assign_subgroups([r for r in primary if r.get("sub_sector")], settings.get("subgroups") or [],
                               settings["subgroup_min_members"])
    for part in split["groups"]:
        groups.append((part["key"], part["label"], "subsector", part["parent"], part["tickers"]))
    dates, series = None, []
    for key, label, kind, parent, tickers in groups:
        columns = [t for t in tickers if t in cap_frame.columns]
        if not columns:
            continue
        entry = {"key": key, "label": label, "kind": kind, "companies": len(columns)}
        if parent:
            entry["parent"] = parent
        members = [r for r in rows if r["ticker"] in columns and r.get("market_cap")]
        forward = V.aggregate_forward({r["ticker"]: r["market_cap"] for r in members},
                                      {r["ticker"]: r["eps_ntm"] * r["market_cap"] / r["price"]
                                       for r in members if r.get("eps_ntm") is not None and r.get("price")})
        if forward:
            entry["forward_now"] = {"pe": clean_float(forward["pe"], 2), "coverage": clean_float(forward["coverage"], 3)}
            entry["scenario"] = [[clean_float(v, 1) for v in line] for line in
                                 V.scenario_grid(forward["pe"], scenario["multiple_turns"], scenario["eps_change_pct"])]
        book = V.aggregate_book(members)
        if book:
            entry["book"] = {k: clean_float(v, 3 if k.endswith("coverage") else 2) for k, v in book.items()}
        path = _path(members)
        if path:
            entry["path"] = {"stages": [{k: clean_float(v, 2) if isinstance(v, float) else v for k, v in st.items()}
                                        for st in path["stages"]],
                             "companies": path["companies"], "coverage": clean_float(path["coverage"], 3)}
        recorded = _forward_aggregate(cap_frame, columns, forward_earnings or {})
        if recorded:
            entry["forward_history"] = recorded
        for basis, frame_all in frames.items():
            frame = V.aggregate_pe(cap_frame[columns], frame_all.reindex(columns=columns)).iloc[-V.HISTORY_SESSIONS:]
            stats = V.pe_stats(frame["pe"])
            weekly = _weekly(frame)
            dates = dates or [d.strftime("%Y-%m-%d") for d in weekly.index]
            suffix = "" if basis == V.OPERATING else f"_{basis}"
            entry |= {
                f"coverage{suffix}": clean_float(frame["coverage"].iloc[-1], 3),
                f"stats{suffix}": _stats_json(stats) if stats else None,
                f"pe{suffix}": [clean_float(v, 2) for v in weekly["pe"].to_numpy()],
            }
        series.append(entry)
    return {
        "dates": dates,
        "series": series,
        "basis": V.OPERATING,
        "alternate": V.REPORTED,
        "window_sessions": V.HISTORY_SESSIONS,
        "min_coverage": V.AGGREGATE_MIN_COVERAGE,
        "scenario": {"multiple_turns": scenario["multiple_turns"], "eps_change_pct": scenario["eps_change_pct"]},
        "subgroups": {"min_members": settings["subgroup_min_members"], "unmatched": split["unmatched"],
                      "too_small": split["too_small"], "unassigned": split["unassigned"]},
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
            meta.setdefault(row.yahoo_symbol, {"name": str(row.name).title(), "sector": row.sector,
                                               "sub_sector": getattr(row, "sub_sector", None)})
            indices.setdefault(row.yahoo_symbol, []).append(key)

    if use_cache:
        sec.check_filings(cik_for(symbol, cik_map) for symbol in symbols)
    # Consensus for the forward multiple: EARNINGS read the whole universe's
    # this session, so these are the cached answers.
    try:
        trends, _ = estimates.fetch_trends(sorted(symbols))
    except Exception:
        trends = {}
    today = pd.Timestamp(ctx.as_of)
    recorded = snapshot_store.consensus_history((today - pd.Timedelta(days=V.HISTORY_SESSIONS * 7 // 5)).date(), today.date())
    rows, skipped = [], {}
    # Market cap and TTM earnings through time, one listing per company: a
    # second share class carries the whole company's cap again.
    caps, companies = {}, set()
    earnings: dict[str, dict[str, pd.Series]] = {V.OPERATING: {}, V.REPORTED: {}}
    forward_earnings: dict[str, dict[str, float]] = {}
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
        sector = meta.get(symbol, {}).get("sector")
        ntm = V.ntm_eps(trends.get(symbol), today)
        forward = _forward_series(symbol, ctx.prices.get(symbol), recorded, today, ntm)
        history = _history(symbol, data, ctx.prices.get(symbol), symbol_splits, sector, forward)
        fallback_cap = estimates.market_cap(symbol) if not data.trailing["shares"] and price is not None else None
        row = _row(symbol, meta.get(symbol, {}), data, price, indices.get(symbol, []), ctx.splits, history, ntm, fallback_cap,
                   V.fiscal_path(trends.get(symbol), ntm))
        rows.append(row)
        prices = ctx.prices.get(symbol)
        if (prices is not None and data.eps_history and row["market_cap"] and price and row["cik"] not in companies
                and row["shares_basis"] != YAHOO_CAP_BASIS):
            companies.add(row["cik"])
            shares = row["market_cap"] / price
            caps[symbol] = prices * shares
            earnings[V.REPORTED][symbol] = V.plausible_eps(prices, V.eps_steps(data.eps_history, symbol_splits)) * shares
            basis = V.operating_basis(data.eps_history, sector)
            operating = V.as_steps(V.operating_steps(data.eps_history, symbol_splits, basis))
            earnings[V.OPERATING][symbol] = V.plausible_eps(prices, operating) * shares
            if forward:
                forward_earnings[symbol] = {d: e * shares for d, e in zip(forward["dates"], forward["eps_ntm"]) if e is not None}

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
        "aggregates": _aggregates(ctx, rows, caps, earnings, forward_earnings),
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
