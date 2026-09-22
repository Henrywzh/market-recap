"""SEC XBRL company facts -- the free fundamentals behind the DCF tab.

data.sec.gov sends no ``Access-Control-Allow-Origin`` header, so a static page
cannot fetch it from the browser. Fundamentals are therefore extracted at build
time into a small per-ticker artifact, and the interactive model runs on that.

Each extracted figure keeps the filing's ``filed`` date, because "FY2025
revenue" is only meaningful alongside when it became public.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import time

import httpx
import pandas as pd

from ..config import CACHE_DIR, SEC_USER_AGENT

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Annual report forms. A foreign private issuer files 20-F or 40-F rather
# than a 10-K, and excluding them would silently drop every ADR.
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}

# SEC asks for no more than ten requests per second from one client.
_MIN_INTERVAL = 0.12
_last_call = 0.0

# Line items the DCF needs, each with the US-GAAP tags that actually carry them
# across filers. Order matters: the first tag with data wins.
LINE_ITEMS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "ebit": ("OperatingIncomeLoss",),
    "taxes": ("IncomeTaxExpenseBenefit",),
    "dep_amort": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
        "PaymentsForCapitalImprovements",
    ),
    "nwc_change": ("IncreaseDecreaseInOperatingCapital",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_investments": ("ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
    "total_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "shares": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
    "pretax_income": ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",),
}

# Most filers never tag ``IncreaseDecreaseInOperatingCapital``. Where they do
# not, the change in working capital is taken from the balance sheet as the
# year-over-year move in current assets less current liabilities.
#
# This is the plain definition, and it deliberately does NOT strip cash or
# short-term borrowings out of the two totals. That matters: a company that
# simply banked more cash will show a working-capital "build" here. The figure
# is reported under that name so the number can be checked, and the DCF tab
# says so beside the row.
NWC_ASSETS_TAG = "AssetsCurrent"
NWC_LIABILITIES_TAG = "LiabilitiesCurrent"


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch_ticker_cik_map(*, use_cache: bool = True) -> dict[str, int]:
    path = CACHE_DIR / "sec" / "company_tickers.json"
    if use_cache and path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(days=7):
            payload = json.loads(path.read_text(encoding="utf-8"))
            return {v["ticker"].upper(): int(v["cik_str"]) for v in payload.values()}
    _throttle()
    response = httpx.get(TICKERS_URL, headers={"User-Agent": SEC_USER_AGENT}, timeout=45.0)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding="utf-8")
    payload = response.json()
    return {v["ticker"].upper(): int(v["cik_str"]) for v in payload.values()}


def fetch_company_facts(cik: int, *, use_cache: bool = True) -> dict:
    path = CACHE_DIR / "sec" / "facts" / f"CIK{cik:010d}.json"
    if use_cache and path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(days=3):
            return json.loads(path.read_text(encoding="utf-8"))
    _throttle()
    response = httpx.get(FACTS_URL.format(cik=cik), headers={"User-Agent": SEC_USER_AGENT}, timeout=60.0)
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding="utf-8")
    return response.json()


def _annual_values(facts: dict, tags: tuple[str, ...]) -> dict[int, dict]:
    """One annual figure per fiscal year, falling back across tags per year.

    A filer can report revenue under ``Revenues`` in one year and
    ``RevenueFromContractWithCustomerExcludingAssessedTax`` in the next, so
    picking a single winning tag for the whole company silently blanks half
    the history. Tags are tried in priority order *for each year* instead.

    ``form == 10-K`` and ``fp == FY`` keeps a quarter from being presented as
    a year, and the latest ``filed`` wins so a restated year shows its most
    recent published value along with when that was.
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    picked: dict[int, dict] = {}

    for priority, tag in enumerate(tags):
        units = gaap.get(tag, {}).get("units", {})
        series = units.get("USD") or units.get("shares") or next(iter(units.values()), None)
        if not series:
            continue
        for row in series:
            if row.get("form") not in ANNUAL_FORMS or row.get("fp") != "FY":
                continue
            year, start, end = row.get("fy"), row.get("start"), row.get("end")
            if year is None or end is None or row.get("val") is None:
                continue
            if start is not None:
                # A flow item's duration must actually be a year; anything
                # else is a quarter or a cumulative stub.
                span = (pd.Timestamp(end) - pd.Timestamp(start)).days
                if not 300 <= span <= 400:
                    continue
            current = picked.get(year)
            if current is None:
                picked[year] = {"value": row["val"], "filed": row.get("filed"), "end": end, "tag": tag, "priority": priority}
                continue
            # A higher-priority tag wins outright; within one tag, the newest
            # filing wins.
            if priority < current["priority"]:
                picked[year] = {"value": row["val"], "filed": row.get("filed"), "end": end, "tag": tag, "priority": priority}
            elif priority == current["priority"] and (row.get("filed") or "") >= (current["filed"] or ""):
                picked[year] = {"value": row["val"], "filed": row.get("filed"), "end": end, "tag": tag, "priority": priority}
    return picked


def extract_fundamentals(ticker: str, cik: int, *, years: int = 5, use_cache: bool = True) -> dict:
    facts = fetch_company_facts(cik, use_cache=use_cache)
    extracted = {item: _annual_values(facts, tags) for item, tags in LINE_ITEMS.items()}

    # Rebuild the working-capital change from the balance sheet where the
    # filer did not tag it directly. A year whose prior year is missing stays
    # None: a "change" needs two observations, and defaulting it to zero would
    # quietly add a year of free cash flow.
    current_assets = _annual_values(facts, (NWC_ASSETS_TAG,))
    current_liabilities = _annual_values(facts, (NWC_LIABILITIES_TAG,))
    nwc_level = {
        year: float(current_assets[year]["value"]) - float(current_liabilities[year]["value"])
        for year in set(current_assets) & set(current_liabilities)
        if current_assets[year]["value"] is not None and current_liabilities[year]["value"] is not None
    }
    for year, level in nwc_level.items():
        if year - 1 not in nwc_level or extracted["nwc_change"].get(year) is not None:
            continue
        extracted["nwc_change"][year] = {
            "value": level - nwc_level[year - 1],
            "filed": current_assets[year]["filed"],
            "end": current_assets[year]["end"],
            "tag": "derived:AssetsCurrent-LiabilitiesCurrent",
            "priority": 99,
        }

    known_years = sorted({y for values in extracted.values() for y in values})
    if not known_years:
        raise ValueError(f"{ticker}: no annual US-GAAP facts found")
    fiscal_years = known_years[-years:]

    rows = []
    for year in fiscal_years:
        row: dict = {"fiscal_year": year}
        for item, values in extracted.items():
            entry = values.get(year)
            row[item] = entry["value"] if entry else None
            row[f"{item}_filed"] = entry["filed"] if entry else None
        row["nwc_basis"] = (extracted["nwc_change"].get(year) or {}).get("tag")
        rows.append(row)

    return {
        "ticker": ticker,
        "cik": cik,
        "entity_name": facts.get("entityName"),
        "fiscal_years": fiscal_years,
        "rows": rows,
        "source": "SEC XBRL company facts",
        "source_url": FACTS_URL.format(cik=cik),
    }
