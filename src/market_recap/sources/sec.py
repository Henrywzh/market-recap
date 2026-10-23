"""SEC XBRL company facts -- the free fundamentals behind the DCF tab.

data.sec.gov sends no ``Access-Control-Allow-Origin`` header, so a static page
cannot fetch it from the browser. Fundamentals are therefore extracted at build
time into a small per-ticker artifact, and the interactive model runs on that.

Each extracted figure keeps the filing's ``filed`` date, because "FY2025
revenue" is only meaningful alongside when it became public.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import math
from functools import lru_cache
import json
import os
from pathlib import Path
import pickle
import re
import threading
import time

import httpx
import pandas as pd

from .. import cache
from ..config import SEC_USER_AGENT
from . import xbrl_instance
from .http import FetchError

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
        # Notes and loans (Oracle files its long-term debt only as these; Realty
        # Income and D.R. Horton as plain notes payable).
        "LongTermNotesAndLoans", "LongTermNotesPayable", "NotesPayable",
    ), "balance"),
    LineItem("debt_current", "Current debt", (
        "DebtCurrent", "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "NotesPayableCurrent",
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
    # PaymentsOfOrdinaryDividends is the same total (common and preferred)
    # under the name many filers moved to: Bank of America, J&J, Pfizer,
    # Qualcomm and 17 more of the index report nothing else since 2014-ish.
    LineItem("dividends_paid", "Dividends paid", (
        "PaymentsOfDividends", "PaymentsOfOrdinaryDividends", "PaymentsOfDividendsCommonStock",
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


def _statement_filings(recent: dict) -> list[LatestFiling]:
    """Every statement filing with XBRL in a submissions index's recent block."""
    return [
        LatestFiling(form, accession, filed, datetime.fromisoformat(accepted.replace("Z", "+00:00")))
        for form, accession, filed, accepted, xbrl in zip(
            recent.get("form", []), recent.get("accessionNumber", []), recent.get("filingDate", []),
            recent.get("acceptanceDateTime", []), recent.get("isXBRL", []),
        )
        if form in STATEMENT_FORMS and xbrl
    ]


def _latest_statement(recent: dict) -> LatestFiling | None:
    """The newest statement filing with XBRL in a submissions index's recent block."""
    return max(_statement_filings(recent), key=lambda f: f.accepted, default=None)


def _recent_block(cik: int, *, use_cache: bool = True) -> dict:
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


def latest_statement_filing(cik: int, *, use_cache: bool = True) -> LatestFiling | None:
    """The filer's most recent 10-K/10-Q/20-F/40-F, or an amendment to one.

    Company facts are megabytes per filer and SEC answers no conditional
    request for them, so "has anything changed?" is asked of the submissions
    index instead: tens of KB, updated as each filing is accepted. Read once
    per session, like the closes.
    """
    return _latest_statement(_recent_block(cik, use_cache=use_cache))


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
    index_path = cache.path_for(f"{NAMESPACE}/submissions", f"CIK{cik:010d}", ".json" + cache.GZIP_SUFFIX)
    _checked[cik] = {"latest": latest, "refetched": refetch, "index_fetched": cache.modified(index_path)}
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
    fetched = [c["index_fetched"] for c in _checked.values() if c.get("index_fetched")]
    return {
        "checked": len(_checked),
        "failed": sum(1 for c in _checked.values() if "error" in c),
        "refetched": sum(1 for c in _checked.values() if c.get("refetched")),
        "latest_filed": max((f.filed for f in latest), default=None),
        # Company facts lacked these filers' latest filing: read from the
        # filing itself ("backfilled"), or not readable at all ("unprocessed").
        "backfilled": {f"{cik:010d}": accessions for cik, accessions in sorted(_backfilled.items())},
        "unprocessed": {f"{cik:010d}": why for cik, why in sorted(_unprocessed.items())},
        # A quiet filer can have an old 10-Q and a freshly fetched index. Use
        # the oldest actual index fetch, so stale-cache fallback stays visible.
        "index_observed_date": min(fetched).date().isoformat() if fetched else None,
    }


ARCHIVE_FOLDER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/"
INSTANCE_NAMESPACE = f"{NAMESPACE}/instance"
_NOT_AN_INSTANCE = re.compile(r"_(cal|def|lab|pre)\.xml$|FilingSummary|MetaLinks", re.I)

# Filers whose latest statement filing company facts did not carry, and what
# became of each: read from the filing's own instance, or why that failed.
_backfilled: dict[int, str] = {}
_unprocessed: dict[int, str] = {}


def _carries(facts: dict, accession: str) -> bool:
    """Whether any company-facts row came from ``accession``."""
    for taxonomy in facts.get("facts", {}).values():
        for concept in taxonomy.values():
            for rows in concept.get("units", {}).values():
                if any(row.get("accn") == accession for row in rows):
                    return True
    return False


def instance_facts(cik: int, filing: LatestFiling) -> dict:
    """Company-facts rows read from a filing's XBRL instance, kept per filing.

    A filing never changes, so the derived rows are cached on their own and the
    17 MB instance is downloaded once, not once a night.
    """
    folder = filing.accession.replace("-", "")

    def fetch() -> str:
        base = ARCHIVE_FOLDER_URL.format(cik=cik, folder=folder)
        listing = json.loads(_get(base + "index.json", 45.0))
        names = [item["name"] for item in listing.get("directory", {}).get("item", [])]
        # EDGAR extracts the inline XBRL into "<name>_htm.xml"; older filings
        # carry a plain "<name>.xml" instance.
        instance = next((n for n in names if n.endswith("_htm.xml")), None) or next(
            (n for n in names if n.endswith(".xml") and not _NOT_AN_INSTANCE.search(n)), None)
        if instance is None:
            raise LookupError(f"{filing.accession} lists no XBRL instance")
        rows = xbrl_instance.facts_from_instance(
            _get(base + instance, 180.0), accession=filing.accession, filed=filing.filed)
        return json.dumps(rows)

    text = cache.fetch_text(INSTANCE_NAMESPACE, folder, fetch, kind="filings", suffix=".json", compress=True)
    _record_read(cache.path_for(INSTANCE_NAMESPACE, folder, ".json" + cache.GZIP_SUFFIX))
    return json.loads(text)


