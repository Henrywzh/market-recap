"""SEC XBRL company facts -- the free fundamentals behind the DCF tab.

data.sec.gov sends no ``Access-Control-Allow-Origin`` header, so a static page
cannot fetch it from the browser. Fundamentals are therefore extracted at build
time into a small per-ticker artifact, and the interactive model runs on that.

Each extracted figure keeps the filing's ``filed`` date, because "FY2025
revenue" is only meaningful alongside when it became public.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from functools import lru_cache
import json
import time

import httpx
import pandas as pd

from .. import cache
from ..config import SEC_USER_AGENT

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Annual report forms. A foreign private issuer files 20-F or 40-F rather
# than a 10-K, and excluding them would silently drop every ADR.
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}

# SEC asks for no more than ten requests per second from one client.
_MIN_INTERVAL = 0.12
_last_call = 0.0

# Every line item this repository reads from a filing, with the US-GAAP tags
# that actually carry it across filers. Order matters: for each fiscal year the
# first tag with a value wins, because filers switch tags between years.
#
# One table for the DCF and the FINANCIALS tab: two tag lists for "revenue"
# would be two claims about what revenue is.


@dataclass(frozen=True)
class LineItem:
    key: str
    label: str
    tags: tuple[str, ...]
    statement: str          # income | balance | cash_flow
    unit: str = "USD"       # the XBRL unit the value is reported in

    @property
    def instant(self) -> bool:
        """A balance-sheet figure is a point in time, not a flow over a year."""
        return self.statement == "balance"


LINE_ITEMS: tuple[LineItem, ...] = (
    # --- Income statement
    LineItem("revenue", "Revenue", (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ), "income"),
    LineItem("cost_of_revenue", "Cost of revenue", (
        "CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
    ), "income"),
    LineItem("gross_profit", "Gross profit", ("GrossProfit",), "income"),
    LineItem("rnd", "R&D", ("ResearchAndDevelopmentExpense",), "income"),
    LineItem("sga", "SG&A", ("SellingGeneralAndAdministrativeExpense",), "income"),
    LineItem("ebit", "Operating income (EBIT)", ("OperatingIncomeLoss",), "income"),
    LineItem("interest_expense", "Interest expense", (
        "InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
    ), "income"),
    LineItem("pretax_income", "Pre-tax income", (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ), "income"),
    LineItem("taxes", "Income tax", ("IncomeTaxExpenseBenefit",), "income"),
    LineItem("net_income", "Net income", ("NetIncomeLoss", "ProfitLoss"), "income"),
    LineItem("eps_diluted", "Diluted EPS", ("EarningsPerShareDiluted",), "income", unit="USD/shares"),
    LineItem("shares", "Diluted shares", (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ), "income", unit="shares"),
    # --- Balance sheet
    LineItem("cash", "Cash & equivalents", (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ), "balance"),
    LineItem("short_term_investments", "Short-term investments", (
        "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ), "balance"),
    LineItem("current_assets", "Current assets", ("AssetsCurrent",), "balance"),
    LineItem("total_assets", "Total assets", ("Assets",), "balance"),
    LineItem("current_liabilities", "Current liabilities", ("LiabilitiesCurrent",), "balance"),
    LineItem("total_debt", "Long-term debt", ("LongTermDebtNoncurrent", "LongTermDebt"), "balance"),
    LineItem("total_liabilities", "Total liabilities", ("Liabilities",), "balance"),
    LineItem("equity", "Shareholders' equity", (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ), "balance"),
    # --- Cash flow
    LineItem("operating_cash_flow", "Operating cash flow", (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ), "cash_flow"),
    LineItem("capex", "Capital expenditure", (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
        "PaymentsForCapitalImprovements",
    ), "cash_flow"),
    LineItem("dep_amort", "D&A", (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ), "cash_flow"),
    LineItem("sbc", "Stock-based compensation", ("ShareBasedCompensation",), "cash_flow"),
    LineItem("nwc_change", "Change in NWC", ("IncreaseDecreaseInOperatingCapital",), "cash_flow"),
    LineItem("buybacks", "Share repurchases", ("PaymentsForRepurchaseOfCommonStock",), "cash_flow"),
    LineItem("dividends_paid", "Dividends paid", (
        "PaymentsOfDividends", "PaymentsOfDividendsCommonStock",
    ), "cash_flow"),
)
ITEMS_BY_KEY = {item.key: item for item in LINE_ITEMS}

# A flow item's duration must actually be a year; anything else is a quarter
# or a cumulative stub. 52/53-week years land well inside this.
ANNUAL_SPAN_DAYS = (300, 400)

# Most filers never tag ``IncreaseDecreaseInOperatingCapital``. Where they do
# not, the change in working capital is taken from the balance sheet as the
# year-over-year move in current assets less current liabilities.
#
# This is the plain definition, and it deliberately does NOT strip cash or
# short-term borrowings out of the two totals. That matters: a company that
# simply banked more cash will show a working-capital "build" here. The figure
# is reported under that name so the number can be checked, and the DCF tab
# says so beside the row.
NWC_DERIVED_TAG = "derived:AssetsCurrent-LiabilitiesCurrent"

NAMESPACE = "sec"


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _get(url: str, timeout: float) -> str:
    """SEC asks automated clients to identify themselves and to stay under ten
    requests a second; the throttle is shared across every call in the build."""
    _throttle()
    response = httpx.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_ticker_cik_map(*, use_cache: bool = True) -> dict[str, int]:
    text = cache.fetch_text(
        NAMESPACE,
        "company_tickers",
        lambda: _get(TICKERS_URL, 45.0),
        kind="reference_data",
        suffix=".json",
        use_cache=use_cache,
    )
    return {v["ticker"].upper(): int(v["cik_str"]) for v in json.loads(text).values()}


def fetch_company_facts(cik: int, *, use_cache: bool = True) -> dict:
    text = cache.fetch_text(
        f"{NAMESPACE}/facts",
        f"CIK{cik:010d}",
        lambda: _get(FACTS_URL.format(cik=cik), 60.0),
        kind="filings",
        suffix=".json",
        use_cache=use_cache,
        # 3-4 MB of JSON per filer, of which this reads a handful of tags.
        compress=True,
    )
    return json.loads(text)


def _has_annual_facts(facts: dict) -> bool:
    for tag in ITEMS_BY_KEY["revenue"].tags + ITEMS_BY_KEY["net_income"].tags:
        for rows in facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).values():
            if any(r.get("form") in ANNUAL_FORMS and r.get("fp") == "FY" for r in rows):
                return True
    return False


def _predecessor_ciks(facts: dict, cik: int) -> list[int]:
    """Other registrants that submitted this entity's filings, most frequent first.

    An accession number starts with the CIK of whoever submitted it. After a
    holding-company reorganisation the new registrant's filings are submitted
    under the old CIK -- which is where the decade of history still lives.
    (Filing agents also appear here; the caller only accepts a candidate whose
    entity name matches.)
    """
    counts: dict[int, int] = {}
    for concept in facts.get("facts", {}).get("us-gaap", {}).values():
        for rows in concept.get("units", {}).values():
            for row in rows:
                prefix = int(str(row.get("accn", "0"))[:10] or 0)
                if prefix and prefix != cik:
                    counts[prefix] = counts.get(prefix, 0) + 1
    return sorted(counts, key=counts.get, reverse=True)


def _merge(newer: dict, older: dict) -> dict:
    """Union two filers' us-gaap facts; the extraction's latest-filed rule decides overlaps."""
    merged = {**newer, "facts": {**newer.get("facts", {})}}
    gaap = {tag: {**concept, "units": {u: list(r) for u, r in concept.get("units", {}).items()}}
            for tag, concept in newer.get("facts", {}).get("us-gaap", {}).items()}
    for tag, concept in older.get("facts", {}).get("us-gaap", {}).items():
        target = gaap.setdefault(tag, {**concept, "units": {}})
        for unit, rows in concept.get("units", {}).items():
            target["units"].setdefault(unit, []).extend(rows)
    merged["facts"]["us-gaap"] = gaap
    return merged


def fetch_filer_facts(cik: int, *, use_cache: bool = True) -> tuple[dict, list[int]]:
    """Company facts for a filer, followed back to its predecessor if needed.

    Returns the facts and the CIKs they were read from. SEC's ticker map points
    at the *current* registrant: after Exxon's 2026 reorganisation that is a
    CIK holding one 10-Q, and a build that trusted it dropped XOM entirely.
    """
    facts = fetch_company_facts(cik, use_cache=use_cache)
    sources = [cik]
    if _has_annual_facts(facts):
        return facts, sources
    name = str(facts.get("entityName") or "").strip().lower()
    for candidate in _predecessor_ciks(facts, cik):
        try:
            older = fetch_company_facts(candidate, use_cache=use_cache)
        except Exception:
            continue
        if name and str(older.get("entityName") or "").strip().lower() == name:
            return _merge(facts, older), sources + [candidate]
    return facts, sources


# A 52/53-week year that ends on the Saturday nearest 31 December can end on
# 3 January; it is still the year before.
FISCAL_YEAR_END_GRACE_DAYS = 7


def fiscal_year(period_end: str) -> int:
    """The year a fiscal period is named for, from its end date.

    Not the filing's ``fy`` field, which SEC fills inconsistently for
    January year-ends (CrowdStrike has two periods it calls 2022). The end
    date's year matches how NVIDIA, CrowdStrike, Microsoft and Apple name their
    years; retailers ending in late January call it the year before, which is
    why the page prints the period end beside every label.
    """
    return (pd.Timestamp(period_end) - pd.Timedelta(days=FISCAL_YEAR_END_GRACE_DAYS)).year


# A share split shows up in the filings themselves: a later 10-K restates the
# comparative years onto the new share basis, so the same period is filed
# twice with values in a split ratio (4:1, 10:1, 3:2, or 1:10 in reverse).
SPLIT_RATIOS = (1.5, 2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 40, 50, 100)
# Share counts are exact, so a restatement matches a split ratio closely. EPS
# is rounded to cents, so a 10:1 split can restate 1.74 as 0.17 (x0.098); it
# is only used for a filer that tags no plain share count (Alphabet reports
# its counts per share class).
SHARE_COUNT_TOLERANCE = 0.01
PER_SHARE_TOLERANCE = 0.05
PER_SHARE_UNITS = {"shares", "USD/shares"}


def _split_ratio(before: float, after: float, tolerance: float) -> float | None:
    """The split ratio ``after / before`` is closest to, as a multiplier on the
    share count, or None. Checked from the side above 1, so a 50:1 split is
    caught whether the figure grew x50 (a count) or shrank x1/50 (per share)."""
    if not before or not after or (before > 0) != (after > 0):
        return None
    ratio = after / before
    magnitude = max(ratio, 1 / ratio)
    split = min(SPLIT_RATIOS, key=lambda r: abs(r - magnitude))
    if abs(split - magnitude) > tolerance * split:
        return None
    return split if ratio > 1 else 1 / split


def _split_events(rows_by_series: dict[tuple[str, str], list[dict]], *, tolerance: float) -> dict[str, tuple[str, float]]:
    """{first filing on the new basis: (last filing on the old basis, ratio)}.

    Read one tag at a time: basic and diluted share counts differ by a few
    percent, and interleaving them made each alternation look like another
    split. The same split is seen in every comparative period the first
    post-split 10-K restated; those collapse to one event.
    """
    events: dict[tuple[str, float], str] = {}
    for rows in rows_by_series.values():
        ordered = sorted(rows, key=lambda r: r["filed"])
        for before, after in zip(ordered, ordered[1:]):
            ratio = _split_ratio(before["val"], after["val"], tolerance)
            if ratio is not None:
                key = (after["filed"], round(ratio, 6))
                events[key] = max(events.get(key, ""), before["filed"])
    return {first_new: (last_old, ratio) for (first_new, ratio), last_old in events.items()}


def _annual_rows(facts: dict, item: LineItem):
    """(priority, tag, end, value, filed) for every annual-period fact of an item."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    low, high = ANNUAL_SPAN_DAYS
    for priority, tag in enumerate(item.tags):
        for row in gaap.get(tag, {}).get("units", {}).get(item.unit, []):
            if row.get("form") not in ANNUAL_FORMS or row.get("fp") != "FY":
                continue
            end, value, filed = row.get("end"), row.get("val"), row.get("filed") or ""
            if end is None or value is None:
                continue
            start = row.get("start")
            if item.instant != (start is None):
                continue
            if start is not None and not low <= (pd.Timestamp(end) - pd.Timestamp(start)).days <= high:
                continue
            yield priority, tag, end, value, filed


