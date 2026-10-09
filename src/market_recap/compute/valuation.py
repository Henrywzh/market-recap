"""Valuation and quality metrics -- one definition each.

Inputs are the trailing snapshot (TTM flows and the latest balance sheet, read
from the company's own 10-Qs and 10-K), the annual rows FINANCIALS shows, and
the page's closing price. A metric whose input is missing, or whose
denominator is not positive, is None: a P/E on a loss or a return on negative
equity is a number without a meaning, not a very large or very small one.

EV-based multiples, gross profit, free cash flow and accruals are not computed
for the Financials sector. A bank's debt is its raw material and its operating
cash flow moves with its loan book (JPMorgan's TTM OCF is -$160bn), so those
figures would rank banks on accounting, not on value or quality.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
import math
from statistics import pstdev

import numpy as np
import pandas as pd

from ..config import TRADING_DAYS_PER_YEAR
from ..sources.sec import ANNUAL_SPAN_DAYS

FINANCIALS_SECTOR = "Financials"
# Used for NOPAT when the effective rate cannot be measured (a loss, a tax
# credit, a missing line): the US federal statutory rate since 2018.
US_STATUTORY_TAX_RATE = 0.21
# A standard deviation of five points is still a sample; fewer is not.
MIN_YEARS_FOR_STABILITY = 5
PIOTROSKI_SIGNALS = 9


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str          # x | pct | score | pp
    group: str         # valuation | quality
    better: str        # low | high
    banks: bool = True  # meaningful for the Financials sector


def _ratio(numerator, denominator, *, positive_denominator: bool = True) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    if positive_denominator and denominator < 0:
        return None
    return float(numerator) / float(denominator)


def _pct(numerator, denominator, **kwargs) -> float | None:
    value = _ratio(numerator, denominator, **kwargs)
    return None if value is None else value * 100.0


def gross_profit(flows: dict) -> float | None:
    if flows.get("gross_profit") is not None:
        return flows["gross_profit"]
    if flows.get("revenue") is None or flows.get("cost_of_revenue") is None:
        return None
    return flows["revenue"] - flows["cost_of_revenue"]


def ebit(flows: dict) -> float | None:
    """Operating income as tagged, else pre-tax income plus interest expense --
    the textbook EBIT, for filers (Exxon) that report no operating-income line."""
    if flows.get("ebit") is not None:
        return flows["ebit"]
    if flows.get("pretax_income") is None or flows.get("interest_expense") is None:
        return None
    return flows["pretax_income"] + flows["interest_expense"]


def depreciation_and_amortization(flows: dict) -> float | None:
    """The combined line, else depreciation plus intangible amortization."""
    if flows.get("dep_amort") is not None:
        return flows["dep_amort"]
    if flows.get("depreciation") is None:
        return None
    return flows["depreciation"] + (flows.get("amortization") or 0.0)


def ebitda(flows: dict) -> float | None:
    operating, da = ebit(flows), depreciation_and_amortization(flows)
    return None if operating is None or da is None else operating + da


def debt(snapshot: dict) -> tuple[float, str]:
    """Total borrowings at the snapshot, and how they were read.

    A company with no debt tags no debt line at all, so "nothing tagged" is
    taken as zero -- and said so beside the figure, because it is an
    inference, not a reported zero.
    """
    balance = snapshot["balance"]
    long_term, current = balance.get("total_debt"), balance.get("debt_current")
    if long_term is None and current is None:
        return 0.0, "no debt tagged"
    if snapshot.get("debt_includes_current"):
        return float(long_term or current or 0.0), "long-term debt incl. current portion"
    return float(long_term or 0.0) + float(current or 0.0), "long-term + current debt"


def cash_and_investments(balance: dict) -> float:
    return float(balance.get("cash") or 0.0) + float(balance.get("short_term_investments") or 0.0)


def enterprise_value(market_cap: float | None, snapshot: dict) -> float | None:
    if market_cap is None or snapshot["balance"].get("cash") is None:
        return None
    borrowings, _ = debt(snapshot)
    minority = float(snapshot["balance"].get("minority_interest") or 0.0)
    return market_cap + borrowings + minority - cash_and_investments(snapshot["balance"])


def _tax_rate(flows: dict) -> float:
    rate = _ratio(flows.get("taxes"), flows.get("pretax_income"))
    return rate if rate is not None and 0.0 <= rate <= 1.0 else US_STATUTORY_TAX_RATE


def roic(snapshot: dict) -> float | None:
    """NOPAT over invested capital (equity + debt - cash), TTM."""
    flows, balance = snapshot["ttm"], snapshot["balance"]
    operating = ebit(flows)
    if operating is None or balance.get("equity") is None:
        return None
    borrowings, _ = debt(snapshot)
    invested = balance["equity"] + borrowings - cash_and_investments(balance)
    return _pct(operating * (1 - _tax_rate(flows)), invested)


def return_on_equity(snapshot: dict) -> float | None:
    """TTM net income over average equity (ending equity if no year-ago balance)."""
    equity, prior = snapshot["balance"].get("equity"), snapshot["balance_prior"].get("equity")
    if equity is None or equity <= 0:
        return None
    average = equity if prior is None or prior <= 0 else (equity + prior) / 2
    return _pct(snapshot["ttm"].get("net_income"), average)


# --- Tangible book ------------------------------------------------------------------
def tangible_book(balance: dict) -> dict | None:
    """Common tangible book value: shareholders' equity less preferred stock,
    goodwill and other intangibles, as filed.

    A filer that tags neither goodwill, intangibles nor a combined line cannot be
    told from one that has none, so it has no tangible book here rather than a
    book passed off as tangible. A combined goodwill-and-intangibles line stands
    in when neither is tagged on its own. An untagged preferred stock is taken as
    none, as an untagged debt is (see ``debt``); ``assumed_none`` names what was
    taken as none so the row can say so. A negative component is a sign error in
    the filing, not an asset, and leaves the figure blank. Deferred tax on
    intangibles and mortgage-servicing rights are not adjusted, so a bank's own
    reported tangible book per share can differ.
    """
    equity = balance.get("equity")
    parts = {"preferred": balance.get("preferred"), "goodwill": balance.get("goodwill"), "intangibles": balance.get("intangibles")}
    combined = balance.get("goodwill_and_intangibles")
    if parts["goodwill"] is None and parts["intangibles"] is None and combined is not None:
        parts = {"preferred": parts["preferred"], "goodwill and intangibles": combined}
    elif parts["goodwill"] is None and parts["intangibles"] is None:
        return None
    if equity is None:
        return None
    if any(v is not None and v < 0 for v in parts.values()):
        return None
    return {"value": equity - sum(v or 0.0 for v in parts.values()),
            "assumed_none": sorted(k for k, v in parts.items() if v is None)}


def rotce(snapshot: dict) -> float | None:
    """TTM net income to common holders over average tangible common equity
    (the ending figure when a year ago has none). Blank unless the filing tags
    the income to common: net income would overstate a bank with preferred
    dividends."""
    now, prior = tangible_book(snapshot["balance"]), tangible_book(snapshot["balance_prior"])
    if now is None or now["value"] <= 0:
        return None
    average = now["value"] if prior is None or prior["value"] <= 0 else (now["value"] + prior["value"]) / 2
    return _pct(snapshot["ttm"].get("income_to_common"), average)


def ptbv(market_cap: float | None, balance: dict) -> float | None:
    book = tangible_book(balance)
    return None if book is None else _ratio(market_cap, book["value"])


# --- P / tangible book against its own history ---------------------------------------
# A tangible book per share more than this multiple of the price (or a price
# below it) cannot be a real figure: a units or sign error in the filing.
TBV_PRICE_LIMIT = 20.0


def tbv_steps(history: Sequence[dict], splits: pd.Series | None) -> list[tuple[str, str, float]]:
    """(filed, period end, common tangible book per share on today's share
    basis) for each quarter, from the balance sheet as filed that day.

    The per-share figure divides by the quarter's diluted count (the same one
    its operating EPS uses), scaled by the splits after its filing. That is a
    weighted average over the quarter, so it runs a little above the period-end
    count for a company that buys back stock. A quarter with no tangible book
    (or a negative one) or no usable count is left out; the figure before it
    stands until it expires, as for EPS.
    """
    splits = split_schedule(splits)
    reported = {filed: eps for filed, _, eps in eps_steps(history, splits)}
    steps = []
    for quarter in history:
        book = tangible_book(quarter.get("book") or {})
        eps = reported.get(quarter["filed"])
        if book is None or book["value"] <= 0 or eps is None:
            continue
        shares = _shares(quarter.get("core") or {}, eps, splits, quarter["filed"])
        if shares is None:
            continue
        steps.append((quarter["filed"], quarter["period_end"], book["value"] / shares))
    return steps


def plausible_tbvps(prices: pd.Series, steps: Sequence[tuple[str, str, float]]) -> pd.Series:
    """eps_in_force on the price's sessions for tangible book per share, blank
    where it cannot be a real figure."""
    book = eps_in_force(prices.index, steps)
    return book.where((book / prices) <= TBV_PRICE_LIMIT)


def ptbv_series(prices: pd.Series, steps: Sequence[tuple[str, str, float]]) -> pd.Series:
    """Daily P / tangible book: the split-adjusted close over the tangible book
    per share already public."""
    prices = prices.dropna()
    if prices.empty or not steps:
        return pd.Series(dtype=float)
    book = plausible_tbvps(prices, steps)
    return (prices / book.where(book > 0)).rename("ptbv")


def _is_prior_year(row: dict, prior: dict) -> bool:
    low, high = ANNUAL_SPAN_DAYS
    return low <= (pd.Timestamp(row["period_end"]) - pd.Timestamp(prior["period_end"])).days <= high


def piotroski(rows: Sequence[dict]) -> tuple[int | None, int]:
    """(score, signals testable) on the last two fiscal years.

    The nine binary signals of Piotroski (2000): profitability, cash quality,
    leverage, liquidity, dilution and efficiency, each "improved or not" year
    on year. The score is reported only when all nine can be tested; a 6 out
    of 7 testable signals is not a 6 out of 9.
    """
    if len(rows) < 2 or not _is_prior_year(rows[-1], rows[-2]):
        return None, 0
    now, before = rows[-1], rows[-2]

    def get(row, key):
        return row.get(key)

    def roa(row):
        return _ratio(get(row, "net_income"), get(row, "total_assets"))

    def leverage(row):
        return _ratio(get(row, "total_debt") or 0.0, get(row, "total_assets"))

    def current_ratio(row):
        return _ratio(get(row, "current_assets"), get(row, "current_liabilities"))

    def gross_margin(row):
        return _ratio(gross_profit(row), get(row, "revenue"))

    def turnover(row):
        return _ratio(get(row, "revenue"), get(row, "total_assets"))

    def improved(metric):
        a, b = metric(now), metric(before)
        return None if a is None or b is None else a > b

    def not_raised(metric):
        a, b = metric(now), metric(before)
        return None if a is None or b is None else a <= b

    signals = [
        None if roa(now) is None else roa(now) > 0,
        None if get(now, "operating_cash_flow") is None else get(now, "operating_cash_flow") > 0,
        improved(roa),
        None if get(now, "operating_cash_flow") is None or get(now, "net_income") is None
        else get(now, "operating_cash_flow") > get(now, "net_income"),
        not_raised(leverage),
        improved(current_ratio),
        not_raised(lambda row: get(row, "shares")),
        improved(gross_margin),
        improved(turnover),
    ]
    tested = [s for s in signals if s is not None]
    return (sum(tested) if len(tested) == PIOTROSKI_SIGNALS else None), len(tested)


def margin_stability(rows: Sequence[dict]) -> float | None:
    """Standard deviation of annual operating margin, in percentage points."""
    margins = [_pct(r.get("ebit"), r.get("revenue")) for r in rows]
    margins = [m for m in margins if m is not None]
    return pstdev(margins) if len(margins) >= MIN_YEARS_FOR_STABILITY else None


@dataclass(frozen=True)
class Inputs:
    snapshot: dict
    rows: Sequence[dict]
    market_cap: float | None
    ev: float | None


def _yield(numerator, market_cap):
    return _pct(numerator, market_cap)


METRICS: tuple[tuple[Metric, Callable[[Inputs], float | None]], ...] = (
    (Metric("pe", "P/E (TTM)", "x", "valuation", "low"),
     lambda i: _ratio(i.market_cap, i.snapshot["ttm"].get("net_income"))),
    (Metric("ev_ebitda", "EV / EBITDA", "x", "valuation", "low", banks=False),
     lambda i: _ratio(i.ev, ebitda(i.snapshot["ttm"]))),
    (Metric("ev_sales", "EV / Sales", "x", "valuation", "low", banks=False),
     lambda i: _ratio(i.ev, i.snapshot["ttm"].get("revenue"))),
    (Metric("pb", "P / Book", "x", "valuation", "low"),
     lambda i: _ratio(i.market_cap, i.snapshot["balance"].get("equity"))),
    (Metric("ptbv", "P / Tangible book", "x", "valuation", "low"),
     lambda i: ptbv(i.market_cap, i.snapshot["balance"])),
    (Metric("fcf_yield", "FCF yield", "pct", "valuation", "high", banks=False),
     lambda i: None if i.snapshot["ttm"].get("operating_cash_flow") is None or i.snapshot["ttm"].get("capex") is None
     else _yield(i.snapshot["ttm"]["operating_cash_flow"] - i.snapshot["ttm"]["capex"], i.market_cap)),
    (Metric("dividend_yield", "Dividend yield", "pct", "valuation", "high"),
     lambda i: _yield(i.snapshot["ttm"].get("dividends_paid"), i.market_cap)),
    (Metric("shareholder_yield", "Shareholder yield (div + buyback)", "pct", "valuation", "high"),
     lambda i: None if i.snapshot["ttm"].get("dividends_paid") is None and i.snapshot["ttm"].get("buybacks") is None
     else _yield((i.snapshot["ttm"].get("dividends_paid") or 0) + (i.snapshot["ttm"].get("buybacks") or 0), i.market_cap)),
    (Metric("roe", "ROE (TTM, avg equity)", "pct", "quality", "high"), lambda i: return_on_equity(i.snapshot)),
    (Metric("rotce", "ROTCE (TTM, avg tangible common equity)", "pct", "quality", "high"), lambda i: rotce(i.snapshot)),
    (Metric("roic", "ROIC (TTM)", "pct", "quality", "high", banks=False), lambda i: roic(i.snapshot)),
    (Metric("gross_profitability", "Gross profit / assets", "pct", "quality", "high", banks=False),
     lambda i: _pct(gross_profit(i.snapshot["ttm"]), i.snapshot["balance"].get("total_assets"))),
    (Metric("operating_margin", "Operating margin (TTM)", "pct", "quality", "high", banks=False),
     lambda i: _pct(ebit(i.snapshot["ttm"]), i.snapshot["ttm"].get("revenue"))),
    (Metric("revenue_growth", "Revenue growth (TTM y/y)", "pct", "quality", "high"),
     lambda i: None if _ratio(i.snapshot["ttm"].get("revenue"), i.snapshot["ttm_prior"].get("revenue")) is None
     else (_ratio(i.snapshot["ttm"]["revenue"], i.snapshot["ttm_prior"]["revenue"]) - 1) * 100),
    (Metric("accruals", "Accruals (NI - OCF) / assets", "pct", "quality", "low", banks=False),
     lambda i: None if i.snapshot["ttm"].get("net_income") is None or i.snapshot["ttm"].get("operating_cash_flow") is None
     else _pct(i.snapshot["ttm"]["net_income"] - i.snapshot["ttm"]["operating_cash_flow"], i.snapshot["balance"].get("total_assets"))),
    (Metric("net_debt_ebitda", "Net debt / EBITDA", "x", "quality", "low", banks=False),
     lambda i: _ratio(debt(i.snapshot)[0] - cash_and_investments(i.snapshot["balance"]), ebitda(i.snapshot["ttm"]))),
    (Metric("interest_coverage", "Interest coverage (EBIT / interest)", "x", "quality", "high", banks=False),
     lambda i: _ratio(ebit(i.snapshot["ttm"]), i.snapshot["ttm"].get("interest_expense"))),
    (Metric("piotroski", "Piotroski F-score", "score", "quality", "high"), lambda i: piotroski(i.rows)[0]),
    (Metric("margin_stability", "Op. margin σ, annual", "pp", "quality", "low", banks=False),
     lambda i: margin_stability(i.rows)),
)


def compute(inputs: Inputs, *, sector: str | None) -> dict[str, float | None]:
    bank = sector == FINANCIALS_SECTOR
    return {metric.key: (None if bank and not metric.banks else fn(inputs)) for metric, fn in METRICS}


# --- P/E against its own history ---------------------------------------------
# The window a current multiple is compared with, and the least history that
# makes a percentile describe a range rather than one market regime.
HISTORY_SESSIONS = 10 * TRADING_DAYS_PER_YEAR
MIN_HISTORY_SESSIONS = 2 * TRADING_DAYS_PER_YEAR
HISTORY_QUANTILES = {"p10": 0.10, "p25": 0.25, "median": 0.50, "p75": 0.75, "p90": 0.90}
# An EPS figure stands until the next one is filed -- but not forever. A filer
# that stopped tagging EPS (Monster, in 2011) would otherwise have its 2011
# earnings divided into every price since; two quarters without a successor
# and the multiple goes blank instead.
EPS_STALE_AFTER_DAYS = 190
# A TTM EPS more than this multiple of the share price, either way, is a units
# error in the filing's facts, not a result: Halliburton's 2021-25 figures
# came through in the millions of dollars. A real loss that deep is rare
# enough (APA's 2020 was about 1.3x its price) that the bound costs nothing.
EPS_PRICE_LIMIT = 2.0


class SplitSchedule:
    """A symbol's splits, kept as the few events they are.

    ``split_factor_after`` was asked about every filed part of every quarter of
    every company -- 520,000 times a build -- and each time dropped the NaNs from
    the whole price-length series and masked it, which was most of VALUATION's
    time. The splits are a handful of dated ratios: build this once per symbol,
    and each question scans only those.
    """

    def __init__(self, splits: pd.Series | None):
        ratios = splits.dropna() if splits is not None else pd.Series(dtype=float)
        self._days = list(ratios.index)
        self._ratios = [float(r) for r in ratios]

    def factor_after(self, date: str) -> float:
        cutoff = _timestamp(date)
        # np.prod of the same ratios in the same order: what Series.prod() did.
        return float(np.prod([r for d, r in zip(self._days, self._ratios) if d > cutoff]))


@lru_cache(maxsize=None)
def _timestamp(date: str) -> pd.Timestamp:
    return pd.Timestamp(date)


def split_schedule(splits: "pd.Series | SplitSchedule | None") -> "SplitSchedule | None":
    """The schedule for a splits series (itself if it already is one)."""
    if splits is None or isinstance(splits, SplitSchedule):
        return splits
    return SplitSchedule(splits)


def split_factor_after(splits: "pd.Series | SplitSchedule | None", date: str) -> float:
    """Product of the splits after ``date``: what a figure filed that day must be
    scaled by to be on today's share basis. Pass a ``SplitSchedule`` when asking
    more than once about the same symbol."""
    schedule = split_schedule(splits)
    return 1.0 if schedule is None else schedule.factor_after(date)


def eps_steps(history: Sequence[dict], splits: pd.Series | None) -> list[tuple[str, str, float]]:
    """(filed, period end, TTM EPS on today's share basis) for each quarter.

    Every part is scaled by the splits after *its own* filing date: a filing
    reports every figure on the share basis of the day it was issued, so a
    part filed before a split and one filed after it are on different bases
    until each is scaled separately.
    """
    steps = []
    splits = split_schedule(splits)
    for quarter in history:
        eps = sum(sign * value / split_factor_after(splits, filed) for value, filed, sign in quarter["parts"])
        steps.append((quarter["filed"], quarter["period_end"], eps))
    return steps


# --- Operating EPS ---------------------------------------------------------------
# Reported EPS counts whatever sits below the operating line. Alphabet's
# 2026 Q2 carried $99bn of gains on its equity stakes against $41bn of
# operating income, and Amazon's $53bn: marked up, both looked their cheapest
# in ten years. An operating P/E takes those gains out:
#
#   pre-tax income, but no more than operating income less interest paid,
#   taxed at the company's own rate
#
# Only a net gain below the operating line is removed. A net loss stays: a
# filer's "operating income" does not always carry all of its costs (Disney
# tags its segment total, before corporate costs and amortisation), and
# removing losses would make such a company look cheaper than its own
# statements say. Interest paid stays in either way. Discontinued operations
# go with the rest, since they are below pre-tax income from continuing ones.
# The tax rate is the median of the company's trailing-twelve-month rates at
# its last TAX_RATE_QUARTERS quarter ends, each as then filed, so one quarter's
# tax charge (Meta's $16bn in 2025 Q3) does not move it.
TAX_RATE_QUARTERS = 12
TAX_RATE_BOUNDS = (0.0, 0.35)
# A company with no positive pre-tax year in the window: the federal rate.
DEFAULT_TAX_RATE = 0.21
# A filed diluted count this far from the one the filing's own net income and
# EPS imply is a units error (Waters tagged 98.2 billion shares for 98.2
# million); the implied count is used instead.
SHARE_UNITS_FACTOR = 20
# The bases a P/E history can be on. OPERATING as above. EX_GAINS: the
# reported EPS less gains (or losses) on equity securities after tax -- for
# financials and utilities, whose ordinary earnings are partly below the
# operating line (interest is a bank's business; AFUDC a utility's), and for
# companies that tag no operating line (Merck, J&J, Deere).
OPERATING, EX_GAINS, REPORTED = "operating", "ex_gains", "reported"
BASIS_LABELS = {
    OPERATING: "pre-tax income capped at operating income less interest, taxed at the company's own rate",
    EX_GAINS: "reported EPS less gains on equity securities, after tax",
    REPORTED: "reported diluted EPS",
}
BELOW_THE_LINE_SECTORS = frozenset({FINANCIALS_SECTOR, "Utilities"})


def tax_rates(history: Sequence[dict]) -> list[float]:
    """Each quarter's normalised tax rate, from what was filed by then."""
    ratios: list[float] = []
    out = []
    low, high = TAX_RATE_BOUNDS
    for quarter in history:
        core = quarter.get("core") or {}
        tax, pretax = core.get("taxes"), core.get("pretax_income")
        ratios.append(tax / pretax if tax is not None and pretax is not None and pretax > 0 else math.nan)
        window = [r for r in ratios[-TAX_RATE_QUARTERS:] if not math.isnan(r)]
        rate = float(np.median(window)) if window else DEFAULT_TAX_RATE
        out.append(min(max(rate, low), high))
    return out


def _shares(core: dict, eps: float, splits: pd.Series | None, filed: str) -> float | None:
    """The quarter's diluted count on today's share basis, checked against the
    count its own net income and EPS imply."""
    implied = core["net_income"] / eps if core.get("net_income") and eps else None
    shares = core.get("shares")
    if shares:
        shares *= split_factor_after(splits, core.get("shares_filed") or filed)
        if implied and implied > 0 and not 1 / SHARE_UNITS_FACTOR <= shares / implied <= SHARE_UNITS_FACTOR:
            shares = implied
    else:
        shares = implied
    return shares if shares and shares > 0 else None


def minority_share(core: dict) -> float:
    """What of a year's net income belongs to minority holders (Freeport's
    Indonesian partners, TKO's Endeavor units): the per-share figure is the
    parent's."""
    if core.get("minority_share") is not None:
        return core["minority_share"]
    if core.get("profit_loss") is not None and core.get("parent_income") is not None:
        return core["profit_loss"] - core["parent_income"]
    return 0.0


def operating_basis(history: Sequence[dict], sector: str | None) -> str:
    """OPERATING when the latest quarter has an operating line to build from;
    one basis for the whole history, so a company's decade is one measure."""
    latest = (history[-1].get("core") or {}) if history else {}
    return EX_GAINS if sector in BELOW_THE_LINE_SECTORS or latest.get("ebit") is None else OPERATING


def operating_steps(history: Sequence[dict], splits: pd.Series | None, basis: str) -> list[dict]:
    """Operating TTM EPS on today's share basis per quarter, with what went
    into it: {filed, period_end, eps, reported, removed, tax_rate}.

    A quarter whose inputs were not filed is left out; the figure before it
    stands, as for a reported EPS, until it expires.
    """
    splits = split_schedule(splits)
    reported = {filed: eps for filed, _, eps in eps_steps(history, splits)}
    out = []
    for quarter, rate in zip(history, tax_rates(history)):
        core = quarter.get("core") or {}
        filed, eps = quarter["filed"], reported.get(quarter["filed"])
        if eps is None:
            continue
        shares = _shares(core, eps, splits, filed)
        if shares is None:
            continue
        if basis == OPERATING:
            if core.get("ebit") is None:
                continue
            # Some filers sign interest expense negative (Disney); some tag
            # none (Charter), where the pre-tax cap keeps it in.
            pretax = core["ebit"] - abs(core.get("interest_expense") or 0.0)
            if core.get("pretax_income") is not None:
                pretax = min(pretax, core["pretax_income"])
            value = (pretax * (1 - rate) - minority_share(core)) / shares
        else:
            value = eps - (core.get("equity_gains") or 0.0) * (1 - rate) / shares
        out.append({"filed": filed, "period_end": quarter["period_end"], "eps": value,
                    "reported": eps, "removed": eps - value, "tax_rate": rate})
    return out


def as_steps(steps: Sequence[dict]) -> list[tuple[str, str, float]]:
    return [(s["filed"], s["period_end"], s["eps"]) for s in steps]


def eps_in_force(sessions: pd.DatetimeIndex, steps: Sequence[tuple[str, str, float]]) -> pd.Series:
    """The TTM EPS already public on each session, losses included.

    A quarter's EPS applies from the session after its filing date -- a filing
    can land after the close. Before the first filing, and once a figure has
    stood EPS_STALE_AFTER_DAYS without a successor, it is unknown.
    """
    if not len(sessions) or not steps:
        return pd.Series(np.nan, index=sessions, dtype=float)
    known = pd.Series(
        {pd.Timestamp(filed) + pd.Timedelta(days=1): eps for filed, _, eps in sorted(steps)}
    ).groupby(level=0).last()
    # The figure in force each session, and how long it has been in force.
    position = known.index.searchsorted(sessions, side="right") - 1
    in_force = position >= 0
    eps = pd.Series(np.where(in_force, known.to_numpy()[position.clip(0)], np.nan), index=sessions)
    age = (sessions - known.index[position.clip(0)]).days
    eps[~in_force | (age > EPS_STALE_AFTER_DAYS)] = np.nan
    return eps


def plausible_eps(prices: pd.Series, steps: Sequence[tuple[str, str, float]]) -> pd.Series:
    """eps_in_force on the price's sessions, blank where it cannot be a real figure."""
    eps = eps_in_force(prices.index, steps)
    return eps.where((eps / prices).abs() <= EPS_PRICE_LIMIT)


def pe_series(prices: pd.Series, steps: Sequence[tuple[str, str, float]]) -> pd.Series:
    """Daily P/E: the split-adjusted close over the TTM EPS already public.
    A loss leaves the multiple blank."""
    prices = prices.dropna()
    if prices.empty or not steps:
        return pd.Series(dtype=float)
    eps = plausible_eps(prices, steps)
    return (prices / eps.where(eps > 0)).rename("pe")


def pe_stats(pe: pd.Series) -> dict | None:
    """Where the latest P/E sits in its own last ten years."""
    window = pe.iloc[-HISTORY_SESSIONS:]
    valid = window.dropna()
    if len(valid) < MIN_HISTORY_SESSIONS:
        return None
    current = pe.iloc[-1]
    stats = {name: float(valid.quantile(q)) for name, q in HISTORY_QUANTILES.items()}
    stats |= {
        "current": None if pd.isna(current) else float(current),
        "min": float(valid.min()),
        "max": float(valid.max()),
        "sessions": int(len(valid)),
        "first": valid.index[0].strftime("%Y-%m-%d"),
    }
    stats["percentile"] = None if pd.isna(current) else float((valid <= current).mean() * 100)
    stats["vs_median"] = None if pd.isna(current) else (float(current) / stats["median"] - 1) * 100
    return stats


# --- Index and sector P/E -------------------------------------------------------
# A session's aggregate is drawn only when the companies with an EPS in force
# hold at least this share of the group's priced market cap; below it the
# multiple describes whichever companies happened to have filed.
AGGREGATE_MIN_COVERAGE = 0.8


def aggregate_pe(caps: pd.DataFrame, earnings: pd.DataFrame) -> pd.DataFrame:
    """Total market cap over total TTM earnings, per session (dates x companies in).

    Losses count, as in an index's own P/E, so a group whose earnings sum to
    zero or less has no multiple. ``coverage`` is the share of the group's
    priced market cap that has an EPS in force.
    """
    both = caps.notna() & earnings.notna()
    total_cap = caps.where(both).sum(axis=1, min_count=1)
    total_earnings = earnings.where(both).sum(axis=1, min_count=1)
    coverage = total_cap / caps.sum(axis=1, min_count=1)
    pe = total_cap / total_earnings.where(total_earnings > 0)
    pe = pe.where(coverage >= AGGREGATE_MIN_COVERAGE)
    return pd.DataFrame({"pe": pe, "coverage": coverage})


# --- Forward P/E ------------------------------------------------------------------
# Price over the next twelve months' consensus EPS: this fiscal year's and next
# year's estimates, weighted by how much of each the coming twelve months
# covers (the convention FactSet's index figure uses). A fiscal year that has
# ended but not been reported weighs nothing. Yahoo's estimates are on the
# analysts' basis -- adjusted EPS for most companies -- so a forward multiple
# is not the same measure as a trailing one on reported earnings.
DAYS_PER_YEAR_F = 365.25


def ntm_eps(trend: dict | None, today) -> dict | None:
    """{eps, weight_this_year, this_year_end} or None without both years."""
    if not trend:
        return None
    this, nxt = trend.get("0y") or {}, trend.get("+1y") or {}
    if this.get("eps") is None or nxt.get("eps") is None or not this.get("end"):
        return None
    left = (pd.Timestamp(this["end"]) - pd.Timestamp(today)).days
    weight = min(max(left / DAYS_PER_YEAR_F, 0.0), 1.0)
    return {"eps": weight * this["eps"] + (1 - weight) * nxt["eps"], "weight_this_year": round(weight, 3),
            "this_year_end": this["end"]}


def forward_pe(price: float | None, ntm: dict | None) -> float | None:
    """A forward multiple, blank on a forecast loss."""
    if price is None or not ntm or ntm["eps"] <= 0:
        return None
    return price / ntm["eps"]


# --- Yahoo's fiscal-year forward P/E history --------------------------------------
# What Yahoo itself published at each month end: price over the consensus EPS of
# a *fiscal year*, as of that day (sources.forward_pe_history). It is not the
# next-twelve-months multiple above, and the two are never drawn as one line.
# Yahoo moves the EPS on to the next fiscal year this many months before the
# year ends -- seen as a step in the EPS the multiple implies (close / P/E) at
# that month for Goldman and JPMorgan (December years), Microsoft (June), Oracle
# (May), Costco (August) and Apple (September); not published by Yahoo, so a
# rule read off the data and checked against it by the tests.
FY_ROLL_MONTHS = 3
# Above this a forward multiple is reported as extreme. Some are real (a company
# priced for years of growth) and some are a near-zero EPS (Boeing's 3,333x, Warner
# Bros. Discovery's 5,000x); the multiple alone cannot tell them apart, so none is
# removed -- as with the P/E history, the table keeps the true range and the chart's
# axis stops short of a spike.
EXTREME_FORWARD_PE = 100.0


def _month_index(date: str) -> int:
    stamp = pd.Timestamp(date)
    return stamp.year * 12 + stamp.month - 1


def fiscal_year_end_month(annual: Sequence[dict]) -> int | None:
    """The month a company's fiscal year ends: the month of its annual points.

    The annual series is dated at each fiscal year end, so the most common
    month is the answer; a 52-week year that wanders across a month boundary
    still has one most common month. None without annual points.
    """
    months = [pd.Timestamp(p["date"]).month for p in annual]
    if not months:
        return None
    counts = {m: months.count(m) for m in set(months)}
    return max(counts, key=lambda m: (counts[m], m))


def forward_horizon_months(date: str, year_end_month: int) -> int:
    """Months from ``date`` to the end of the fiscal year Yahoo's EPS is for.

    Until FY_ROLL_MONTHS before the year ends it is the current year, so the
    horizon shrinks from 11 months to 4; from then on it is the next year, 15
    months at the roll and 12 at the year end itself. Always 4 to 15, which is
    why successive months are not on one footing.
    """
    left = (year_end_month - pd.Timestamp(date).month) % 12
    return left + 12 if left <= FY_ROLL_MONTHS else left


def is_roll_month(date: str, year_end_month: int) -> bool:
    """True at the month the EPS behind the multiple moves to the next fiscal year."""
    return (year_end_month - pd.Timestamp(date).month) % 12 == FY_ROLL_MONTHS


def merge_points(*series: Sequence[dict]) -> list[dict]:
    """One list of points by date, the first series winning where two overlap.

    Where the monthly and quarterly series share a date they carry the same
    value (all 2,412 shared points across the S&P 500 universe did); the
    quarterly series adds the fiscal quarter ends the monthly one lacks."""
    by_date: dict[str, dict] = {}
    for name, points in zip(("monthly", "quarterly"), series):
        for point in points:
            by_date.setdefault(point["date"], {"date": point["date"], "pe": point["pe"], "series": name})
    return [by_date[d] for d in sorted(by_date)]


def missing_months(dates: Sequence[str]) -> list[str]:
    """Calendar months between the first and last date that no point covers."""
    if len(dates) < 2:
        return []
    have = {_month_index(d) for d in dates}
    first, last = min(have), max(have)
    return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(first, last + 1) if i not in have]