def _newest_filed(facts: dict) -> str:
    """The latest date a statement filing (10-K, 10-Q or an amendment) is
    carried by company facts. An 8-K's cover facts do not count: Citigroup's
    September 8-K is there while both its 2026 10-Qs are not."""
    newest = ""
    for taxonomy in facts.get("facts", {}).values():
        for concept in taxonomy.values():
            for rows in concept.get("units", {}).values():
                newest = max([newest, *(row.get("filed") or "" for row in rows if row.get("form") in STATEMENT_FORMS)])
    return newest


def _backfill(cik: int, facts: dict) -> dict:
    """Add the filer's statement filings that company facts lack.

    SEC builds company facts in a second pipeline and can skip filings for
    months (Citigroup's two 2026 10-Qs). Left alone, that is a row quietly
    valued on statements two quarters old while its peers are current. Every
    statement filing newer than the newest one company facts carries is read
    from the filing itself; one accepted inside the processing margin may
    still be on its way and is left. A filing that cannot be read is reported,
    never guessed.
    """
    latest = _checked.get(cik, {}).get("latest")
    # An IFRS filer's statements are not US-GAAP and are not extracted here at
    # all (FINANCIALS lists them as such); reading its amendment would only
    # report a failure about something nobody asked for.
    if latest is None or "us-gaap" not in facts.get("facts", {}) or _carries(facts, latest.accession):
        return facts
    newest = _newest_filed(facts)
    now = datetime.now(timezone.utc)
    newer = [f for f in _statement_filings(_recent_block(cik)) if f.filed > newest and not _carries(facts, f.accession)]
    missing = sorted((f for f in newer if now - f.accepted >= PROCESSING_MARGIN), key=lambda f: f.accepted)
    for waiting in (f for f in newer if now - f.accepted < PROCESSING_MARGIN):
        # Left for now; a parsed filer kept from this build is stale once it is due.
        _record_recheck(waiting.accepted + PROCESSING_MARGIN)
    for filing in missing:
        try:
            extra = instance_facts(cik, filing)
            if not extra.get("us-gaap"):
                # An amendment often carries a cover or an exhibit and no
                # statements (Nebius's 20-F/A of 2026-05-22): nothing to add.
                # An original filing with no statements was not read right.
                if filing.form.endswith("/A"):
                    continue
                raise LookupError("instance carried no US-GAAP facts")
        except Exception as exc:
            _unprocessed[cik] = f"{filing.form} {filing.accession} filed {filing.filed}: {exc}"
            continue
        _backfilled[cik] = ", ".join(filter(None, [_backfilled.get(cik), filing.accession]))
        facts = xbrl_instance.merge_into(facts, extra)
    return facts


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
    _record_read(cache.path_for(f"{NAMESPACE}/facts", f"CIK{cik:010d}", ".json" + cache.GZIP_SUFFIX))
    return _backfill(cik, json.loads(text))


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


@lru_cache(maxsize=None)
def _ordinal(day: str) -> int:
    return date.fromisoformat(str(day)[:10]).toordinal()


def _days(earlier: str, later: str) -> int:
    # Tens of thousands of calls per filer as a decade of quarters is rebuilt
    # as then filed; a filing's dates repeat, so each is parsed once.
    return _ordinal(later) - _ordinal(earlier)


def _form_rank(key: tuple[str | None, str], form: str | None) -> int:
    """0 unless a quarterly report claims a whole year. A 10-Q has no year to
    report; Comfort Systems' 2026 Q1 10-Q tagged its Q1 2025 operating income
    as the whole of 2025, and as the later filing it replaced the 10-K's."""
    start, end = key
    if start is None or form in ANNUAL_FORMS:
        return 0
    low, high = ANNUAL_SPAN_DAYS
    return 1 if low <= _days(start, end) <= high else 0


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
            rank = (priority, _form_rank(key, row.get("form")))
            current = picked.get(key)
            if current is None or rank < current["rank"] or (rank == current["rank"] and filed >= current["filed"]):
                picked[key] = {"value": row["val"], "filed": filed, "priority": priority, "rank": rank}
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
    # Each span's length once: this runs for every quarter of every vintage of
    # every line, and three scans of the periods with a date parse each were
    # most of a filer's parse.
    lengths = [(key, _days(*key)) for key in periods if key[0] is not None]
    spans = [(key, length) for key, length in lengths if key[1] == end and length <= high]
    if not spans:
        return None
    (start, _), length = max(spans, key=lambda span: span[1])
    ytd = periods[(start, end)]
    if length >= low:
        return [(ytd, 1)]

    one_year_back = (date.fromisoformat(end[:10]) - timedelta(days=DAYS_PER_YEAR)).isoformat()
    prior = [key for key, span in lengths if abs(span - length) <= PERIOD_MATCH_DAYS]
    prior_end = _near(one_year_back, [k[1] for k in prior])
    fiscal_years = [key for key, span in lengths if low <= span <= high]
    year_end = _near(start, [k[1] for k in fiscal_years])
    if prior_end is None or year_end is None:
        return None
    prior_ytd = next(periods[k] for k in prior if k[1] == prior_end)
    last_year = next(periods[k] for k in fiscal_years if k[1] == year_end)
    return [(ytd, 1), (last_year, 1), (prior_ytd, -1)]


