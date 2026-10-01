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


def split_factor_after(splits: pd.Series | None, date: str) -> float:
    """Product of the splits after ``date``: what a figure filed that day must be
    scaled by to be on today's share basis."""
    if splits is None:
        return 1.0
    ratios = splits.dropna()
    return float(ratios[ratios.index > pd.Timestamp(date)].prod()) if not ratios.empty else 1.0


def eps_steps(history: Sequence[dict], splits: pd.Series | None) -> list[tuple[str, str, float]]:
    """(filed, period end, TTM EPS on today's share basis) for each quarter.

    Every part is scaled by the splits after *its own* filing date: a filing
    reports every figure on the share basis of the day it was issued, so a
    part filed before a split and one filed after it are on different bases
    until each is scaled separately.
    """
    steps = []
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