def fiscal_forward(found: dict | None) -> dict | None:
    """One company's Yahoo history, ready to draw; None when it has no points.

    ``points`` are the monthly and quarterly points merged, each with the
    ``horizon`` of its EPS in months and ``rolled`` at the month the EPS moved
    to the next fiscal year. ``year_ago`` compares the latest point with the
    same month a year earlier -- the one comparison that holds the horizon
    fixed -- and ``annual`` is the fiscal year ends, each exactly twelve months
    ahead, so comparable across companies and years. Values are as Yahoo
    published them.
    """
    if not found:
        return None
    annual = found.get("annual") or []
    year_end = fiscal_year_end_month(annual)
    merged = merge_points(found.get("monthly") or [], found.get("quarterly") or [])
    if not merged and not annual:
        return None

    points = [{"date": p["date"], "series": p["series"], "pe": p["pe"],
               "horizon": None if year_end is None else forward_horizon_months(p["date"], year_end),
               "rolled": year_end is not None and is_roll_month(p["date"], year_end)} for p in merged]
    latest = points[-1] if points else None
    year_ago = None
    if latest:
        earlier = next((p for p in points if _month_index(p["date"]) == _month_index(latest["date"]) - 12), None)
        if earlier:
            change = None
            if latest["pe"] is not None and earlier["pe"] is not None:
                change = (latest["pe"] / earlier["pe"] - 1) * 100
            year_ago = {"date": earlier["date"], "pe": earlier["pe"], "change_pct": change}
    return {
        "year_end_month": year_end,
        "points": points,
        "annual": [{"date": p["date"], "pe": p["pe"]} for p in annual],
        "latest": latest,
        "year_ago": year_ago,
        "missing_months": missing_months([p["date"] for p in points]),
        "unread": found.get("unread") or [],
    }