def _vintages(facts: dict, item: LineItem, dates) -> dict[str, dict]:
    """``_period_values(facts, item, (), filed_by=d)`` for every date in
    ``dates``, read in one pass over the filings in date order: a decade of
    quarters, each seeing only what had been filed by its own day."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    rows = []
    for priority, tag in enumerate(item.tags):
        for row in gaap.get(tag, {}).get("units", {}).get(item.unit, []):
            if row.get("form") not in QUARTERLY_FORMS or row.get("end") is None or row.get("val") is None:
                continue
            start = row.get("start")
            if item.instant != (start is None):
                continue
            key = (start, row["end"])
            rows.append((row.get("filed") or "", (priority, _form_rank(key, row.get("form"))), key, row["val"]))
    rows.sort(key=lambda r: r[0])
    out, picked, i = {}, {}, 0
    for day in sorted(set(dates)):
        while i < len(rows) and rows[i][0] <= day:
            filed, rank, key, value = rows[i]
            i += 1
            current = picked.get(key)
            if current is None or rank < current["rank"] or (rank == current["rank"] and filed >= current["filed"]):
                picked[key] = {"value": value, "filed": filed, "priority": rank[0], "rank": rank}
        out[day] = dict(picked)
    return out


def eps_history(facts: dict) -> list[dict]:
    """TTM diluted EPS for every reported quarter, as it was known when first filed.

    Each quarter's figure is built only from what had been filed by the day
    that quarter was first reported, so a valuation history read from it never
    sees a number before it was public. Its parts are returned with their own
    filing dates and on the share basis of that date; the caller puts them on
    today's basis with the split record. ``core`` carries what an operating
    P/E is built from, known on the same day.
    """
    item = ITEMS_BY_KEY["eps_diluted"]
    first_filed: dict[str, str] = {}
    for tag in item.tags:
        for row in facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(item.unit, []):
            if row.get("form") in QUARTERLY_FORMS and row.get("start") and row.get("end") and row.get("filed"):
                first_filed[row["end"]] = min(first_filed.get(row["end"], row["filed"]), row["filed"])
    days = set(first_filed.values())
    eps = _vintages(facts, item, days)
    core = {key: _vintages(facts, ITEMS_BY_KEY[key], days) for key in CORE_KEYS + ("shares",)}
    core |= {item.key: _vintages(facts, item, days) for item in CORE_EXTRA}
    book = {item.key: _vintages(facts, item, days) for item in BOOK_BALANCE}
    history = []
    for end in sorted(first_filed):
        filed = first_filed[end]
        parts = trailing_parts(eps[filed], end)
        if parts:
            history.append({
                "period_end": end,
                "filed": filed,
                "parts": [(entry["value"], entry["filed"], sign) for entry, sign in parts],
                "core": core_inputs({key: vintage[filed] for key, vintage in core.items()}, end),
                # The balance sheet at quarter end as filed that day, for tangible book per share.
                "book": {"equity": _instant_near(book["equity"][filed], end),
                         **book_at({k: book[k][filed] for k in BOOK_KEYS}, end)[0]},
            })
    return history


# What an operating P/E is built from, beside the reported EPS: the operating
# line, the interest paid on debt, pre-tax income and tax (for the company's
# own tax rate), and the gains on equity holdings a financial company's net
# income is cleaned of. Kept apart from LINE_ITEMS -- the statements tab does
# not show them as lines.
CORE_KEYS = ("ebit", "interest_expense", "pretax_income", "taxes", "net_income")
# Minority holders' share: tagged directly, or the gap between net income
# before and after it (TKO tags only the two totals).
CORE_EXTRA = (
    LineItem("equity_gains", "Gains on equity securities", ("EquitySecuritiesFvNiGainLoss",), "income"),
    LineItem("minority_share", "Net income to non-controlling interests",
             ("NetIncomeLossAttributableToNoncontrollingInterest",), "income"),
    LineItem("profit_loss", "Net income including non-controlling interests", ("ProfitLoss",), "income"),
    LineItem("parent_income", "Net income to the parent", ("NetIncomeLoss",), "income"),
)
# What tangible book and ROTCE are built from. Kept apart from LINE_ITEMS for
# the same reason as CORE_EXTRA: the statements tab and the DCF do not show them
# as lines. Read into the trailing snapshot's ``balance`` and ``ttm`` (resolved by
# ``book_at``: the raw items below are components, not what the snapshot carries).
#
# Found against real filings (probe_book_tags.py), not assumed: JPMorgan files its
# preferred stock under ...NetOfDiscount and Bank of America only in its 10-K;
# American Express, Aflac, Prudential and Apollo tag goodwill only in the 10-K;
# Raymond James and Arch tag one combined goodwill-and-intangibles line in a 10-Q;
# and Ameriprise splits intangibles into finite- and indefinite-lived lines.
BOOK_ITEMS: tuple[LineItem, ...] = (
    LineItem("goodwill", "Goodwill", ("Goodwill",), "balance"),
    LineItem("intangibles_total", "Intangible assets excluding goodwill", ("IntangibleAssetsNetExcludingGoodwill",), "balance"),
    LineItem("intangibles_finite", "Finite-lived intangible assets", ("FiniteLivedIntangibleAssetsNet",), "balance"),
    LineItem("intangibles_indefinite", "Indefinite-lived intangible assets",
             ("IndefiniteLivedIntangibleAssetsExcludingGoodwill",), "balance"),
    LineItem("goodwill_and_intangibles", "Goodwill and intangible assets", ("IntangibleAssetsNetIncludingGoodwill",), "balance"),
    # Carrying value of preferred stock, which sits inside StockholdersEquity but
    # belongs to no common holder.
    LineItem("preferred", "Preferred stock", (
        "PreferredStockValue", "PreferredStockIncludingAdditionalPaidInCapital",
        "PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount"), "balance"),
    LineItem("income_to_common", "Net income to common holders", ("NetIncomeLossAvailableToCommonStockholdersBasic",), "income"),
)
# The balance-sheet lines of tangible book, read as they stood the day each
# quarter was filed (``eps_history``'s ``book``).
BOOK_BALANCE: tuple[LineItem, ...] = (ITEMS_BY_KEY["equity"],) + tuple(i for i in BOOK_ITEMS if i.instant)
BOOK_KEYS = tuple(i.key for i in BOOK_ITEMS if i.instant)
# A balance-sheet line a 10-Q leaves out is carried from the latest earlier
# period that has it, up to this old: a 10-K's goodwill and preferred stock are
# the best figure for the next three quarters' balance sheets. Older is unknown.
CARRY_BOOK_DAYS = 400


def _instant_carried(periods: dict, end: str) -> tuple[float | None, str | None]:
    """(value, the period end it is from): the instant at ``end`` (within the
    usual tolerance), else the latest earlier one no older than CARRY_BOOK_DAYS."""
    ends = [e for (start, e) in periods if start is None]
    near = _near(end, ends)
    if near is not None:
        return periods[(None, near)]["value"], near
    earlier = [e for e in ends if e < end and _days(e, end) <= CARRY_BOOK_DAYS]
    if not earlier:
        return None, None
    last = max(earlier)
    return periods[(None, last)]["value"], last


def book_at(periods: dict[str, dict], end: str) -> tuple[dict, dict]:
    """Goodwill, intangibles, preferred stock and the combined goodwill-and-
    intangibles line as they stood at ``end``, and which of them are carried from
    an earlier period ({key: its period end}).

    Intangibles are the filer's net total, else its finite- and indefinite-lived
    lines added. A current combined line replaces goodwill and intangibles that
    would only be carried: the combined figure is this quarter's, they are not.
    """
    raw, source = {}, {}
    for key in BOOK_KEYS:
        raw[key], source[key] = _instant_carried(periods[key], end)
    fresh = {key: source[key] is not None and abs(_days(source[key], end)) <= PERIOD_MATCH_DAYS for key in BOOK_KEYS}
    parts = ("intangibles_total", "intangibles_finite", "intangibles_indefinite")
    if raw["intangibles_total"] is not None:
        intangibles, used = raw["intangibles_total"], ("intangibles_total",)
    elif raw["intangibles_finite"] is not None or raw["intangibles_indefinite"] is not None:
        used = tuple(k for k in parts[1:] if raw[k] is not None)
        intangibles = sum(raw[k] for k in used)
    else:
        intangibles, used = None, ()
    values = {"goodwill": raw["goodwill"], "intangibles": intangibles,
              "goodwill_and_intangibles": raw["goodwill_and_intangibles"], "preferred": raw["preferred"]}
    carried = {}
    if raw["goodwill_and_intangibles"] is not None and fresh["goodwill_and_intangibles"] \
            and not fresh["goodwill"] and not any(fresh[k] for k in parts):
        values["goodwill"] = values["intangibles"] = None
    else:
        if raw["goodwill"] is not None and not fresh["goodwill"]:
            carried["goodwill"] = source["goodwill"]
        if used and not all(fresh[k] for k in used):
            carried["intangibles"] = min(source[k] for k in used)
        values["goodwill_and_intangibles"] = values["goodwill_and_intangibles"] if values["goodwill"] is None and intangibles is None else None
    if raw["preferred"] is not None and not fresh["preferred"]:
        carried["preferred"] = source["preferred"]
    if values["goodwill_and_intangibles"] is not None and not fresh["goodwill_and_intangibles"]:
        carried["goodwill_and_intangibles"] = source["goodwill_and_intangibles"]
    return values, carried


# A share count is an average over a period; anything shorter is a stub.
MIN_SHARE_PERIOD_DAYS = 80


def core_inputs(periods: dict[str, dict], end: str) -> dict:
    """TTM figures ending at ``end`` from each item's periods as then filed,
    and that period's diluted share count with its own filing date (the caller
    puts it on today's share basis). A figure that cannot be built is None."""
    out = {key: trailing_value(periods[key], end)[0] for key in CORE_KEYS + tuple(i.key for i in CORE_EXTRA)}
    # The shortest period ending at ``end`` is the latest count: the quarter's,
    # or the year's in a 10-K that reports no fourth quarter.
    shares = periods["shares"]
    spans = [k for k in shares if k[0] is not None and k[1] == end and _days(k[0], end) >= MIN_SHARE_PERIOD_DAYS]
    entry = shares[min(spans, key=lambda k: _days(k[0], k[1]))] if spans else None
    out["shares"] = entry["value"] if entry else None
    out["shares_filed"] = entry["filed"] if entry else None
    return out


