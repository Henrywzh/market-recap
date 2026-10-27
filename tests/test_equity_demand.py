from __future__ import annotations

import pytest

from market_recap.config import load_config
import pandas as pd

from market_recap.compute.buybacks import aggregate_history, attach_turnover, cash_execution, latest_capacity, plan_facts, quarter_at
from market_recap.compute.equity_demand import build_hedge_fund_monitor, build_sector_and_foreign_demand


def test_buyback_history_missing_and_incomplete_periods():
    rows = [
        {"start": "2024-01-01", "end": "2024-03-31", "value": 1e9},
        {"start": "2024-04-01", "end": "2024-06-30", "value": 2e9},
        {"start": "2024-07-01", "end": "2024-09-30", "value": 0},
        {"start": "2024-10-01", "end": "2024-12-31", "value": 3e9},
    ]
    out = aggregate_history({1: rows, 2: rows[:2]}, cutoff="2025-02-01", issuer_count=2)
    q3 = next(r for r in out["quarterly"] if r["period"] == "2024Q3")
    assert (q3["covered_sum_bn"], q3["covered_issuers"], q3["coverage_pct"]) == (0, 1, 50)
    assert out["annual"][0]["covered_sum_bn"] == 6
    assert out["annual"][0]["covered_issuers"] == 1
    assert out["quarterly"][-1]["covered_sum_bn"] is None
    assert out["quarterly"][-1]["period_ended"] is False


def test_buyback_yoy_uses_same_companies_only():
    out = aggregate_history({
        1: [{"start": "2023-01-01", "end": "2023-03-31", "value": 1e9},
            {"start": "2024-01-01", "end": "2024-03-31", "value": 2e9}],
        2: [{"start": "2024-01-01", "end": "2024-03-31", "value": 8e9}],
    }, cutoff="2024-05-01", issuer_count=2)
    row = next(r for r in out["quarterly"] if r["period"] == "2024Q1")
    assert row["covered_sum_bn"] == 10
    assert row["matched_yoy"] == {"issuers": 1, "current_bn": 2, "prior_bn": 1, "change_bn": 1, "change_pct": 100}


def test_turnover_ratio_requires_same_issuer_and_sufficient_sessions():
    idx = pd.bdate_range('2024-01-01', '2024-03-31')
    prices = pd.DataFrame({'A': 10.0, 'B': 20.0}, index=idx)
    volumes = pd.DataFrame({'A': 100.0, 'B': 100.0}, index=idx)
    volumes.loc[idx[:15], 'B'] = float('nan')
    q = {'start': '2024-01-01', 'end': '2024-03-31', 'value': 6500}
    attached = attach_turnover({1: [q], 2: [q]}, {1: ['A'], 2: ['B']}, prices, volumes)
    out = aggregate_history(attached, cutoff='2024-04-30', issuer_count=2)
    ratio = out['quarterly'][0]['trading_value_comparison']
    assert ratio['issuers'] == 1
    assert ratio['ratio_pct'] == round(6500 / (len(idx) * 1000) * 100, 3)


def test_sector_and_foreign_demand_offline_reconciliation():
    cfg = load_config()["risk"]["equity_demand"]
    # It reconciles the downloaded Z.1 and TIC files: a checkout or CI run that has
    # not fetched them yet has nothing to reconcile, which is not a failure.
    try:
        out = build_sector_and_foreign_demand(cfg, offline=True)
    except FileNotFoundError as missing:
        pytest.skip(str(missing))
    z1 = out["z1"]
    assert z1["quarters_count"] >= 298
    assert z1["first_quarter"] == "1952Q1"
    assert z1["reconciliation"]["passed"] is True
    groups = {g["key"]: g for g in z1["groups"]}
    assert {"households", "mutual_funds", "pensions", "foreign", "etfs"} <= set(groups)
    pensions_sum = sum(c["latest_bn"] for c in z1["pension_components"])
    assert abs(pensions_sum - groups["pensions"]["latest_bn"]) <= 0.02

    foreign = out["foreign"]
    assert foreign["tic_months_count"] >= 43
    sb = foreign["scope_bridge"]
    assert sb["matched_quarters"] >= 13
    assert sb["scope_aligned_mean_abs_diff_bn"] < 1.0
    assert sb["raw_mean_abs_diff_bn"] > 20.0