# --- Sub-sector groups ------------------------------------------------------------
def assign_subgroups(rows: list[dict], specs: list[dict], min_members: int) -> dict:
    """Split sectors into the groups the config names, by GICS sub-industry.

    ``rows`` carry ``ticker``, ``sector`` and ``sub_sector``; each spec has a
    ``key``, a ``label``, the ``sector`` it divides and the ``sub_industries``
    it takes. The config is the only place a sub-industry is assigned, so what
    the split cannot place is reported instead of guessed:

    - ``unmatched``: a configured sub-industry no row carries (a renamed GICS
      label would otherwise empty a group without a word);
    - ``too_small``: a group with some companies, but fewer than ``min_members``;
    - ``unassigned``: sub-industries of a divided sector that no group claims.

    A sub-industry named by two groups is a config error and raises.
    """
    claimed: dict[tuple[str, str], str] = {}
    for spec in specs:
        for name in spec["sub_industries"]:
            other = claimed.setdefault((spec["sector"], name), spec["key"])
            if other != spec["key"]:
                raise ValueError(f"sub-industry {name!r} of {spec['sector']} is in both {other!r} and {spec['key']!r}")
    present: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        present.setdefault((row["sector"], row["sub_sector"]), []).append(row["ticker"])
    groups, unmatched, too_small = [], [], []
    for spec in specs:
        tickers = sorted(t for name in spec["sub_industries"] for t in present.get((spec["sector"], name), []))
        unmatched += [f"{spec['sector']}: {name}" for name in spec["sub_industries"] if (spec["sector"], name) not in present]
        if not tickers:
            continue                                                  # ``unmatched`` already says why
        if len(tickers) < min_members:
            too_small.append({"key": spec["key"], "label": spec["label"], "companies": len(tickers)})
            continue
        groups.append({"key": spec["key"], "label": spec["label"], "parent": spec["sector"], "tickers": tickers})
    divided = {spec["sector"] for spec in specs}
    unassigned = [{"sector": sector, "sub_industry": str(name), "tickers": sorted(tickers)}
                  for (sector, name), tickers in sorted(present.items(), key=lambda kv: (kv[0][0], str(kv[0][1])))
                  if sector in divided and (sector, name) not in claimed]
    return {"groups": groups, "unmatched": unmatched, "too_small": too_small, "unassigned": unassigned}


