"""SECTORS hub: the market, its eleven GICS sectors, their sub-industries and their names.

Read from this session's other artifacts, and it fetches nothing. HEATMAPS gives
the S&P 500 names with their index weights, sectors and sub-industries, and the
fund returns. MONITOR gives each name's drawdown, trend, EPS revisions and
earnings date; VALUATION its forward P/E, book multiples and their percentiles.
A sector's fund comes from config ``universe.sectors``; its rotation quadrant
from ROTATION, its evidence and medians from INDUSTRIES, its ten-year multiple
band from VALUATION's sector series. THEMES groups are tied to a sector or a
sub-industry through config ``[sectors]``, and the rest are listed as cross-sector.

Sector and sub-industry returns are cap-weighted from the names (compute.sectors).
A sub-industry INDUSTRIES did not read (fewer names than its minimum) keeps its
returns and weight and leaves its evidence empty. An input that did not build
leaves the fields that read it empty and is named in ``missing``; HEATMAPS is
required, since without it there are no names to show.
"""

from __future__ import annotations

from ..compute import industries as I
from ..compute import sectors as S
from ..util import clean_float, company_name

# Panels read, each required to be from this session (build.optional_panel).
INPUTS = ("heatmaps", "industries", "rotation", "valuation", "monitor", "themes")
BENCHMARK = {"label": "S&P 500", "symbol": "SPY"}
# The window that orders the best and worst name in a sector.
RANK_PERIOD = "3M"
NOTES = [
    "Returns are cap-weighted from the names' published index weights; a sub-industry's evidence (down share, drawdown, revisions, P/E) is the median of its names, as on INDUSTRIES.",
    "Sub-industries are as the holdings file names them; a name the Wikipedia GICS list did not cover takes its sub-industry from Yahoo's fallback classification.",
]


def _by_ticker(panel: dict | None, key: str = "rows") -> dict[str, dict]:
    return {row["ticker"]: row for row in ((panel or {}).get(key) or []) if row.get("ticker")}


def _flag(value) -> bool | None:
    return None if value is None else bool(value)


def _symbol(item) -> str | None:
    """A THEMES bellwether as a ticker: the artifact writes each as a dict with a ``symbol``; the config gives strings."""
    return item.get("symbol") if isinstance(item, dict) else item


def _weight(rows: list[dict]) -> float:
    return sum(clean_float(row.get("weight")) or 0.0 for row in rows)


def _returns(rows: list[dict], periods: list[str], benchmark: dict) -> tuple[dict, dict]:
    """Cap-weighted returns of ``rows`` and their gap to the benchmark, in percent and points."""
    raw = S.weighted_returns(rows, periods)
    returns = {p: clean_float(raw[p], 2) for p in periods}
    versus = {p: clean_float(S.excess(raw[p], clean_float(benchmark.get(p))), 2) for p in periods}
    return returns, versus


def _industry_fields(row: dict | None) -> dict:
    """The INDUSTRIES reading shared by a sector and a sub-industry; all empty when not read."""
    row = row or {}
    revision = row.get("revision") or {}
    evidence = row.get("evidence") or {}
    return {
        "above_200d": clean_float(row.get("above_ma"), 0),
        "down_share_1m": clean_float(row.get("down_share"), 0),
        "median_drawdown": clean_float(row.get("drawdown"), 1),
        "revision": {
            "30d": clean_float(revision.get("30d"), 1),
            "90d": clean_float(revision.get("90d"), 1),
            "names": revision.get("names"),
        },
        "forward_pe": clean_float((row.get("forward_pe") or {}).get("median"), 1),
        "pe_percentile": clean_float((row.get("pe_percentile") or {}).get("median"), 0),
        "evidence": {
            "sold_off": evidence.get("sold_off"),
            "estimates_cut": evidence.get("estimates_cut"),
            "cheap_vs_own_history": evidence.get("cheap_vs_own_history"),
        },
    }


def _pe(value, digits: int, applies: bool) -> float | None:
    """A P/E figure, or None where the sector is not valued on earnings (a REIT, see [industries])."""
    return clean_float(value, digits) if applies else None


def _extreme(item: dict | None) -> dict | None:
    return None if item is None else {"ticker": item["ticker"], "return": clean_float(item["return"], 1)}


