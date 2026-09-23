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

from ..sources.sec import ANNUAL_SPAN_DAYS


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
)


def ratio_table(rows: Sequence[dict]) -> dict[str, list[float | None]]:
    """Each ratio across the rows, oldest first, aligned with the statement columns."""
    out: dict[str, list[float | None]] = {ratio.key: [] for ratio, _ in RATIOS}
    for position, row in enumerate(rows):
        prior = rows[position - 1] if position else None
        for ratio, compute in RATIOS:
            out[ratio.key].append(compute(row, prior))
    return out
