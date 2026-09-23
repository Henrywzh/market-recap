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
from statistics import pstdev

import pandas as pd

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
    (Metric("fcf_yield", "FCF yield", "pct", "valuation", "high", banks=False),
     lambda i: None if i.snapshot["ttm"].get("operating_cash_flow") is None or i.snapshot["ttm"].get("capex") is None
     else _yield(i.snapshot["ttm"]["operating_cash_flow"] - i.snapshot["ttm"]["capex"], i.market_cap)),
    (Metric("dividend_yield", "Dividend yield", "pct", "valuation", "high"),
     lambda i: _yield(i.snapshot["ttm"].get("dividends_paid"), i.market_cap)),
    (Metric("shareholder_yield", "Shareholder yield (div + buyback)", "pct", "valuation", "high"),
     lambda i: None if i.snapshot["ttm"].get("dividends_paid") is None and i.snapshot["ttm"].get("buybacks") is None
     else _yield((i.snapshot["ttm"].get("dividends_paid") or 0) + (i.snapshot["ttm"].get("buybacks") or 0), i.market_cap)),
    (Metric("roe", "ROE (TTM, avg equity)", "pct", "quality", "high"), lambda i: return_on_equity(i.snapshot)),
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