def aggregate_book(members: list[dict]) -> dict | None:
    """A group's P / tangible book and ROTCE as totals: market cap over total
    tangible book, and total income to common over total average tangible
    book. Each counts only the members that have both of its inputs, and is
    drawn when they hold ``AGGREGATE_MIN_COVERAGE`` of the group's market cap.
    A member with no positive tangible book (most software companies) is out,
    so a non-financial group usually has no figure at all."""
    total = sum(r["market_cap"] for r in members if r.get("market_cap"))
    if not total:
        return None

    def share(rows):
        return sum(r["market_cap"] for r in rows) / total

    with_book = [r for r in members if r.get("market_cap") and (r.get("tbv") or 0) > 0]
    with_return = [r for r in with_book if r.get("tbv_avg") and r.get("income_common") is not None]
    out = {}
    if with_book and share(with_book) >= AGGREGATE_MIN_COVERAGE:
        out["ptbv"] = sum(r["market_cap"] for r in with_book) / sum(r["tbv"] for r in with_book)
        out["ptbv_coverage"] = share(with_book)
    if with_return and share(with_return) >= AGGREGATE_MIN_COVERAGE:
        out["rotce"] = sum(r["income_common"] for r in with_return) / sum(r["tbv_avg"] for r in with_return) * 100
        out["rotce_coverage"] = share(with_return)
    return out or None


