"""SEC XBRL company facts -- the free fundamentals behind the DCF tab.

data.sec.gov sends no ``Access-Control-Allow-Origin`` header, so a static page
cannot fetch it from the browser. Fundamentals are therefore extracted at build
time into a small per-ticker artifact, and the interactive model runs on that.

Each extracted figure keeps the filing's ``filed`` date, because "FY2025
revenue" is only meaningful alongside when it became public.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from functools import lru_cache
import json
import threading
import time

import httpx
import pandas as pd

from .. import cache
from ..config import SEC_USER_AGENT

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# Annual report forms. A foreign private issuer files 20-F or 40-F rather
# than a 10-K, and excluding them would silently drop every ADR.
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}

# SEC asks for no more than ten requests per second from one client.
_MIN_INTERVAL = 0.12
_last_call = 0.0
_throttle_lock = threading.Lock()

# Answers worth one more try: SEC's rate limiter and its edge's transient failures.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
ATTEMPTS = 3

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
        # Banks report revenue net of interest expense.
        "RevenuesNetOfInterestExpense",
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
    # Monster has tagged only the continuing-operations EPS since 2011; some
    # filers report one figure for basic and diluted.
    LineItem("eps_diluted", "Diluted EPS", (
        "EarningsPerShareDiluted",
        "IncomeLossFromContinuingOperationsPerDilutedShare",
        "EarningsPerShareBasicAndDiluted",
    ), "income", unit="USD/shares"),
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
    # Noncurrent tags first; ``LongTermDebt`` includes the current portion,
    # which the trailing snapshot records so EV does not count it twice.
    LineItem("total_debt", "Long-term debt", (
        "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt",
    ), "balance"),
    LineItem("debt_current", "Current debt", (
        "DebtCurrent", "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
    ), "balance"),
    LineItem("minority_interest", "Non-controlling interest", ("MinorityInterest",), "balance"),
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
    # Filers without a combined D&A line (Microsoft, Alphabet, Tesla) tag the
    # two parts; valuation adds them when the combined line is missing.
    LineItem("depreciation", "Depreciation", ("Depreciation",), "cash_flow"),
    LineItem("amortization", "Amortization of intangibles", ("AmortizationOfIntangibleAssets",), "cash_flow"),
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
    """Space request starts, across threads, at least _MIN_INTERVAL apart."""
    global _last_call
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _get(url: str, timeout: float) -> str:
    """SEC asks automated clients to identify themselves and to stay under ten
    requests a second; the throttle is shared across every call in the build.
    One unanswered request in five hundred is routine, so a throttled or
    dropped request is retried before it counts as a failure."""
    for attempt in range(ATTEMPTS):
        last = attempt == ATTEMPTS - 1
        _throttle()
        try:
            response = httpx.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=timeout)
        except httpx.TransportError:
            if last:
                raise
        else:
            if response.status_code not in RETRY_STATUSES or last:
                response.raise_for_status()
                return response.text
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


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


# Forms whose XBRL carries the statements read here; an amendment restates them.
STATEMENT_FORMS = frozenset(
    form + suffix for form in ANNUAL_FORMS | {"10-Q"} for suffix in ("", "/A")
)

# SEC turns a filing into company facts within minutes of accepting it, but a
# copy fetched inside those minutes predates it. A copy fetched less than this
# long after the latest filing was accepted is fetched again on the next build.
PROCESSING_MARGIN = timedelta(hours=6)


@dataclass(frozen=True)
class LatestFiling:
    form: str
    accession: str
    filed: str
    accepted: datetime


# What each filer's submissions index said this build, for the manifest.
_checked: dict[int, dict] = {}


def _latest_statement(recent: dict) -> LatestFiling | None:
    """The newest statement filing with XBRL in a submissions index's recent block."""
    filings = [
        LatestFiling(form, accession, filed, datetime.fromisoformat(accepted.replace("Z", "+00:00")))
        for form, accession, filed, accepted, xbrl in zip(
            recent.get("form", []), recent.get("accessionNumber", []), recent.get("filingDate", []),
            recent.get("acceptanceDateTime", []), recent.get("isXBRL", []),
        )
        if form in STATEMENT_FORMS and xbrl
    ]
    return max(filings, key=lambda f: f.accepted, default=None)