def _valuation(series: dict | None, *, pe_applies: bool) -> dict:
    """The sector's own ten-year band: P/E where it is the multiple, P/TBV where it is kept."""
    series = series or {}
    stats, book = series.get("stats") or {}, series.get("stats_ptbv") or {}
    return {
        "pe_now": _pe(stats.get("current"), 1, pe_applies),
        "pe_median_10y": _pe(stats.get("median"), 1, pe_applies),
        "pe_p25": _pe(stats.get("p25"), 1, pe_applies),
        "pe_p75": _pe(stats.get("p75"), 1, pe_applies),
        "ptbv_now": clean_float(book.get("current"), 2),
        "ptbv_median_10y": clean_float(book.get("median"), 2),
    }


def _next_report(watch: dict) -> dict | None:
    date = watch.get("earnings_date")
    return {"date": date, "timing": watch.get("earnings_status")} if date else None


def _member(row: dict, *, sector_key: str, sub_key: str, watch: dict, value: dict,
            periods: list[str], pe_applies: bool) -> dict:
    expect = watch.get("expectations") or {}
    # The same revision definition INDUSTRIES uses, so a name reads one way on both pages.
    rev30 = I.revision(expect.get("eps"), expect.get("eps_30d"), expect.get("change_30d_pct"))
    rev90 = I.revision(expect.get("eps"), expect.get("eps_90d"), expect.get("change_90d_pct"))
    return {
        "ticker": row["ticker"],
        "name": company_name(row.get("name")),
        "sector_key": sector_key,
        "sub_key": sub_key,
        "weight": clean_float(row.get("weight"), 3),
        "price": clean_float(row.get("price"), 2),
        "returns": {p: clean_float((row.get("returns") or {}).get(p), 2) for p in periods},
        "drawdown": clean_float(watch.get("drawdown_pct"), 1),
        "above_200d": _flag(watch.get("above_ma")),
        "revision_30d": clean_float(rev30, 1),
        "revision_90d": clean_float(rev90, 1),
        "forward_pe": _pe(value.get("pe_forward"), 1, pe_applies),
        "pe_percentile": _pe(value.get("pe_percentile"), 0, pe_applies),
        "ptbv": clean_float(value.get("ptbv"), 2),
        "ptbv_percentile": clean_float(value.get("ptbv_percentile"), 0),
        "rotce": clean_float(value.get("rotce"), 1),
        "next_report": _next_report(watch),
        "monitor": {
            "queued": _flag(watch.get("candidate")),
            "price_state": watch.get("price_state"),
            "evidence_state": watch.get("evidence_state"),
        },
    }