def share_splits(facts: dict) -> list[tuple[str, float]]:
    """Splits, read from restated share counts only.

    Share counts are exact integers, so a 10:1 split restates them by exactly
    10. EPS is rounded to cents -- 1.74 restated to 0.17 is a ratio of 0.0977
    -- and reading splits from it found the same split twice.
    """
    def restatements(item: LineItem) -> dict[tuple[str, str], list[dict]]:
        seen: dict[tuple[str, str], list[dict]] = {}
        for _, tag, end, value, filed in _annual_rows(facts, item):
            seen.setdefault((tag, end), []).append({"val": value, "filed": filed})
        return seen

    events = _split_events(restatements(ITEMS_BY_KEY["shares"]), tolerance=SHARE_COUNT_TOLERANCE)
    # EPS fills in only the restating filings the share counts do not cover,
    # read in share-count terms (EPS shrinks by the ratio a count grows by).
    per_share = _split_events(restatements(ITEMS_BY_KEY["eps_diluted"]), tolerance=PER_SHARE_TOLERANCE)
    for first_new, (last_old, ratio) in per_share.items():
        events.setdefault(first_new, (last_old, 1 / ratio))
    return list(events.values())


def _annual_series(facts: dict, item: LineItem, splits: list[tuple[str, float]] = ()) -> dict[str, dict]:
    """One annual figure per fiscal period end, falling back across tags per period.

    Keyed by the period's ``end`` date, never by ``fy``: ``fy`` is the fiscal
    year of the *filing*, so a FY2025 10-K reports its FY2024 and FY2023
    comparatives under ``fy=2025`` as well. Keying on it shifted CrowdStrike's
    revenue into the wrong years and dropped one. Within one period the
    highest-priority tag wins, then the latest filing -- so a restated year
    (or a pre-split share count) shows its restated value.
    """
    picked: dict[str, dict] = {}
    for priority, tag, end, value, filed in _annual_rows(facts, item):
        current = picked.get(end)
        if current is None or priority < current["priority"] or (
            priority == current["priority"] and filed >= current["filed"]
        ):
            picked[end] = {"value": value, "filed": filed, "tag": tag, "priority": priority}

    if item.unit in PER_SHARE_UNITS:
        # A year last filed before a split is on the old share basis; put it
        # on today's, or EPS "falls 70%" the year Apple split 4:1. A share
        # count scales with the split, a per-share amount inversely.
        for entry in picked.values():
            factor = math.prod(ratio for last_old, ratio in splits if entry["filed"] <= last_old)
            if factor != 1:
                entry["value"] = entry["value"] * (factor if item.unit == "shares" else 1 / factor)
                entry["split_factor"] = factor
    return picked