def latest_statement_filing(cik: int, *, use_cache: bool = True) -> LatestFiling | None:
    """The filer's most recent 10-K/10-Q/20-F/40-F, or an amendment to one.

    Company facts are megabytes per filer and SEC answers no conditional
    request for them, so "has anything changed?" is asked of the submissions
    index instead: tens of KB, updated as each filing is accepted. Read once
    per session, like the closes.
    """
    text = cache.fetch_text(
        f"{NAMESPACE}/submissions",
        f"CIK{cik:010d}",
        lambda: _get(SUBMISSIONS_URL.format(cik=cik), 45.0),
        kind="daily_file",
        suffix=".json",
        use_cache=use_cache,
        compress=True,
    )
    return _latest_statement(json.loads(text).get("filings", {}).get("recent", {}))


def predates(fetched: datetime | None, latest: LatestFiling | None) -> bool:
    """Whether company facts fetched at ``fetched`` can be missing ``latest``."""
    return fetched is not None and latest is not None and latest.accepted > fetched - PROCESSING_MARGIN


# A change the submissions index does not announce (SEC reprocessing a filing)
# is picked up by age. The age is staggered by filer so the ~500 documents
# fetched on one night do not all fall due again on one night.
BACKSTOP_DAYS = 30
BACKSTOP_STAGGER_DAYS = 7


def backstop_due(cik: int, fetched: datetime | None, now: datetime) -> bool:
    if fetched is None:
        return False
    return now - fetched > timedelta(days=BACKSTOP_DAYS + cik % BACKSTOP_STAGGER_DAYS)


def _needs_refetch(cik: int) -> bool:
    """Whether the cached company facts predate the filer's latest statements.

    Without this the facts lived out a fixed three-day lifetime, so a 10-Q
    filed on Monday reached the page on Thursday. If the index cannot be read,
    the cache's own lifetime decides, as before.
    """
    path = cache.path_for(f"{NAMESPACE}/facts", f"CIK{cik:010d}", ".json" + cache.GZIP_SUFFIX)
    try:
        latest = latest_statement_filing(cik)
    except Exception as exc:
        _checked[cik] = {"error": str(exc)}
        return False
    fetched = cache.modified(path)
    refetch = predates(fetched, latest) or backstop_due(cik, fetched, datetime.now(timezone.utc))
    _checked[cik] = {"latest": latest, "refetched": refetch}
    return refetch


# Parallel reads of the submissions indexes. One at a time, each is a round
# trip of ~0.35 s and five hundred took three minutes; the shared throttle
# still holds the whole build under SEC's ten requests a second.
CHECK_WORKERS = 6


def check_filings(ciks) -> None:
    """Ask every filer's submissions index up front, so the facts reads that
    follow already know which cached copies are out of date."""
    pending = sorted({cik for cik in ciks if cik is not None and cik not in _checked})
    with ThreadPoolExecutor(CHECK_WORKERS) as pool:
        list(pool.map(_needs_refetch, pending))


def filing_check() -> dict:
    """Summary of this build's submissions checks."""
    latest = [c["latest"] for c in _checked.values() if c.get("latest")]
    return {
        "checked": len(_checked),
        "failed": sum(1 for c in _checked.values() if "error" in c),
        "refetched": sum(1 for c in _checked.values() if c.get("refetched")),
        "latest_filed": max((f.filed for f in latest), default=None),
    }