def build(ctx, inputs: dict) -> dict:
    heatmaps = inputs.get("heatmaps")
    if heatmaps is None:
        raise RuntimeError("sectors needs the heatmaps panel (the S&P 500 names and fund returns); it did not build this session")
    industries, rotation = inputs.get("industries"), inputs.get("rotation")
    valuation, monitor, themes = inputs.get("valuation"), inputs.get("monitor"), inputs.get("themes")
    missing = [name for name in INPUTS if inputs.get(name) is None]

    config = ctx.config
    # The thresholds and the no-P/E sectors are INDUSTRIES' own; the config stands in if it did not build.
    settings = (industries or {}).get("settings") or config["industries"]
    thin_below = settings["thin_below"]
    no_pe = set(settings.get("no_pe_sectors") or [])
    funds = config["universe"]["sectors"]
    section = config.get("sectors") or {}
    sector_themes = dict(section.get("sector_themes") or {})
    sub_themes = dict(section.get("sub_industry_themes") or {})
    # A sub-industry with VALUATION's own subsector band (the bank groups' P/TBV).
    sub_bands = dict(section.get("sub_industry_valuation") or {})

    periods = list(heatmaps.get("periods") or [])
    etfs = {row["ticker"]: row for row in heatmaps.get("etfs") or [] if row.get("ticker")}
    benchmark = (etfs.get(BENCHMARK["symbol"]) or {}).get("returns") or {}
    watch, value = _by_ticker(monitor), _by_ticker(valuation)
    ind_sectors = {row["sector"]: row for row in (industries or {}).get("sectors") or []}
    ind_subs = {(row["sector"], row["label"]): row for row in (industries or {}).get("sub_industries") or []}
    quadrants = {g["key"]: (g.get("cap") or {}).get("quadrant") for g in (rotation or {}).get("groups") or []}
    all_series = ((valuation or {}).get("aggregates") or {}).get("series") or []
    series = {s["key"]: s for s in all_series if s.get("kind") == "sector"}
    bands = {s["key"]: s for s in all_series if s.get("kind") == "subsector"}

    by_sector: dict[str, list[dict]] = {}
    for row in heatmaps.get("constituents") or []:
        if row.get("ticker"):
            by_sector.setdefault(row["sector"], []).append(row)
    # Heaviest first. Keys are assigned in label order, so they do not move when weights do.
    sector_order = sorted(by_sector, key=lambda s: (-_weight(by_sector[s]), s))
    sector_keys: dict[str, str] = {}
    sub_keys: dict[tuple[str, str], str] = {}
    for sector in sector_order:
        sector_keys[sector] = funds.get(sector) or f"S-{S.initials(sector)}"
        taken: set[str] = set()
        for sub in sorted({row["sub_sector"] for row in by_sector[sector]}):
            key = S.sub_key(sector_keys[sector], sub, taken)
            taken.add(key)
            sub_keys[(sector, sub)] = key

    sectors_out, subs_out, members_out = [], [], []
    for sector in sector_order:
        rows = by_sector[sector]
        pe_applies = sector not in no_pe
        sub_rows: dict[str, list[dict]] = {}
        for row in rows:
            sub_rows.setdefault(row["sub_sector"], []).append(row)
        sub_order = sorted(sub_rows, key=lambda s: (-_weight(sub_rows[s]), s))

        for sub in sub_order:
            members = sub_rows[sub]
            key = sub_keys[(sector, sub)]
            returns, versus = _returns(members, periods, benchmark)
            count = len(members)
            subs_out.append({
                "key": key,
                "label": sub,
                "sector": sector,
                "sector_key": sector_keys[sector],
                "members": count,
                "weight": clean_float(_weight(members), 2),
                "thin": count < thin_below,
                "returns": returns,
                "vs_index": versus,
                **_industry_fields(ind_subs.get((sector, sub))),
                "valuation": _valuation(bands[sub_bands[sub]], pe_applies=pe_applies) if sub_bands.get(sub) in bands else None,
                "theme": sub_themes.get(sub),
            })
        for row in sorted(rows, key=lambda r: (-(clean_float(r.get("weight")) or 0.0), r["ticker"])):
            members_out.append(_member(
                row, sector_key=sector_keys[sector], sub_key=sub_keys[(sector, row["sub_sector"])],
                watch=watch.get(row["ticker"]) or {}, value=value.get(row["ticker"]) or {},
                periods=periods, pe_applies=pe_applies,
            ))

        returns, versus = _returns(rows, periods, benchmark)
        best, worst = S.best_and_worst(rows, RANK_PERIOD)
        fund = etfs.get(funds.get(sector) or "")
        ind_row = ind_sectors.get(sector)
        sectors_out.append({
            "key": sector_keys[sector],
            "label": sector,
            "etf": funds.get(sector),
            "weight": clean_float(_weight(rows), 2),
            "members": len(rows),
            "returns": returns,
            "vs_index": versus,
            "etf_returns": {p: clean_float((fund.get("returns") or {}).get(p), 2) for p in periods} if fund else None,
            "quadrant": quadrants.get(sector),
            **_industry_fields(ind_row),
            "valuation": _valuation(series.get(sector), pe_applies=pe_applies),
            "best": _extreme(best),
            "worst": _extreme(worst),
            "theme": sector_themes.get(sector),
            "sub_industries": [sub_keys[(sector, sub)] for sub in sub_order],
        })

    benchmark_out = {
        **BENCHMARK,
        "returns": {p: clean_float(benchmark.get(p), 2) for p in periods},
    }
    # A THEMES group tied to neither a sector nor a sub-industry, listed as cross-sector.
    mapped = set(sector_themes.values()) | set(sub_themes.values())
    cross = [
        {
            "key": group["key"],
            "label": group.get("label"),
            "proxy": group.get("proxy"),
            "members": [_symbol(item) for item in group.get("bellwethers") or [] if _symbol(item)],
        }
        for group in (themes or {}).get("groups") or []
        if group.get("key") and group["key"] not in mapped
    ]
    members_out.sort(key=lambda m: (-(m["weight"] or 0.0), m["ticker"]))
    return {
        "as_of": ctx.as_of,
        "periods": periods,
        "benchmark": benchmark_out,
        "sectors": sectors_out,
        "sub_industries": subs_out,
        "members": members_out,
        "themes": cross,
        "notes": list(NOTES),
        "missing": missing,
    }