# --- Valuation path ---------------------------------------------------------------
# One group's multiple at four points on the same analyst-consensus basis: the
# fiscal year just reported (Yahoo's ``yearAgoEps``, the actual), this fiscal
# year, the next twelve months, and next fiscal year. Every stage is Yahoo's,
# so the steps between them are growth, not a change of accounting (a trailing
# filed-EPS multiple would differ by definition). A "fiscal year" is each
# company's own, so a sector mixes year-ends.
PATH_STAGES = ("fy_prev", "fy0", "ntm", "fy1")


def fiscal_path(trend: dict | None, ntm: dict | None) -> dict | None:
    """Per-share EPS at each stage, or None without this year's and next year's
    consensus. The last fiscal year's actual may be missing; the rest stand."""
    if not trend or not ntm:
        return None
    this, nxt = trend.get("0y") or {}, trend.get("+1y") or {}
    if this.get("eps") is None or nxt.get("eps") is None:
        return None
    return {"fy_prev": this.get("year_ago_eps"), "fy0": this["eps"], "ntm": ntm["eps"], "fy1": nxt["eps"]}


def aggregate_path(caps: dict[str, float], stages: dict[str, dict[str, float]]) -> dict | None:
    """Total cap over total earnings at each stage, for the same companies at
    every stage, so a step between stages is the earnings path and not a change
    of who is counted.

    Needs ``AGGREGATE_MIN_COVERAGE`` of the group's cap. If too few companies
    carry last year's actual, that stage is dropped and the rest are kept,
    rather than leaving the whole path blank. ``growth`` is the step's change
    in total earnings from the stage before it; a loss makes the multiple and
    the growth blank, never zero.
    """
    total = sum(caps.values())
    if not total:
        return None
    for wanted in (PATH_STAGES, PATH_STAGES[1:]):
        common = [s for s in caps if caps[s] and all(s in stages.get(k, {}) for k in wanted)]
        covered = sum(caps[s] for s in common)
        if not common or covered < AGGREGATE_MIN_COVERAGE * total:
            continue
        out, previous = [], None
        for key in wanted:
            profit = sum(stages[key][s] for s in common)
            out.append({"key": key, "pe": covered / profit if profit > 0 else None,
                        "growth": (profit / previous - 1) * 100 if profit > 0 and previous and previous > 0 else None})
            previous = profit
        return {"stages": out, "companies": len(common), "coverage": covered / total}
    return None


def scenario_grid(pe: float | None, turns: list[float], eps_changes: list[float]) -> list[list[float | None]]:
    """Price change implied by a forward multiple moved by ``turns`` and NTM
    consensus EPS revised by ``eps_changes`` percent: price = multiple x EPS,
    so (pe + turn) / pe x (1 + eps change) - 1, in percent. Arithmetic on
    today's multiple, not a forecast of either input."""
    if pe is None or pe <= 0:
        return [[None] * len(eps_changes) for _ in turns]
    return [[((pe + turn) / pe * (1 + change / 100) - 1) * 100 if pe + turn > 0 else None
             for change in eps_changes] for turn in turns]


def aggregate_forward(caps: dict[str, float], earnings: dict[str, float]) -> dict | None:
    """Total cap over total NTM earnings for the companies with both, and the
    share of the group's cap they hold."""
    both = [s for s in caps if s in earnings and caps[s]]
    total = sum(caps.values())
    if not both or not total:
        return None
    covered = sum(caps[s] for s in both)
    profit = sum(earnings[s] for s in both)
    return {"pe": covered / profit if profit > 0 else None, "coverage": covered / total}