def _instant_near(periods: dict, end: str) -> float | None:
    match = _near(end, [e for (start, e) in periods if start is None])
    return periods[(None, match)]["value"] if match else None


DEBT_CARRYING_TAG = "DebtInstrumentCarryingAmount"
DEBT_BY_INSTRUMENT = ("SeniorNotes", "SecuredDebt", "UnsecuredDebt", "ConvertibleDebt")
# How old an earlier quarter's debt may be to stand in for this one's.
DEBT_CARRY_DAYS = 370


def trailing_snapshot(facts: dict) -> dict | None:
    """The latest reported quarter: TTM flows and balances at its end, the same a
    year earlier (for growth and averages), and a share count for market cap."""
    splits = share_splits(facts)
    read = LINE_ITEMS + BOOK_ITEMS
    periods = {item.key: _period_values(facts, item, splits) for item in read}
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
        return {item.key: flow(item.key, at, record) for item in read if not item.instant} if at else {}

    book_carried: dict[str, str] = {}

    def balances(at, record=False):
        if not at:
            return {}
        out = {item.key: _instant_near(periods[item.key], at) for item in read if item.instant and item.key not in BOOK_KEYS}
        values, carried = book_at({key: periods[key] for key in BOOK_KEYS}, at)
        if record:
            book_carried.update(carried)
        return out | values

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
        "balance": balances(end, record=True),
        # Tangible-book lines this quarter's balance sheet left out, with the
        # period end of the earlier one they are carried from.
        "balance_carried": book_carried,
        "balance_prior": balances(prior_end),
        # LongTermDebt already includes the current portion; LongTermDebtNoncurrent does not.
        "debt_includes_current": debt_tag == "LongTermDebt",
        "debt_fallback": _debt_fallback(facts, end, periods),
        "lagged": lagged,
        **_market_shares(facts, periods["shares"], end, filed),
    }


