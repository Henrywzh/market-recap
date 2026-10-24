"""BY BUSINESS: revenue and profit by segment, product and region per company.

From each company's own 10-K and 10-Q XBRL (sources.segments): about fifteen
years of annual figures from every other 10-K, and five years of quarters from
the last twelve 10-Qs, the fourth quarter as the year less nine months. Filings
are cached per accession, so a night reads only what was filed since; the first
builds fill the history within a budget per build, newest filings first across
every company, and the index says how many are still to come.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..compute import segments as C
from ..config import ARTIFACT_DIR
from ..sources import sec
from ..sources import segments as S
from ..util import ERROR_DETAIL_CHARS, SourceRecord, prune_stale, write_json
from .financials import cik_for, universe

SEGMENTS_ARTIFACT_DIR = ARTIFACT_DIR / "segments"
# Filings not yet cached that one build reads (~0.4 MB each). The whole universe
# is about 9,500 filings, so a first fill takes a few builds.
DEFAULT_BUDGET = 2500
INDEX_WORKERS = 6

NOTE = (
    "From each company's own 10-K and 10-Q XBRL: the breakdowns it reports beside its statements. "
    "Segments are the company's own operating segments (ASC 280), with the profit measure its "
    "management uses -- often before corporate costs, R&D or amortisation the company keeps "
    "unallocated -- so a segment margin compares with the same company's history, not with "
    "another company's segment. Products and regions are revenue only. Each period is read from the "
    "newest filing that breaks it down, so a year recast after a reorganisation shows as recast. "
    "A breakdown is shown when its parts add up to the reported total (within 1%); subtotals beside "
    "their parts are left out. A fourth quarter is the year less nine months where the filer does "
    "not report it."
)


def _order(by_symbol: dict[str, list]) -> list:
    """Every filing, newest first within a company, and the companies interleaved:
    each company's latest filing before any company's second."""
    out = []
    depth = max((len(v) for v in by_symbol.values()), default=0)
    for rank in range(depth):
        out += [filings[rank] for filings in by_symbol.values() if rank < len(filings)]
    return out


def _coverage(views: dict) -> dict:
    out = {}
    for view, kinds in views.items():
        out[view] = {kind: {"periods": len(series["periods"]), "first": series["periods"][0]["label"],
                            "last": series["periods"][-1]["label"], "members": len(series["members"])}
                     for kind, series in kinds.items()}
    return out


def build(ctx, *, use_cache: bool = True) -> dict:
    settings = ctx.config.get("segments") or {}
    budget = int(settings.get("budget", DEFAULT_BUDGET))
    symbols = universe(ctx)
    try:
        cik_map = sec.fetch_ticker_cik_map(use_cache=use_cache)
    except Exception as exc:
        ctx.log.fail("segments:cik_map", exc)
        return {"as_of": ctx.as_of, "available": [], "error": str(exc)[:ERROR_DETAIL_CHARS]}

    by_symbol: dict[str, list] = {}
    skipped: dict[str, str] = {}
    ciks = {}
    for symbol in symbols:
        cik = cik_for(symbol, cik_map)
        if cik is None:
            skipped[symbol] = "no CIK in SEC's ticker map"
        else:
            ciks[symbol] = cik

    def index(symbol):
        try:
            return symbol, S.statement_filings(ciks[symbol]), None
        except Exception as exc:
            return symbol, None, f"filing index: {str(exc)[:ERROR_DETAIL_CHARS]}"

    # Side by side under SEC's shared throttle: a first build reads a further
    # page of the filing index for most companies.
    with ThreadPoolExecutor(INDEX_WORKERS) as pool:
        for symbol, filings, why in pool.map(index, ciks):
            if filings is None:
                skipped[symbol] = why
            else:
                by_symbol[symbol] = filings
    fetch = S.fetch_missing(_order(by_symbol), budget)

    available, pending_total = [], 0
    for symbol, filings in by_symbol.items():
        payloads = [S.cached(f) for f in filings]
        pending = sum(p is None for p in payloads)
        pending_total += pending
        read = [p for p in payloads if p]
        if not read:
            skipped.setdefault(symbol, "no filing read yet" if pending else "no breakdown in its filings")
            continue
        try:
            views = C.breakdown(read)
        except Exception as exc:
            skipped[symbol] = str(exc)[:ERROR_DETAIL_CHARS]
            continue
        if not views:
            skipped[symbol] = "no breakdown that adds up to the reported total"
            continue
        write_json(SEGMENTS_ARTIFACT_DIR / f"{symbol}.json", {
            "ticker": symbol, "filings_read": len(read), "filings_pending": pending,
            "latest_filed": max(p["filed"] for p in read), "views": views,
        })
        available.append({"ticker": symbol, "views": sorted(views), "coverage": _coverage(views), "pending": pending})

    prune_stale(SEGMENTS_ARTIFACT_DIR, (row["ticker"] for row in available))
    if hasattr(ctx, "diagnostics"):
        ctx.diagnostics["segments"] = {"fetched": fetch["fetched"], "failed": len(fetch["failed"]),
                                       "deferred": fetch["deferred"]}
    ctx.log.add(SourceRecord(
        "sec_segments", "SEC filings' XBRL (segment, product and region breakdowns)",
        "https://www.sec.gov/Archives/edgar/data/",
        rows=len(available), policy="filings",
        status="ok" if not fetch["failed"] and not pending_total else "partial",
        error=(f"{pending_total} filings still to read; {len(fetch['failed'])} failed this build"
               if pending_total or fetch["failed"] else None),
    ))
    return {
        "as_of": ctx.as_of,
        "universe": len(symbols),
        "available": available,
        "skipped": skipped,
        "filings_pending": pending_total,
        "fetched_this_build": fetch["fetched"],
        "failed": dict(list(fetch["failed"].items())[:50]),
        "note": NOTE,
    }
