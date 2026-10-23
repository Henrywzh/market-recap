"""The reverse DCF's enterprise-cash-flow model, and the growth a price implies.

A port of ``web/js/reverse-dcf-math.js`` ``scenarioValue`` (held equal by
``tests/test_reverse_dcf.py`` against the page's own numbers), so the build can
set the growth today's price implies beside the analysts' revenue growth for
every name -- the expectations research's third step
(docs/expectations_research_v1.md). Same assumptions as the page: the shared
WACC, tax, net investment, terminal growth and terminal ROIC in ``[dcf.reverse]``.
All rates here are decimal fractions.
"""

from __future__ import annotations

import math

# The implied growth is searched for between these, and reported outside them, never clamped.
GROWTH_BOUNDS = (-0.5, 1.0)


def scenario_ev(*, revenue: float, base_margin: float, growth: float, margin: float, wacc: float, tax: float,
                net_investment: float, terminal_growth: float, terminal_roic: float, years: int,
                transition_years: int) -> float:
    """Enterprise value of a scenario: ``years`` of revenue growing at ``growth``,
    the margin moving from ``base_margin`` to ``margin`` over ``transition_years``,
    free cash flow as NOPAT less ``net_investment`` of revenue, then a terminal
    value whose reinvestment funds ``terminal_growth`` at ``terminal_roic``."""
    explicit = 0.0
    for year in range(1, years + 1):
        revenue *= 1 + growth
        m = base_margin + (margin - base_margin) * min(1.0, year / transition_years)
        fcf = revenue * m * (1 - tax) - revenue * net_investment
        explicit += fcf / (1 + wacc) ** year
    terminal_nopat = revenue * (1 + terminal_growth) * margin * (1 - tax)
    terminal_fcf = terminal_nopat - terminal_nopat * terminal_growth / terminal_roic
    return explicit + terminal_fcf / (wacc - terminal_growth) / (1 + wacc) ** years


def settings_of(reverse: dict) -> dict:
    """The page's shared assumptions, from ``[dcf.reverse]``, as fractions."""
    return {
        "wacc": reverse["wacc_pct"] / 100, "tax": reverse["tax_pct"] / 100,
        "net_investment": reverse["net_investment_pct"] / 100,
        "terminal_growth": reverse["terminal_growth_pct"] / 100,
        "terminal_roic": reverse["terminal_roic_pct"] / 100,
        "years": int(reverse["years"]), "transition_years": int(reverse["margin_transition_years"]),
    }


def implied_growth(revenue: float, margin: float, target_ev: float, assumptions: dict,
                   tolerance: float = 1e-7) -> dict:
    """The yearly revenue growth at which the model EV, with today's margin held,
    equals ``target_ev``. EV rises with growth only while each dollar of revenue
    leaves free cash flow (margin after tax above net investment); otherwise
    there is no such growth and the status says why."""
    if not (revenue > 0 and 0 < margin < 1 and target_ev > 0):
        return {"status": "invalid", "growth": None}
    if margin * (1 - assumptions["tax"]) <= assumptions["net_investment"]:
        return {"status": "no_free_cash_flow", "growth": None}

    def ev(growth: float) -> float:
        return scenario_ev(revenue=revenue, base_margin=margin, growth=growth, margin=margin, **assumptions)

    low, high = GROWTH_BOUNDS
    if target_ev < ev(low):
        return {"status": "below_range", "growth": None}
    if target_ev > ev(high):
        return {"status": "above_range", "growth": None}
    for _ in range(200):
        if high - low <= tolerance:
            break
        mid = (low + high) / 2
        if ev(mid) < target_ev:
            low = mid
        else:
            high = mid
    growth = (low + high) / 2
    return {"status": "solved", "growth": growth if math.isfinite(growth) else None}