def _debt_fallback(facts: dict, end: str, periods: dict) -> dict | None:
    """Debt for a quarter whose balance sheet tags none: its lines may be under the
    filer's own tags, which SEC's company facts leave out (CoreWeave, Chevron,
    Caterpillar and T-Mobile in 2026). In order, the first that exists:
      - the debt note's total carrying amount at this quarter's end;
      - this quarter's debt by kind of instrument, summed (how REITs file it);
      - the long-term and current debt of the latest earlier quarter that tagged
        them, within a year, said to be carried from that date.
    Returns {value, basis} or None."""
    gaap = facts.get("facts", {}).get("us-gaap", {})

    def at_end(tag):
        rows = [r for r in gaap.get(tag, {}).get("units", {}).get("USD", [])
                if r.get("end") == end and "start" not in r and r.get("form") in QUARTERLY_FORMS and r.get("val") is not None]
        return float(max(rows, key=lambda r: r.get("filed") or "")["val"]) if rows else None

    if (carrying := at_end(DEBT_CARRYING_TAG)) is not None:
        return {"value": carrying, "basis": "carrying amount of debt instruments (no standard balance lines)"}
    parts = [v for v in (at_end(tag) for tag in DEBT_BY_INSTRUMENT) if v is not None]
    if parts:
        return {"value": sum(parts), "basis": "debt by instrument, summed (no standard balance lines)"}
    tagged = sorted({e for key in ("total_debt", "debt_current") for (start, e) in periods[key]
                     if start is None and e < end and _days(e, end) <= DEBT_CARRY_DAYS})
    if not tagged:
        return None
    earlier = tagged[-1]
    long_term, current = periods["total_debt"].get((None, earlier)), periods["debt_current"].get((None, earlier))
    value = (long_term or {}).get("value") or 0.0
    # LongTermDebt includes its current part; only add the current line beside a non-current one.
    if current and not (long_term and long_term["priority"] == ITEMS_BY_KEY["total_debt"].tags.index("LongTermDebt")):
        value += current["value"]
    return {"value": float(value), "basis": f"long-term + current debt carried from {earlier} (no standard balance lines this quarter)"}


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


# --- Quarterly statements -----------------------------------------------------
# The annual table's lines, one row per fiscal quarter. A quarter is the three
# months a 10-Q reports where it does; otherwise it is built from the year to
# date figures the 10-Qs and the 10-K carry.

QUARTER_SPAN_DAYS = (80, 100)
# Quarters kept on the parsed filer; the panel shows the latest of them.
QUARTERS_KEPT = 40
# Mean length of a quarter, for naming the quarter from its day count.
QUARTER_DAYS = 91.3125


def _is_quarter_span(key: tuple) -> bool:
    start, end = key
    return start is not None and QUARTER_SPAN_DAYS[0] <= _days(start, end) <= QUARTER_SPAN_DAYS[1]


class _Periods(dict):
    """A line's periods with their ends indexed. A quarterly rebuild asks for the
    periods near each of some fifty quarter ends, line by line: scanning every
    period each time was a million scans a build and most of the parse. The index
    is built on the first ask; a later insertion drops it."""

    def __setitem__(self, key, value) -> None:
        self.__dict__.pop("_index", None)
        super().__setitem__(key, value)

    def near(self, end: str) -> list[tuple]:
        """(key, entry) of every period ending within PERIOD_MATCH_DAYS of ``end``,
        in the map's own order (what a scan of ``items()`` would have found)."""
        index = self.__dict__.get("_index")
        if index is None:
            ordered = sorted(enumerate(self.items()), key=lambda item: _ordinal(item[1][0][1]))
            index = self._index = ([_ordinal(key[1]) for _, (key, _) in ordered], ordered)
        ends, ordered = index
        target = _ordinal(end)
        low, high = bisect_left(ends, target - PERIOD_MATCH_DAYS), bisect_right(ends, target + PERIOD_MATCH_DAYS)
        window = ordered[low:high]
        # One end date: the stable sort by end kept the map's order already.
        if high - low > 1 and ends[low] != ends[high - 1]:
            window = sorted(window)  # by position in the map; positions are unique
        return [item for _, item in window]


def _periods_near(periods: dict, end: str) -> list[tuple]:
    if isinstance(periods, _Periods):
        return periods.near(end)
    return [(key, entry) for key, entry in periods.items() if abs(_days(key[1], end)) <= PERIOD_MATCH_DAYS]


def _nearest_period(periods: dict, end: str, accept) -> tuple | None:
    """(key, entry) of the period ending within PERIOD_MATCH_DAYS of ``end`` that
    ``accept`` admits: the nearest end, then the latest filed."""
    found = [(key, entry) for key, entry in _periods_near(periods, end) if accept(key)]
    if not found:
        return None
    found.sort(key=lambda item: item[1]["filed"], reverse=True)
    return min(found, key=lambda item: abs(_days(item[0][1], end)))


def _quarter_ends(periods: dict) -> list[tuple[str, bool]]:
    """(end, is a fiscal year end), oldest first. Quarters come from three-month
    spans of revenue or net income; fiscal years from their annual spans. Ends
    within PERIOD_MATCH_DAYS of each other are one quarter, named by its year end."""
    quarters, years = set(), set()
    for tag in ("revenue", "net_income"):
        for (start, end), entry in periods[tag].items():
            if start is None:
                continue
            length = _days(start, end)
            if _is_quarter_span((start, end)):
                quarters.add(end)
            elif ANNUAL_SPAN_DAYS[0] <= length <= ANNUAL_SPAN_DAYS[1] and entry["rank"][1] == 0:
                years.add(end)
    clusters: list[list[str]] = []
    for end in sorted(quarters | years):
        if clusters and _days(clusters[-1][-1], end) <= PERIOD_MATCH_DAYS:
            clusters[-1].append(end)
        else:
            clusters.append([end])
    out = []
    for cluster in clusters:
        year_end = next((end for end in cluster if end in years), None)
        out.append((year_end or cluster[-1], year_end is not None))
    return out


def _fiscal_quarter(end: str, is_year_end: bool, year_ends: list[str]) -> tuple[int, int] | None:
    """(fiscal year, quarter) of a quarter end. The fiscal year is the one
    containing the quarter, named by fiscal_year(); the quarter is counted in
    months from the previous fiscal year end, or back from the next one where
    no earlier year end is known. None where neither is."""
    prior = max((y for y in year_ends if _days(y, end) > PERIOD_MATCH_DAYS), default=None)
    later = [y for y in year_ends if _days(end, y) > PERIOD_MATCH_DAYS]
    if is_year_end:
        containing = end
    elif later:
        containing = min(later)
    elif prior is not None:
        # The year in progress has no end yet: the previous one plus a year.
        containing = (date.fromisoformat(prior) + timedelta(days=DAYS_PER_YEAR)).isoformat()
    else:
        return None
    if prior is not None:
        quarter = round(_days(prior, end) / QUARTER_DAYS)
    else:
        quarter = 4 - round(_days(end, containing) / QUARTER_DAYS)
    return fiscal_year(containing), min(4, max(1, quarter))


