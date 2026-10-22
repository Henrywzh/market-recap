"""Ratios derived from filed statements -- one definition each.

Every ratio is computed from the same annual rows the statements show, so a
reader can check any figure against the lines above it. Where an input is
missing the ratio is None, never an estimate: a bank has no gross profit, and
a gross margin of zero would be a claim the filing does not make.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pandas as pd

from ..sources.sec import ANNUAL_SPAN_DAYS, QUARTER_SPAN_DAYS


@dataclass(frozen=True)
class Ratio:
    key: str
    label: str
    unit: str  # pct | x | usd


def _div(numerator, denominator) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def _pct(numerator, denominator) -> float | None:
    value = _div(numerator, denominator)
    return None if value is None else value * 100.0


def _average(current, previous) -> float | None:
    """Average of opening and closing balance; the closing balance alone when
    there is no prior year, because a return on the year-end figure is still a
    return on capital -- just a less smooth one."""
    if current is None:
        return None
    return current if previous is None else (float(current) + float(previous)) / 2.0


def _is_prior_year(row: dict, prior: dict | None) -> bool:
    """A growth rate needs the immediately preceding fiscal year, not merely the
    previous row: a filer that skipped tagging a year must not have two years
    of growth reported as one."""
    if prior is None:
        return False
    days = (pd.Timestamp(row["period_end"]) - pd.Timestamp(prior["period_end"])).days
    low, high = ANNUAL_SPAN_DAYS
    return low <= days <= high


def gross_profit(row: dict) -> float | None:
    """As tagged, or revenue less cost of revenue -- the same line by definition."""
    if row.get("gross_profit") is not None:
        return row["gross_profit"]
    if row.get("revenue") is None or row.get("cost_of_revenue") is None:
        return None
    return row["revenue"] - row["cost_of_revenue"]


def free_cash_flow(row: dict) -> float | None:
    if row.get("operating_cash_flow") is None or row.get("capex") is None:
        return None
    return row["operating_cash_flow"] - row["capex"]


def net_debt(row: dict) -> float | None:
    if row.get("total_debt") is None or row.get("cash") is None:
        return None
    return row["total_debt"] - row["cash"] - (row.get("short_term_investments") or 0)


# NOPAT uses the company's own effective tax rate, kept to a plausible band;
# where the rate cannot be read (no tax line, or no pre-tax profit) the
# statutory 21% stands in.
DEFAULT_TAX_RATE = 0.21
TAX_RATE_BOUNDS = (0.0, 0.5)


def nopat(ebit, taxes, pretax) -> float | None:
    if ebit is None:
        return None
    rate = DEFAULT_TAX_RATE
    if taxes is not None and pretax is not None and pretax > 0:
        rate = min(max(taxes / pretax, TAX_RATE_BOUNDS[0]), TAX_RATE_BOUNDS[1])
    return ebit * (1 - rate)


def invested_capital(row: dict) -> float | None:
    """Equity plus debt less cash and short-term investments. A missing debt or
    short-term investment line counts as zero; missing equity or cash is None,
    and so is a capital base that is not positive."""
    if row.get("equity") is None or row.get("cash") is None:
        return None
    capital = (row["equity"] + (row.get("total_debt") or 0) + (row.get("debt_current") or 0)
               - row["cash"] - (row.get("short_term_investments") or 0))
    return capital if capital > 0 else None


RATIOS: tuple[tuple[Ratio, Callable[[dict, dict | None], float | None]], ...] = (
    (Ratio("revenue_growth", "Revenue growth", "pct"),
     lambda r, p: _pct(r["revenue"] - p["revenue"], p["revenue"])
     if _is_prior_year(r, p) and r.get("revenue") is not None and p.get("revenue") else None),
    (Ratio("gross_margin", "Gross margin", "pct"), lambda r, p: _pct(gross_profit(r), r.get("revenue"))),
    (Ratio("operating_margin", "Operating margin", "pct"), lambda r, p: _pct(r.get("ebit"), r.get("revenue"))),
    (Ratio("net_margin", "Net margin", "pct"), lambda r, p: _pct(r.get("net_income"), r.get("revenue"))),
    (Ratio("free_cash_flow", "Free cash flow (OCF - capex)", "usd"), lambda r, p: free_cash_flow(r)),
    (Ratio("fcf_margin", "FCF margin", "pct"), lambda r, p: _pct(free_cash_flow(r), r.get("revenue"))),
    (Ratio("roe", "Return on equity (avg)", "pct"),
     lambda r, p: _pct(r.get("net_income"), _average(r.get("equity"), (p or {}).get("equity") if _is_prior_year(r, p) else None))
     if (r.get("equity") or 0) > 0 else None),
    (Ratio("roa", "Return on assets (avg)", "pct"),
     lambda r, p: _pct(r.get("net_income"), _average(r.get("total_assets"), (p or {}).get("total_assets") if _is_prior_year(r, p) else None))),
    (Ratio("net_debt", "Net debt (LT debt - cash - ST inv.)", "usd"), lambda r, p: net_debt(r)),
    (Ratio("debt_to_equity", "LT debt / equity", "x"),
     lambda r, p: _div(r.get("total_debt"), r.get("equity")) if (r.get("equity") or 0) > 0 else None),
    (Ratio("interest_coverage", "Interest coverage (EBIT / interest)", "x"),
     lambda r, p: _div(r.get("ebit"), r.get("interest_expense"))),
    (Ratio("effective_tax_rate", "Effective tax rate", "pct"),
     lambda r, p: _pct(r.get("taxes"), r.get("pretax_income")) if (r.get("pretax_income") or 0) > 0 else None),
    (Ratio("sbc_to_revenue", "Stock comp / revenue", "pct"), lambda r, p: _pct(r.get("sbc"), r.get("revenue"))),
    (Ratio("roic", "Return on invested capital (avg)", "pct"),
     lambda r, p: _pct(nopat(r.get("ebit"), r.get("taxes"), r.get("pretax_income")),
                       _average(invested_capital(r), invested_capital(p) if _is_prior_year(r, p) else None))),
)


def ratio_table(rows: Sequence[dict]) -> dict[str, list[float | None]]:
    """Each ratio across the rows, oldest first, aligned with the statement columns."""
    out: dict[str, list[float | None]] = {ratio.key: [] for ratio, _ in RATIOS}
    for position, row in enumerate(rows):
        prior = rows[position - 1] if position else None
        for ratio, compute in RATIOS:
            out[ratio.key].append(compute(row, prior))
    return out


# --- Quarterly ratios ---------------------------------------------------------
# Across the quarter columns of quarterly_statements. Margins and free cash flow
# are the quarter's own figures. Growth is against the same quarter a year
# earlier. Returns use the trailing four quarters over the average of the
# balance now and a year ago, and need both balances: a return on a missing
# opening balance is not a return.

QUARTERLY_RATIO_KEYS = (
    "revenue_growth", "gross_margin", "operating_margin", "net_margin", "free_cash_flow",
    "fcf_margin", "roe", "roic", "net_debt",
)


def _year_ago(rows: Sequence[dict], position: int) -> dict | None:
    """The quarter four columns back, when its period end is 350-380 days earlier."""
    if position < 4:
        return None
    prior = rows[position - 4]
    days = (pd.Timestamp(rows[position]["period_end"]) - pd.Timestamp(prior["period_end"])).days
    return prior if 350 <= days <= 380 else None


def _trailing(rows: Sequence[dict], position: int, key: str) -> float | None:
    """The sum of a flow over the four quarters ending at ``position``: None unless
    all four are present and they are consecutive quarters."""
    if position < 3:
        return None
    window = rows[position - 3: position + 1]
    if any(row.get(key) is None for row in window):
        return None
    for earlier, later in zip(window, window[1:]):
        gap = (pd.Timestamp(later["period_end"]) - pd.Timestamp(earlier["period_end"])).days
        if not QUARTER_SPAN_DAYS[0] <= gap <= QUARTER_SPAN_DAYS[1]:
            return None
    return float(sum(row[key] for row in window))


def _both_balances(now, then) -> float | None:
    """The average of two balances, or None when either is missing."""
    if now is None or then is None:
        return None
    return (float(now) + float(then)) / 2.0


def quarterly_ratio_table(rows: Sequence[dict]) -> dict[str, list[float | None]]:
    """Each quarterly ratio across the quarter rows, oldest first."""
    out: dict[str, list[float | None]] = {key: [] for key in QUARTERLY_RATIO_KEYS}
    for position, row in enumerate(rows):
        year_ago = _year_ago(rows, position)
        revenue_then = (year_ago or {}).get("revenue")
        growth = None
        if year_ago is not None and row.get("revenue") is not None and revenue_then:
            growth = _pct(row["revenue"] - revenue_then, revenue_then)
        ttm_net_income = _trailing(rows, position, "net_income")
        equity = _both_balances(row.get("equity"), (year_ago or {}).get("equity"))
        roe = _pct(ttm_net_income, equity) if ttm_net_income is not None and equity and equity > 0 else None
        capital = _both_balances(invested_capital(row), invested_capital(year_ago) if year_ago else None)
        ttm_nopat = nopat(
            _trailing(rows, position, "ebit"),
            _trailing(rows, position, "taxes"),
            _trailing(rows, position, "pretax_income"),
        )
        roic = _pct(ttm_nopat, capital)
        values = {
            "revenue_growth": growth,
            "gross_margin": _pct(gross_profit(row), row.get("revenue")),
            "operating_margin": _pct(row.get("ebit"), row.get("revenue")),
            "net_margin": _pct(row.get("net_income"), row.get("revenue")),
            "free_cash_flow": free_cash_flow(row),
            "fcf_margin": _pct(free_cash_flow(row), row.get("revenue")),
            "roe": roe,
            "roic": roic,
            "net_debt": net_debt(row),
        }
        for key in QUARTERLY_RATIO_KEYS:
            out[key].append(values[key])
    return out