def annual_statements(facts: dict) -> list[dict]:
    """Every annual period the filer has reported, oldest first, one row each.

    Columns are the period ends of flow items (a fiscal year is defined by its
    income and cash-flow statements); balance-sheet items are read at those
    same dates.
    """
    splits = share_splits(facts)
    series = {item.key: _annual_series(facts, item, splits) for item in LINE_ITEMS}

    # Rebuild the working-capital change from the balance sheet where the
    # filer did not tag it directly. A year whose prior year is missing stays
    # None: a "change" needs two observations, and defaulting it to zero would
    # quietly add a year of free cash flow.
    assets, liabilities = series["current_assets"], series["current_liabilities"]
    levels = {end: assets[end]["value"] - liabilities[end]["value"] for end in set(assets) & set(liabilities)}
    ends_with_level = sorted(levels)
    for previous, end in zip(ends_with_level, ends_with_level[1:]):
        if end in series["nwc_change"]:
            continue
        series["nwc_change"][end] = {
            "value": levels[end] - levels[previous],
            "filed": assets[end]["filed"],
            "tag": NWC_DERIVED_TAG,
            "priority": len(ITEMS_BY_KEY["nwc_change"].tags),
        }

    flow_keys = [item.key for item in LINE_ITEMS if not item.instant]
    ends = sorted({end for key in flow_keys for end in series[key]})
    rows = []
    for end in ends:
        row: dict = {"fiscal_year": fiscal_year(end), "period_end": end}
        for item in LINE_ITEMS:
            entry = series[item.key].get(end)
            row[item.key] = entry["value"] if entry else None
            row[f"{item.key}_filed"] = entry["filed"] if entry else None
        row["nwc_basis"] = (series["nwc_change"].get(end) or {}).get("tag")
        rows.append(row)
    return rows


