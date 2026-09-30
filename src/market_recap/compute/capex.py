"""Quarterly capital expenditure from SEC XBRL company facts.

Cash-flow statements report year-to-date figures: a 10-Q for the second
quarter carries six months, the 10-K twelve. A quarter is taken as reported
where a three-month figure exists, and otherwise as the difference between
two year-to-date figures that share a fiscal-year start (Q4 = the 10-K's
year less the nine-month 10-Q).

Tags: purchases of property and equipment (``PaymentsToAcquire
PropertyPlantAndEquipment``; Amazon files the same line as
``PaymentsToAcquireProductiveAssets``), and the right-of-use assets taken
on under new finance leases (``RightOfUseAssetObtainedInExchangeFor
FinanceLeaseLiability``) -- capacity leased rather than bought, which is
$4-9bn a quarter at Microsoft and is not in the first line. Companies that
stopped tagging it (Meta, since 2023) show none rather than a stale figure.
"""

from __future__ import annotations

from datetime import date

CAPEX_TAGS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
LEASE_TAG = "RightOfUseAssetObtainedInExchangeForFinanceLeaseLiability"
QUARTER_DAYS = (80, 100)


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _rows(facts: dict, tag: str) -> dict[tuple[str, str], dict]:
    """(start, end) -> the latest-filed 10-Q/10-K value for that span."""
    units = (facts.get("facts", {}).get("us-gaap", {}).get(tag) or {}).get("units", {}).get("USD") or []
    out: dict[tuple[str, str], dict] = {}
    for r in units:
        if r.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A") or not r.get("start"):
            continue
        key = (r["start"], r["end"])
        if key not in out or r["filed"] > out[key]["filed"]:
            out[key] = r
    return out


def quarterly(facts: dict, tag: str) -> list[dict]:
    """[{end, value, filed, derived}] per fiscal quarter, oldest first."""
    rows = _rows(facts, tag)
    ends = sorted({end for _, end in rows})
    out = []
    for end in ends:
        spans = {start: r for (start, e), r in rows.items() if e == end}
        direct = [r for s, r in spans.items() if QUARTER_DAYS[0] <= _days(s, end) <= QUARTER_DAYS[1]]
        if direct:
            r = direct[0]
            out.append({"end": end, "value": r["val"], "filed": r["filed"], "derived": False})
            continue
        # Longest span ending here, less the same fiscal year's span ending one quarter earlier.
        for start, r in sorted(spans.items()):
            earlier = [(e, rows[(start, e)]) for (s, e) in rows if s == start and e < end
                       and QUARTER_DAYS[0] <= _days(e, end) <= QUARTER_DAYS[1]]
            if earlier:
                prior_end, prior = max(earlier)
                out.append({"end": end, "value": r["val"] - prior["val"], "filed": r["filed"], "derived": True})
                break
    return out


def capex_series(facts: dict) -> tuple[list[dict], str | None]:
    """Quarterly capex from whichever tag the filer uses most recently."""
    best, best_tag = [], None
    for tag in CAPEX_TAGS:
        series = quarterly(facts, tag)
        if series and (not best or series[-1]["end"] > best[-1]["end"]):
            best, best_tag = series, tag
    return best, best_tag


def with_growth(series: list[dict]) -> list[dict]:
    """Adds year-on-year growth (against the quarter ending ~a year earlier)."""
    by_end = {r["end"]: r for r in series}
    out = []
    for r in series:
        year_ago = next((by_end[e] for e in by_end if 350 <= _days(e, r["end"]) <= 380), None)
        yoy = round(100 * (r["value"] / year_ago["value"] - 1), 1) if year_ago and year_ago["value"] > 0 else None
        out.append({**r, "yoy_pct": yoy})
    return out