def _eps_quarter(periods: dict, end: str, quarter_ends: list[str], year_ends: list[str]) -> tuple | None:
    """Diluted EPS for a quarter: as filed, or for the fourth quarter the year's
    EPS less the three quarters' -- and only when all three are filed. EPS is
    never differenced from year-to-date figures."""
    span = _nearest_period(periods, end, _is_quarter_span)
    if span is not None:
        return span[1]["value"], span[1]["filed"], False
    year = _nearest_period(periods, end, lambda key: key[0] is not None and ANNUAL_SPAN_DAYS[0] <= _days(*key) <= ANNUAL_SPAN_DAYS[1])
    if year is None or end not in year_ends:
        return None
    start = year[0][0]
    earlier = [q for q in quarter_ends if start < q < end and _days(q, end) > PERIOD_MATCH_DAYS]
    if len(earlier) != 3:
        return None
    parts = [_nearest_period(periods, q, _is_quarter_span) for q in earlier]
    if any(part is None for part in parts):
        return None
    return year[1]["value"] - sum(part[1]["value"] for part in parts), year[1]["filed"], True


def _flow_quarter(periods: dict, end: str) -> tuple | None:
    """A cash-flow or income figure for a quarter: the three months as filed;
    else a year-to-date span ending at ``end`` less the same-start span one quarter
    earlier (a fourth quarter is the year less nine months)."""
    span = _nearest_period(periods, end, _is_quarter_span)
    if span is not None:
        return span[1]["value"], span[1]["filed"], False
    candidates = [(key, entry) for key, entry in _periods_near(periods, end)
                  if key[0] is not None and QUARTER_SPAN_DAYS[1] < _days(*key) <= ANNUAL_SPAN_DAYS[1]]
    for (start, ytd_end), ytd in sorted(candidates, key=lambda item: item[1]["filed"], reverse=True):
        # The same tag on both sides: HIG's year is tagged ``Revenues`` and its
        # nine months a narrower line, and their difference was a $5B "quarter".
        prior = [entry for (s, e), entry in periods.items()
                 if s == start and QUARTER_SPAN_DAYS[0] <= _days(e, ytd_end) <= QUARTER_SPAN_DAYS[1]
                 and entry["priority"] == ytd["priority"]]
        if prior:
            return ytd["value"] - prior[0]["value"], ytd["filed"], True
    return None


def _quarter_figure(item: LineItem, periods: dict, end: str, quarter_ends: list[str], year_ends: list[str]) -> tuple | None:
    """(value, filed, derived) for one line at a quarter end, or None."""
    if item.instant:
        found = _nearest_period(periods, end, lambda key: key[0] is None)
        return None if found is None else (found[1]["value"], found[1]["filed"], False)
    if item.key == "eps_diluted":
        return _eps_quarter(periods, end, quarter_ends, year_ends)
    if item.key == "shares":
        # A share count is an average over a quarter; it is never built from a year.
        found = _nearest_period(periods, end, _is_quarter_span)
        return None if found is None else (found[1]["value"], found[1]["filed"], False)
    return _flow_quarter(periods, end)


def quarterly_statements(facts: dict) -> list[dict]:
    """Every fiscal quarter the filer has reported, oldest first, one row each.

    Each line carries ``{key}_filed`` (the filing its figure came from) and
    ``{key}_derived`` (True where the figure was built, not filed as a three-month
    figure: a cash-flow quarter as year-to-date less the one before, a fourth
    quarter as the year less nine months, and EPS as the year less three quarters).
    Balance-sheet items are read at the quarter end. A quarter whose fiscal year
    cannot be named, or that has neither revenue nor net income, is left out.
    """
    splits = share_splits(facts)
    periods = {item.key: _Periods(_period_values(facts, item, splits)) for item in LINE_ITEMS}
    ends = _quarter_ends(periods)
    quarter_ends = [end for end, _ in ends]
    year_ends = [end for end, is_year in ends if is_year]
    rows = []
    for end, is_year in ends:
        named = _fiscal_quarter(end, is_year, year_ends)
        if named is None:
            continue
        fiscal, quarter = named
        row: dict = {"period_end": end, "fiscal_year": fiscal, "quarter": quarter, "label": f"FY{fiscal} Q{quarter}"}
        for item in LINE_ITEMS:
            found = _quarter_figure(item, periods[item.key], end, quarter_ends, year_ends)
            value, filed, derived = found if found is not None else (None, None, False)
            row[item.key] = value
            row[f"{item.key}_filed"] = filed
            row[f"{item.key}_derived"] = derived
        if row["revenue"] is None and row["net_income"] is None:
            continue
        rows.append(row)
    _drop_stray_revenue(rows)
    return rows


# A quarter's revenue more than this many times above or below the median of the
# quarters around it is taken from another line than its neighbours (ADM's 10-Qs
# tag a $6B line some quarters and the $23B total others) and left blank.
REVENUE_STRAY_FACTOR = 3.0
REVENUE_STRAY_WINDOW = 4