@lru_cache(maxsize=None)
def _filer_statements(cik: int, use_cache: bool) -> tuple[str | None, tuple[int, ...], tuple[str, ...], tuple]:
    """Parsed once per build: the DCF and FINANCIALS read the same filer, and a
    company-facts document is tens of MB once parsed -- the rows are kept, the
    document is not."""
    facts, ciks = fetch_filer_facts(cik, use_cache=use_cache)
    # A period with neither revenue nor net income is not a set of statements:
    # an IFRS filer's few stray US-GAAP tags would otherwise pass as ten
    # empty fiscal years.
    rows = [row for row in annual_statements(facts) if row["revenue"] is not None or row["net_income"] is not None]
    return facts.get("entityName"), tuple(ciks), tuple(sorted(facts.get("facts", {}))), tuple(rows)


def extract_fundamentals(ticker: str, cik: int, *, years: int, use_cache: bool = True) -> dict:
    entity_name, ciks, taxonomies, rows = _filer_statements(cik, use_cache)
    if not rows:
        # A foreign filer reporting under IFRS (ASML, ARM) lands here: its
        # statements are in the ifrs-full taxonomy, which this does not read.
        reason = "reports under IFRS, which is not extracted" if "ifrs-full" in taxonomies else (
            "no annual US-GAAP statements filed yet"
        )
        raise ValueError(f"{ticker}: {reason} (taxonomies: {', '.join(taxonomies) or 'none'})")
    rows = [dict(row) for row in rows[-years:]]
    return {
        "ticker": ticker,
        "cik": cik,
        "source_ciks": list(ciks),
        "entity_name": entity_name,
        "fiscal_years": [row["fiscal_year"] for row in rows],
        "rows": rows,
        "source": "SEC XBRL company facts",
        "source_url": FACTS_URL.format(cik=cik),
    }
