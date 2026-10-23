"""The reverse DCF in Python: equal to the page's model, and the growth a price implies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_recap.compute import reverse_dcf as R

CASES = json.loads((Path(__file__).parent / "fixtures" / "reverse_dcf_cases.json").read_text())
ASSUME = {"wacc": 0.09, "tax": 0.25, "net_investment": 0.05, "terminal_growth": 0.025, "terminal_roic": 0.15,
          "years": 10, "transition_years": 5}


@pytest.mark.parametrize("case", CASES)
def test_the_model_ev_equals_the_pages_scenario_value(case):
    c = case["c"]
    ev = R.scenario_ev(revenue=c["revenue"], base_margin=c["baseMargin"], growth=c["growth"], margin=c["margin"],
                       wacc=c["wacc"], tax=c["tax"], net_investment=c["netInvestment"],
                       terminal_growth=c["terminalGrowth"], terminal_roic=c["terminalRoic"],
                       years=c["years"], transition_years=c["transitionYears"])
    assert ev == pytest.approx(case["ev"], rel=1e-12)


def test_the_implied_growth_reprices_the_model_to_the_target():
    target = R.scenario_ev(revenue=1000, base_margin=0.2, growth=0.12, margin=0.2, **ASSUME)
    found = R.implied_growth(1000, 0.2, target, ASSUME)
    assert found["status"] == "solved" and found["growth"] == pytest.approx(0.12, abs=1e-6)


def test_no_growth_is_implied_without_free_cash_flow_or_outside_the_range():
    assert R.implied_growth(1000, 0.05, 5000, ASSUME)["status"] == "no_free_cash_flow"   # 3.75% NOPAT < 5% investment
    assert R.implied_growth(1000, 0.2, 1.0, ASSUME)["status"] == "below_range"
    assert R.implied_growth(1000, 0.2, 1e15, ASSUME)["status"] == "above_range"
    assert R.implied_growth(-1, 0.2, 100, ASSUME)["status"] == "invalid"


def test_settings_are_read_as_fractions():
    s = R.settings_of({"wacc_pct": 9.0, "tax_pct": 25.0, "net_investment_pct": 5.0, "terminal_growth_pct": 2.5,
                       "terminal_roic_pct": 15.0, "years": 10, "margin_transition_years": 5})
    assert s == ASSUME


def test_a_valuation_row_gets_the_implied_growth_beside_the_analysts_or_the_reason_it_has_none():
    from types import SimpleNamespace
    from market_recap.panels import valuation as panel
    reverse = {"wacc_pct": 9.0, "tax_pct": 25.0, "net_investment_pct": 5.0, "terminal_growth_pct": 2.5,
               "terminal_roic_pct": 15.0, "years": 10, "margin_transition_years": 5, "annual_max_age_days": 550,
               "excluded_sectors": ["Financials"], "excluded_subindustries": ["Biotechnology"]}
    ev = R.scenario_ev(revenue=1000, base_margin=0.2, growth=0.1, margin=0.2, **ASSUME)
    row = {"sector": "Industrials", "sub_sector": "Machinery", "ev": ev, "debt_basis": "long-term debt",
           "revenue_consensus": {"periods": [{"growth_pct": 6.0}, {"growth_pct": 7.5}]}}
    data = SimpleNamespace(rows=({"revenue": 1000, "ebit": 200, "period_end": "2026-06-30"},))
    out = panel._expectation_gap(row, data, reverse, "2026-10-23")
    assert out["implied_growth"] == pytest.approx(10.0, abs=0.05) and out["consensus_growth"] == 7.5
    assert out["implied_growth_status"] == "solved" and "growth_gap" not in out
    assert panel._expectation_gap({**row, "sector": "Financials"}, data, reverse, "2026-10-23")["implied_growth_status"] == "excluded_business"
    assert panel._expectation_gap({**row, "debt_basis": "no debt tagged"}, data, reverse, "2026-10-23")["implied_growth_status"] == "inputs_missing"
    old = SimpleNamespace(rows=({"revenue": 1000, "ebit": 200, "period_end": "2024-06-30"},))
    assert panel._expectation_gap(row, old, reverse, "2026-10-23")["implied_growth"] is None
