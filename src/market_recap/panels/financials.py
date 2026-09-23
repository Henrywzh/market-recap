"""FINANCIALS tab: ten years of filed statements for every index member.

The same SEC extraction feeds the DCF, so the two tabs cannot disagree about
what a company reported. Each column carries the date its figures were last
filed: "FY2023 revenue" means the value as most recently restated, and the
page says when that was.
"""

from __future__ import annotations

from ..compute import fundamentals as F
from ..config import FINANCIALS_ARTIFACT_DIR
from ..sources import sec
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, write_json

STATEMENT_LABELS = {"income": "INCOME STATEMENT", "balance": "BALANCE SHEET", "cash_flow": "CASH FLOW"}


def universe(ctx) -> list[str]:
    """Members of every index the contract names for this tab, deduplicated."""
    keys = list(ctx.config["financials"]["indices"])
    symbols: set[str] = set()
    for key in keys:
        frame = ctx.members.get(key)
        if frame is not None:
            symbols.update(frame["yahoo_symbol"])
    return sorted(symbols)


def cik_for(symbol: str, cik_map: dict[str, int]) -> int | None:
    """Yahoo writes share classes with a dash (BRK-B), SEC with a dot (BRK.B)."""
    return cik_map.get(symbol.replace("-", ".")) or cik_map.get(symbol)


def _payload(symbol: str, extracted: dict, meta: dict) -> dict:
    rows = extracted["rows"]
    columns = [
        {
            "fiscal_year": row["fiscal_year"],
            "period_end": row["period_end"],
            # When this column was last touched: a restatement moves it.
            "filed": max((row[f"{item.key}_filed"] or "") for item in sec.LINE_ITEMS) or None,
        }
        for row in rows
    ]
    values = {item.key: [clean_float(row[item.key], 4) for row in rows] for item in sec.LINE_ITEMS}
    ratios = {key: [clean_float(v, 4) for v in series] for key, series in F.ratio_table(rows).items()}
    return {
        "ticker": symbol,
        "name": meta.get("name"),
        "sector": meta.get("sector"),
        "entity_name": extracted["entity_name"],
        "cik": extracted["cik"],
        "source_ciks": extracted["source_ciks"],
        "source_url": extracted["source_url"],
        "columns": columns,
        "values": values,
        "ratios": ratios,
        "nwc_basis": [row["nwc_basis"] for row in rows],
    }


def build(ctx, *, use_cache: bool = True) -> dict:
    settings = ctx.config["financials"]
    years = int(settings["history_years"])
    symbols = universe(ctx)

    try:
        cik_map = sec.fetch_ticker_cik_map(use_cache=use_cache)
    except Exception as exc:
        ctx.log.fail("financials:cik_map", exc)
        return {"as_of": ctx.as_of, "available": [], "error": str(exc)[:ERROR_DETAIL_CHARS]}

    meta = {}
    for frame in ctx.members.values():
        for row in frame.drop_duplicates("yahoo_symbol").itertuples():
            meta.setdefault(row.yahoo_symbol, {"name": str(row.name).title(), "sector": row.sector})

    available, skipped = [], {}
    for symbol in symbols:
        cik = cik_for(symbol, cik_map)
        if cik is None:
            skipped[symbol] = "no CIK in SEC's ticker map"
            continue
        try:
            extracted = sec.extract_fundamentals(symbol, cik, years=years, use_cache=use_cache)
        except Exception as exc:
            skipped[symbol] = str(exc)[:ERROR_DETAIL_CHARS]
            continue
        write_json(FINANCIALS_ARTIFACT_DIR / f"{symbol}.json", _payload(symbol, extracted, meta.get(symbol, {})))
        available.append({"ticker": symbol, "name": meta.get(symbol, {}).get("name")})

    ctx.log.add(SourceRecord(
        "sec_financials", "SEC XBRL company facts (statements)",
        "https://data.sec.gov/api/xbrl/companyfacts/",
        rows=len(available),
        status="ok" if not skipped else "partial",
        error=None if not skipped else f"{len(skipped)} of {len(symbols)} not extracted",
    ))
    return {
        "as_of": ctx.as_of,
        "indices": list(settings["indices"]),
        "universe": len(symbols),
        "available": available,
        "skipped": skipped,
        "history_years": years,
        "statements": {
            statement: {
                "label": label,
                "items": [
                    {"key": item.key, "label": item.label, "unit": item.unit}
                    for item in sec.LINE_ITEMS if item.statement == statement
                ],
            }
            for statement, label in STATEMENT_LABELS.items()
        },
        "ratios": [{"key": ratio.key, "label": ratio.label, "unit": ratio.unit} for ratio, _ in F.RATIOS],
        "note": (
            "Annual figures from each company's own 10-K / 20-F / 40-F XBRL facts, as most recently "
            "filed: a restated year shows its restated value, and each column shows when it was last "
            "filed. A blank is a line the filer did not tag, never a zero. Share counts and EPS from "
            "years last filed before a stock split are put on today's share basis, using the split the "
            "company's own restatements reveal. Fiscal years are named by "
            "their period end; retailers whose year ends in late January call it the year before. "
            "Companies reporting under IFRS are not extracted."
        ),
    }