def test_buyback_ytd_derivation_and_reconciliation_exception():
    periods = {
        ("2025-01-01", "2025-03-31"): {"value": 100.0, "filed": "2025-05-01"},
        ("2025-01-01", "2025-06-30"): {"value": 250.0, "filed": "2025-08-01"},
    }
    q2 = quarter_at(periods, "2025-06-30")
    assert q2 is not None
    assert q2["method"] == "same_fiscal_start_difference"
    assert q2["value"] == 150.0

    # Construct a synthetic 4-quarter sequence whose sum disagrees with FY TTM by > $1M
    facts = {
        "facts": {
            "us-gaap": {
                "PaymentsForRepurchaseOfCommonStock": {
                    "units": {
                        "USD": [
                            {"form": "10-Q", "start": "2025-01-01", "end": "2025-03-31", "val": 100_000_000, "filed": "2025-05-01"},
                            {"form": "10-Q", "start": "2025-01-01", "end": "2025-06-30", "val": 200_000_000, "filed": "2025-08-01"},
                            {"form": "10-Q", "start": "2025-01-01", "end": "2025-09-30", "val": 300_000_000, "filed": "2025-11-01"},
                            {"form": "10-K", "start": "2025-01-01", "end": "2025-12-31", "val": 400_000_000, "filed": "2026-02-15"},
                            {"form": "10-Q", "start": "2025-10-01", "end": "2025-12-31", "val": 105_000_000, "filed": "2026-02-15"},
                        ]
                    }
                }
            }
        }
    }
    recent = {"form": ["10-K"], "filingDate": ["2026-02-15"], "reportDate": ["2025-12-31"]}
    ce = cash_execution(facts, recent, "2026-10-27", tolerance_usd=1_000_000.0)
    assert ce["status"] == "quarter_ttm_reconciliation_exception"
    assert ce["ttm_usd"] is None
    assert ce["quarter_usd"] is None


def test_plan_facts_dedup_and_capacity():
    html = """
    <html><body>
      <xbrli:context id="c_plan">
        <xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period>
        <xbrli:scenario>
          <xbrldi:explicitMember dimension="us-gaap:ShareRepurchaseProgramAxis">meta:Jan2017PlanMember</xbrldi:explicitMember>
        </xbrli:scenario>
      </xbrli:context>
      <xbrli:unit id="u_usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
      <ix:nonFraction name="us-gaap:StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1" contextRef="c_plan" unitRef="u_usd" scale="9">25.03</ix:nonFraction>
      <ix:nonFraction name="us-gaap:StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1" contextRef="c_plan" unitRef="u_usd" scale="9">25.03</ix:nonFraction>
    </body></html>
    """
    rows = plan_facts(
        html,
        filed="2026-10-22",
        cutoff="2026-10-27",
        source="https://www.sec.gov/example",
        allowed_tags=["StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1"],
    )
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 2
    assert rows[0]["amount_usd"] == 25.03e9
    cap = latest_capacity(rows, "2026-09-30")
    assert cap["status"] == "program_observations_only"
    assert cap["remaining_usd"] is None


def test_hedge_fund_monitor_form_pf():
    cfg = load_config()["risk"]["equity_demand"]
    hfm = build_hedge_fund_monitor(cfg=cfg)
    fpf = hfm["form_pf"]
    assert fpf["latest_period"] == "2026-06-30"
    assert fpf["cash_equities"]["net_bn"] == 2423.0
    assert fpf["equity_derivatives"]["net_bn"] == -350.0
    assert fpf["financing"]["prime_broker_borrowing_bn"] == 3688.0