def _drop_stray_revenue(rows: list[dict]) -> None:
    """Blank a quarter's revenue that is not on the scale of the quarters around
    it, or not positive. Its margins then go blank with it, never wrong."""
    values = [row["revenue"] for row in rows]
    for i, row in enumerate(rows):
        value = values[i]
        if value is None:
            continue
        around = [v for v in values[max(0, i - REVENUE_STRAY_WINDOW):i] + values[i + 1:i + 1 + REVENUE_STRAY_WINDOW]
                  if v is not None and v > 0]
        if value <= 0 or (len(around) >= 3 and not
                          sorted(around)[len(around) // 2] / REVENUE_STRAY_FACTOR <= value
                          <= sorted(around)[len(around) // 2] * REVENUE_STRAY_FACTOR):
            row["revenue"], row["revenue_derived"] = None, False


@dataclass(frozen=True)
class Filer:
    entity_name: str | None
    ciks: tuple[int, ...]
    taxonomies: tuple[str, ...]
    rows: tuple
    trailing: dict | None
    eps_history: tuple = ()
    # {end, value, filed} per fiscal quarter: the scale a release's revenue
    # guidance is checked against.
    quarterly_revenue: tuple = ()
    # The last QUARTERS_KEPT fiscal quarters, oldest first (quarterly_statements).
    quarterly_rows: tuple = ()
    # (tag, ((end, filed, value), ...)) for the debt and share series CREDIT reads
    # (compute.credit.filed_facts), kept here so it needs no second parse.
    credit_facts: tuple = ()


def filer(cik: int, use_cache: bool = True) -> Filer:
    """Parsed once per build: FINANCIALS, VALUATION, the DCF, EVIDENCE and EVENTS
    read the same filer, and a company-facts document is tens of MB once parsed
    -- what the panels need is kept, the document is not.

    The arguments are normalised before the memo: ``lru_cache`` keys
    ``filer(cik)`` and ``filer(cik, True)`` apart, so EVENTS, calling the short
    form, parsed every filer a second time (about a minute a build)."""
    return _filer(int(cik), bool(use_cache))


# --- The parsed filer, kept between builds ---------------------------------------
# Parsing ~500 company-facts documents (JSON decode, then the statements, the
# trailing figures and the EPS history) took about a minute a build, and on most
# nights none of them had changed. The parsed Filer is kept with what it was
# built from, and reused only while all of it still holds:
#   - every cached document it read (company facts, filing instances) is unchanged;
#   - the filer's latest statement filing is the same, and not due a refetch;
#   - no filing it left inside the processing margin has come due since;
#   - the code that parses it is the same (a hash of the modules involved).
# What the parse recorded about backfilled filings is kept and replayed with it.
FILER_NAMESPACE = f"{NAMESPACE}/filer"
# Per thread: a parse records only what it read itself.
_local = threading.local()


def _recorders() -> list[dict]:
    if not hasattr(_local, "recording"):
        _local.recording = []
    return _local.recording


def _record_read(path: Path) -> None:
    for recorder in _recorders():
        recorder["reads"].add(str(path))


def _record_recheck(when: datetime) -> None:
    for recorder in _recorders():
        recorder["recheck"] = when if recorder["recheck"] is None else min(recorder["recheck"], when)


@lru_cache(maxsize=1)
def _code_version() -> str:
    from ..compute import capex, credit

    digest = hashlib.sha256()
    for path in (__file__, xbrl_instance.__file__, capex.__file__, credit.__file__):
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()[:16]


def _file_stamp(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _filer_state(cik: int) -> dict:
    checked = _checked.get(cik) or {}
    latest = checked.get("latest")
    return {"latest": latest.accession if latest else None, "error": "error" in checked}


def _kept_filer(cik: int) -> dict | None:
    path = cache.path_for(FILER_NAMESPACE, f"CIK{cik:010d}", ".pkl")
    if not path.exists() or (_checked.get(cik) or {}).get("refetched"):
        return None
    try:
        entry = pickle.loads(path.read_bytes())
    except Exception:
        return None
    if entry.get("code") != _code_version() or entry.get("state") != _filer_state(cik):
        return None
    if entry.get("recheck") is not None and datetime.now(timezone.utc) >= entry["recheck"]:
        return None
    if any(_file_stamp(read) != stamp for read, stamp in entry.get("reads", {}).items()):
        return None
    return entry


def _keep_filer(cik: int, result: Filer, recorder: dict, before: tuple[dict, dict]) -> None:
    changed = lambda now, then: {k: v for k, v in now.items() if then.get(k) != v}  # noqa: E731
    entry = {
        "code": _code_version(), "state": _filer_state(cik), "recheck": recorder["recheck"],
        "reads": {read: _file_stamp(read) for read in recorder["reads"]},
        "backfilled": changed(_backfilled, before[0]), "unprocessed": changed(_unprocessed, before[1]),
        "filer": result,
    }
    path = cache.path_for(FILER_NAMESPACE, f"CIK{cik:010d}", ".pkl")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".pkl.part")
        temporary.write_bytes(pickle.dumps(entry, protocol=pickle.HIGHEST_PROTOCOL))
        temporary.replace(path)
    except OSError:
        pass  # A filer not kept is parsed again next build, never wrong.


@lru_cache(maxsize=None)
def _filer(cik: int, use_cache: bool) -> Filer:
    if use_cache and (entry := _kept_filer(cik)) is not None:
        _backfilled.update(entry["backfilled"])
        _unprocessed.update(entry["unprocessed"])
        return entry["filer"]
    recorder = {"reads": set(), "recheck": None}
    before = (dict(_backfilled), dict(_unprocessed))
    _recorders().append(recorder)
    try:
        result = _parse_filer(cik, use_cache)
    finally:
        _recorders().remove(recorder)
    if use_cache:
        _keep_filer(cik, result, recorder, before)
    return result


def _parse_filer(cik: int, use_cache: bool) -> Filer:
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
        quarterly_revenue=tuple(_quarterly_revenue(facts)) if rows else (),
        quarterly_rows=tuple(quarterly_statements(facts)[-QUARTERS_KEPT:]) if rows else (),
        credit_facts=tuple(_credit_facts(facts).items()) if rows else (),
    )


def _credit_facts(facts: dict) -> dict:
    from ..compute.credit import filed_facts

    return filed_facts(facts)


def _quarterly_revenue(facts: dict) -> list[dict]:
    """Revenue per fiscal quarter, from the revenue tag reported most recently
    (filers move between tags; the one still in use is the one that counts)."""
    from ..compute.capex import quarterly

    series = [quarterly(facts, tag) for tag in ITEMS_BY_KEY["revenue"].tags]
    best = max((found for found in series if found), key=lambda found: found[-1]["end"], default=[])
    return [{"end": q["end"], "value": q["value"], "filed": q["filed"]} for q in best]


def unextracted_reason(taxonomies) -> str:
    """Why a filer has no statements. A foreign filer reporting under IFRS
    (ASML, CCEP) lands here: its statements are in the ifrs-full taxonomy,
    which this does not read."""
    reason = "reports under IFRS, which is not extracted" if "ifrs-full" in taxonomies else (
        "no annual US-GAAP statements filed yet"
    )
    return f"{reason} (taxonomies: {', '.join(taxonomies) or 'none'})"


def extract_fundamentals(ticker: str, cik: int, *, years: int, quarters: int = 24, use_cache: bool = True) -> dict:
    data = filer(cik, use_cache)
    entity_name, ciks, rows = data.entity_name, data.ciks, data.rows
    if not rows:
        raise ValueError(f"{ticker}: {unextracted_reason(data.taxonomies)}")
    rows = [dict(row) for row in rows[-years:]]
    quarterly = [dict(row) for row in data.quarterly_rows[-quarters:]] if quarters else []
    return {
        "ticker": ticker,
        "cik": cik,
        "source_ciks": list(ciks),
        "entity_name": entity_name,
        "fiscal_years": [row["fiscal_year"] for row in rows],
        "rows": rows,
        "quarterly_rows": quarterly,
        "source": "SEC XBRL company facts",
        "source_url": FACTS_URL.format(cik=cik),
    }


ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"


def submissions_recent(cik: int, *, use_cache: bool = True) -> dict:
    """The filer's recent-filings block (form, dates, items, documents), from
    the same cached submissions index the statement check reads."""
    return _recent_block(cik, use_cache=use_cache)


INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index.html"
_ACCEPTED = re.compile(r"Accepted\s*</div>\s*<div[^>]*>\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", re.I)
_ACCEPTED_TEXT = re.compile(r"Accepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def accepted_eastern(cik: int, accession: str, *, fetch: bool = True) -> str | None:
    """The acceptance time on the filing's EDGAR index page, Eastern wall
    clock ('2026-09-30 16:02:22'). The submissions index's own stamp for a
    recent filing is unreliable: Micron's 16:02 release of 2026-09-30 read
    16:02:22Z that evening and 00:02:22Z two days later. Kept for good."""
    folder = accession.replace("-", "")
    if not fetch and not cache.is_fresh(cache.path_for(f"{NAMESPACE}/accepted", accession, ".html.gz"), "archive"):
        return None             # not read yet, and this build's budget is spent
    try:
        html = cache.fetch_text(f"{NAMESPACE}/accepted", accession,
                                lambda: _get(INDEX_URL.format(cik=cik, folder=folder, accession=accession), 30.0),
                                kind="archive", suffix=".html", compress=True)
    except Exception:  # noqa: BLE001 -- the caller falls back to the stamp
        return None
    m = _ACCEPTED.search(html) or _ACCEPTED_TEXT.search(re.sub(r"<[^>]+>", " ", html))
    return m.group(1) if m else None


OLDER_URL = "https://data.sec.gov/submissions/{name}"


def _submissions(cik: int, use_cache: bool) -> dict:
    text = cache.fetch_text(f"{NAMESPACE}/submissions", f"CIK{cik:010d}",
                            lambda: _get(SUBMISSIONS_URL.format(cik=cik), 45.0),
                            kind="daily_file", suffix=".json", use_cache=use_cache, compress=True)
    return json.loads(text)


def submissions_until(cik: int, enough, *, since: str, use_cache: bool = True) -> dict:
    """The recent block extended with older pages until ``enough(block)`` holds
    or the pages reach back past ``since``.

    SEC's recent block is the last 1,000 filings or the last year, whichever
    is more. For a bank that files thousands of structured-note prospectuses
    a year, that is four earnings releases; the rest are in dated pages. A
    page is cached under the date range it covers, so SEC renumbering its
    pages as new filings arrive never serves a page under the wrong dates.
    """
    payload = _submissions(cik, use_cache)
    block = {k: list(v) for k, v in payload.get("filings", {}).get("recent", {}).items()}
    for page in sorted(payload.get("filings", {}).get("files") or [], key=lambda f: f.get("filingTo", ""), reverse=True):
        if enough(block) or page.get("filingTo", "") < since:
            break
        name = page["name"]
        text = cache.fetch_text(f"{NAMESPACE}/submissions-older", f"CIK{cik:010d}-{page.get('filingFrom')}-{page.get('filingTo')}",
                                lambda: _get(OLDER_URL.format(name=name), 60.0),
                                kind="archive", suffix=".json", use_cache=use_cache, compress=True)
        older = json.loads(text)
        for key in block:
            block[key].extend(older.get(key) or [None] * len(older.get("form") or []))
    return block


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


# --- Every Form 4 filed on a day ----------------------------------------------
# EDGAR's daily form index lists each filing once per party: a Form 4 appears
# under the issuer's CIK and again under each reporting owner's. Filtering on
# issuer CIKs therefore finds every Form 4 about a company, whoever filed it.
DAILY_INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{quarter}/form.{day:%Y%m%d}.idx"
FILING_URL = "https://www.sec.gov/Archives/{path}"
_OWNERSHIP = re.compile(r"<ownershipDocument>.*?</ownershipDocument>", re.S)


def parse_form_index(text: str, forms: frozenset[str] = frozenset({"4"})) -> list[dict]:
    """(form, name, cik, filed, path) rows of a daily form index."""
    rows = []
    for line in text.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 5 or parts[0] not in forms or not parts[2].isdigit() or not parts[3].isdigit():
            continue
        rows.append({"form": parts[0], "name": parts[1], "cik": int(parts[2]),
                     "filed": f"{parts[3][:4]}-{parts[3][4:6]}-{parts[3][6:]}", "path": parts[4]})
    return rows


def daily_form_index(day: date, *, today: date | None = None, use_cache: bool = True) -> list[dict] | None:
    """Form 4 rows filed on ``day``; None when EDGAR has no index for it (a
    weekend, a holiday, or a day not yet published). A day more than two days
    old never changes and is kept; a recent one is refetched each session."""
    today = today or date.today()
    url = DAILY_INDEX_URL.format(year=day.year, quarter=(day.month - 1) // 3 + 1, day=day)

    def fetch() -> str:
        try:
            return _get(url, 45.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404):
                raise FetchError(f"no EDGAR daily index for {day}", not_found=True) from exc
            raise

    try:
        text = cache.fetch_text(f"{NAMESPACE}/daily-index", f"form-{day:%Y%m%d}", fetch,
                                kind="archive" if (today - day).days > 2 else "daily_file",
                                suffix=".idx", use_cache=use_cache, remember_missing=(today - day).days > 2)
    except FetchError as exc:
        if exc.not_found:
            return None
        raise
    return parse_form_index(text)


def ownership_xml(path: str) -> str | None:
    """The ownershipDocument inside one full submission (``edgar/data/...txt``)."""
    match = _OWNERSHIP.search(_get(FILING_URL.format(path=path), 30.0))
    return match.group(0) if match else None