def fetch_company_facts(cik: int, *, use_cache: bool = True) -> dict:
    # Only filers the panels asked about (check_filings) are checked: a
    # predecessor CIK files nothing new, and the candidates tried while looking
    # for one include filing agents with no index at all.
    refetch = use_cache and _checked.get(cik, {}).get("refetched", False)
    text = cache.fetch_text(
        f"{NAMESPACE}/facts",
        f"CIK{cik:010d}",
        lambda: _get(FACTS_URL.format(cik=cik), 60.0),
        kind="filings",
        suffix=".json",
        use_cache=use_cache and not refetch,
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


# --- Trailing twelve months ------------------------------------------------
# Valuation needs the latest figures, not the last 10-K: a company three
# quarters into its year has nine months of results the annual table does not
# show. TTM = last fiscal year + this year-to-date - the same span a year ago,
# all read from the 10-Qs' own comparative columns.

QUARTERLY_FORMS = ANNUAL_FORMS | {"10-Q"}
# 52/53-week calendars move a period end by a few days year to year, so a
# comparative period is matched within this tolerance rather than exactly.
PERIOD_MATCH_DAYS = 7
DAYS_PER_YEAR = 365
# A line missing from the latest 10-Q (Alphabet's Q2 2026 dividends) is taken
# from the quarter before, at most this stale, and named on the row as lagged.
MAX_LAG_DAYS = 100
# The cover-page share count is used for market cap only if it covers the
# whole company. A multi-class filer often tags one class (or none) on the
# cover; checked against the diluted count, a partial figure is caught.
COVER_COMPLETE_SHARE = 0.9
# ...and a diluted count this many times the cover count is not a missing
# class but a units error in the filing: Waters tagged 98.2 *billion* diluted
# shares against 98.2 million on its cover.
MAX_DILUTED_TO_COVER = 20
COVER_SHARES_TAG = "EntityCommonStockSharesOutstanding"


def _days(earlier: str, later: str) -> int:
    return (pd.Timestamp(later) - pd.Timestamp(earlier)).days


def _period_values(
    facts: dict, item: LineItem, splits, *, filed_by: str | None = None
) -> dict[tuple[str | None, str], dict]:
    """Latest-filed value for every (start, end) an item was reported for, in
    10-Ks and 10-Qs; the highest-priority tag wins a period. With ``filed_by``,
    only what had been filed by that date -- the figures as they were known."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    picked: dict[tuple[str | None, str], dict] = {}
    for priority, tag in enumerate(item.tags):
        for row in gaap.get(tag, {}).get("units", {}).get(item.unit, []):
            if row.get("form") not in QUARTERLY_FORMS or row.get("end") is None or row.get("val") is None:
                continue
            start = row.get("start")
            if item.instant != (start is None):
                continue
            key, filed = (start, row["end"]), row.get("filed") or ""
            if filed_by is not None and filed > filed_by:
                continue
            current = picked.get(key)
            if current is None or priority < current["priority"] or (
                priority == current["priority"] and filed >= current["filed"]
            ):
                picked[key] = {"value": row["val"], "filed": filed, "priority": priority}
    if item.unit in PER_SHARE_UNITS:
        for entry in picked.values():
            factor = math.prod(ratio for last_old, ratio in splits if entry["filed"] <= last_old)
            entry["value"] *= factor if item.unit == "shares" else 1 / factor
    return picked


def _near(target: str, candidates, tolerance: int = PERIOD_MATCH_DAYS):
    """The candidate date closest to ``target`` within the tolerance, or None."""
    best = min(candidates, key=lambda d: abs(_days(target, d)), default=None)
    return best if best is not None and abs(_days(target, best)) <= tolerance else None


def trailing_value(periods: dict, end: str) -> tuple[float | None, str | None]:
    """(TTM value ending at ``end``, filing date of its year-to-date part)."""
    parts = trailing_parts(periods, end)
    if parts is None:
        return None, None
    return sum(entry["value"] * sign for entry, sign in parts), parts[0][0]["filed"]


def trailing_parts(periods: dict, end: str) -> list[tuple[dict, int]] | None:
    """The filed figures a TTM value ending at ``end`` is made of, with signs:
    year to date first, then the last fiscal year (+) and the same span a year
    earlier (-). Kept apart so each can be put on today's share basis by its
    own filing date.

    The longest reported span ending at ``end`` is the year-to-date figure. If
    it is already a year, that is the answer; otherwise the prior fiscal year
    is added and the same year-to-date span a year earlier subtracted. A part
    that is missing makes the whole figure None -- never an annualised guess.
    """
    low, high = ANNUAL_SPAN_DAYS
    spans = [(start, e) for (start, e) in periods if start is not None and e == end and _days(start, e) <= high]
    if not spans:
        return None
    start, _ = max(spans, key=lambda k: _days(k[0], k[1]))
    ytd = periods[(start, end)]
    length = _days(start, end)
    if length >= low:
        return [(ytd, 1)]

    one_year_back = (pd.Timestamp(end) - pd.Timedelta(days=DAYS_PER_YEAR)).strftime("%Y-%m-%d")
    prior = [k for k in periods if k[0] is not None and abs(_days(k[0], k[1]) - length) <= PERIOD_MATCH_DAYS]
    prior_end = _near(one_year_back, [k[1] for k in prior])
    fiscal_years = [k for k in periods if k[0] is not None and low <= _days(k[0], k[1]) <= high]
    year_end = _near(start, [k[1] for k in fiscal_years])
    if prior_end is None or year_end is None:
        return None
    prior_ytd = next(periods[k] for k in prior if k[1] == prior_end)
    last_year = next(periods[k] for k in fiscal_years if k[1] == year_end)
    return [(ytd, 1), (last_year, 1), (prior_ytd, -1)]


def eps_history(facts: dict) -> list[dict]:
    """TTM diluted EPS for every reported quarter, as it was known when first filed.

    Each quarter's figure is built only from what had been filed by the day
    that quarter was first reported, so a valuation history read from it never
    sees a number before it was public. Its parts are returned with their own
    filing dates and on the share basis of that date; the caller puts them on
    today's basis with the split record.
    """
    item = ITEMS_BY_KEY["eps_diluted"]
    first_filed: dict[str, str] = {}
    for tag in item.tags:
        for row in facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(item.unit, []):
            if row.get("form") in QUARTERLY_FORMS and row.get("start") and row.get("end") and row.get("filed"):
                first_filed[row["end"]] = min(first_filed.get(row["end"], row["filed"]), row["filed"])
    history = []
    for end in sorted(first_filed):
        periods = _period_values(facts, item, (), filed_by=first_filed[end])
        parts = trailing_parts(periods, end)
        if parts:
            history.append({
                "period_end": end,
                "filed": first_filed[end],
                "parts": [(entry["value"], entry["filed"], sign) for entry, sign in parts],
            })
    return history


def _instant_near(periods: dict, end: str) -> float | None:
    match = _near(end, [e for (start, e) in periods if start is None])
    return periods[(None, match)]["value"] if match else None


def trailing_snapshot(facts: dict) -> dict | None:
    """The latest reported quarter: TTM flows and balances at its end, the same a
    year earlier (for growth and averages), and a share count for market cap."""
    splits = share_splits(facts)
    periods = {item.key: _period_values(facts, item, splits) for item in LINE_ITEMS}
    anchors = sorted({e for key in ("revenue", "net_income") for (start, e) in periods[key] if start is not None})
    if not anchors:
        return None
    end = anchors[-1]
    prior_end = _near((pd.Timestamp(end) - pd.Timedelta(days=DAYS_PER_YEAR)).strftime("%Y-%m-%d"), anchors)

    lagged: list[str] = []

    def flow(key, at, record):
        value, _ = trailing_value(periods[key], at)
        if value is not None:
            return value
        earlier = [e for (start, e) in periods[key] if start is not None and e < at and _days(e, at) <= MAX_LAG_DAYS]
        if not earlier:
            return None
        value, _ = trailing_value(periods[key], max(earlier))
        if value is not None and record:
            lagged.append(key)
        return value

    def flows(at, record=False):
        return {item.key: flow(item.key, at, record) for item in LINE_ITEMS if not item.instant} if at else {}

    def balances(at):
        return {item.key: _instant_near(periods[item.key], at) for item in LINE_ITEMS if item.instant} if at else {}

    filed = max((trailing_value(periods[k], end)[1] or "") for k in ("revenue", "net_income")) or None
    debt_tag = next(
        (tag for tag in ITEMS_BY_KEY["total_debt"].tags
         if any(r.get("end") == end for r in facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", []))),
        None,
    )
    return {
        "period_end": end,
        "filed": filed,
        "prior_period_end": prior_end,
        "ttm": flows(end, record=True),
        "ttm_prior": flows(prior_end),
        "balance": balances(end),
        "balance_prior": balances(prior_end),
        # LongTermDebt already includes the current portion; LongTermDebtNoncurrent does not.
        "debt_includes_current": debt_tag == "LongTermDebt",
        "lagged": lagged,
        **_market_shares(facts, periods["shares"], end, filed),
    }


def _market_shares(facts: dict, diluted: dict, end: str, filed: str | None) -> dict:
    """Shares for market cap: the latest cover-page count when it is complete,
    else the latest quarter's diluted weighted average, else none.

    ``shares_as_of`` is the date the count describes the share basis at: the
    cover's own date, or the filing date for a weighted average (statements
    are restated for any split before they are issued). A split after it is
    applied by the valuation panel.
    """
    quarter = [k for k in diluted if k[1] == end and k[0] is not None]
    diluted_count = diluted[min(quarter, key=lambda k: _days(k[0], k[1]))]["value"] if quarter else None
    cover = facts.get("facts", {}).get("dei", {}).get(COVER_SHARES_TAG, {}).get("units", {}).get("shares", [])
    latest = max(cover, key=lambda r: (r.get("filed") or "", r.get("end") or ""), default=None)
    cover_ok = bool(latest and filed and (latest.get("filed") or "") >= filed and latest.get("val"))
    if cover_ok and (diluted_count is None or latest["val"] >= COVER_COMPLETE_SHARE * diluted_count):
        return {"shares": latest["val"], "shares_as_of": latest.get("end"), "shares_basis": "cover page shares outstanding"}
    if cover_ok and diluted_count > MAX_DILUTED_TO_COVER * latest["val"]:
        return {"shares": latest["val"], "shares_as_of": latest.get("end"),
                "shares_basis": "cover page shares outstanding (the diluted count failed a units check)"}
    if diluted_count:
        return {"shares": diluted_count, "shares_as_of": filed,
                "shares_basis": "diluted weighted-average shares, latest quarter"}
    return {"shares": None, "shares_as_of": None, "shares_basis": "no complete share count filed"}


@dataclass(frozen=True)
class Filer:
    entity_name: str | None
    ciks: tuple[int, ...]
    taxonomies: tuple[str, ...]
    rows: tuple
    trailing: dict | None
    eps_history: tuple = ()


@lru_cache(maxsize=None)
def filer(cik: int, use_cache: bool = True) -> Filer:
    """Parsed once per build: FINANCIALS, VALUATION and the DCF read the same
    filer, and a company-facts document is tens of MB once parsed -- what the
    panels need is kept, the document is not."""
    facts, ciks = fetch_filer_facts(cik, use_cache=use_cache)
    # A period with neither revenue nor net income is not a set of statements:
    # an IFRS filer's few stray US-GAAP tags would otherwise pass as ten
    # empty fiscal years.
    rows = [row for row in annual_statements(facts) if row["revenue"] is not None or row["net_income"] is not None]
    return Filer(
        entity_name=facts.get("entityName"),
        ciks=tuple(ciks),
        taxonomies=tuple(sorted(facts.get("facts", {}))),
        rows=tuple(rows),
        trailing=trailing_snapshot(facts) if rows else None,
        eps_history=tuple(eps_history(facts)) if rows else (),
    )


def unextracted_reason(taxonomies) -> str:
    """Why a filer has no statements. A foreign filer reporting under IFRS
    (ASML, CCEP) lands here: its statements are in the ifrs-full taxonomy,
    which this does not read."""
    reason = "reports under IFRS, which is not extracted" if "ifrs-full" in taxonomies else (
        "no annual US-GAAP statements filed yet"
    )
    return f"{reason} (taxonomies: {', '.join(taxonomies) or 'none'})"


def extract_fundamentals(ticker: str, cik: int, *, years: int, use_cache: bool = True) -> dict:
    data = filer(cik, use_cache)
    entity_name, ciks, rows = data.entity_name, data.ciks, data.rows
    if not rows:
        raise ValueError(f"{ticker}: {unextracted_reason(data.taxonomies)}")
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


ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"


def submissions_recent(cik: int, *, use_cache: bool = True) -> dict:
    """The filer's recent-filings block (form, dates, items, documents), from
    the same cached submissions index the statement check reads."""
    text = cache.fetch_text(
        f"{NAMESPACE}/submissions",
        f"CIK{cik:010d}",
        lambda: _get(SUBMISSIONS_URL.format(cik=cik), 45.0),
        kind="daily_file",
        suffix=".json",
        use_cache=use_cache,
        compress=True,
    )
    return json.loads(text).get("filings", {}).get("recent", {})


def fetch_form4(cik: int, accession: str, primary_document: str, *, use_cache: bool = True) -> str:
    """One Form 4's raw XML. The index names the XSL-rendered view
    (``xslF345X06/doc.xml``); the raw document is the same file at the
    accession's top level. A filed document never changes, so it is kept."""
    document = primary_document.split("/")[-1]
    folder = accession.replace("-", "")
    return cache.fetch_text(
        f"{NAMESPACE}/form4",
        f"{cik}-{folder}-{document}",
        lambda: _get(ARCHIVE_URL.format(cik=cik, accession=folder, document=document), 30.0),
        kind="archive",
        suffix=".xml",
        use_cache=use_cache,
    )
