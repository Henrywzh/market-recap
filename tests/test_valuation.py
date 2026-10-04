"""VALUATION & QUALITY: trailing figures, share counts and the metrics built on them."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import valuation as V
from market_recap.panels import valuation as panel
from market_recap.sources import sec


def _period(start, end, value, filed="2026-08-01"):
    return {(start, end): {"value": value, "filed": filed, "priority": 0}}


def test_ttm_is_last_year_plus_year_to_date_less_the_same_span_a_year_ago():
    """Apple, June 2026: 416,161 + 364,357 - 313,695."""
    periods = {
        **_period("2024-09-29", "2025-09-27", 416_161),
        **_period("2025-09-28", "2026-06-27", 364_357),
        **_period("2026-03-29", "2026-06-27", 109_417),
        **_period("2024-09-29", "2025-06-28", 313_695),
    }
    assert sec.trailing_value(periods, "2026-06-27")[0] == 416_161 + 364_357 - 313_695


def test_ttm_at_a_fiscal_year_end_is_the_year_itself():
    assert sec.trailing_value(_period("2025-01-01", "2025-12-31", 90), "2025-12-31")[0] == 90


def test_ttm_with_a_missing_part_is_blank_not_annualised():
    periods = {**_period("2026-01-01", "2026-06-30", 50), **_period("2025-01-01", "2025-12-31", 90)}
    assert sec.trailing_value(periods, "2026-06-30") == (None, None)


def _facts(cover_val, cover_filed="2026-08-11"):
    return {"facts": {"dei": {sec.COVER_SHARES_TAG: {"units": {"shares": [
        {"end": "2026-08-07", "val": cover_val, "filed": cover_filed}]}}}}}


def _diluted(value):
    return _period("2026-04-05", "2026-07-04", value)


def test_a_complete_cover_count_is_used():
    shares = sec._market_shares(_facts(98_248_111), _diluted(99_000_000), "2026-07-04", "2026-08-11")
    assert shares["shares"] == 98_248_111 and shares["shares_basis"].startswith("cover page")


def test_a_partial_cover_count_falls_back_to_the_diluted_count():
    """A multi-class filer that tags one class on its cover."""
    shares = sec._market_shares(_facts(5_000_000_000), _diluted(12_300_000_000), "2026-07-04", "2026-08-11")
    assert shares["shares"] == 12_300_000_000
    assert shares["shares_as_of"] == "2026-08-11"  # the filing date: restated for any earlier split


def test_a_diluted_count_a_thousand_times_the_cover_is_a_units_error():
    """Waters tagged 98.2 billion diluted shares against 98.2 million on its cover."""
    shares = sec._market_shares(_facts(98_248_111), _diluted(98_204_000_000), "2026-07-04", "2026-08-11")
    assert shares["shares"] == 98_248_111 and "units check" in shares["shares_basis"]


def test_a_split_after_the_count_is_applied_and_one_before_is_not():
    """Amphenol split 2:1 on 2026-09-03, after its July 10-Q."""
    splits = pd.DataFrame({"APH": [2.0, 2.0]}, index=pd.to_datetime(["2024-06-12", "2026-09-03"]))
    assert panel._split_factor(splits, "APH", "2026-07-28") == 2.0
    assert panel._split_factor(splits, "APH", "2026-09-04") == 1.0
    assert panel._split_factor(splits, "MSFT", "2026-07-28") == 1.0


def test_the_weight_check_compares_companies_not_listings():
    """GOOG and GOOGL are one market cap and two SPY lines."""
    rows = [
        {"ticker": "GOOGL", "cik": 1, "market_cap": 400.0, "shares_basis": ""},
        {"ticker": "GOOG", "cik": 1, "market_cap": 400.0, "shares_basis": ""},
        {"ticker": "MSFT", "cik": 2, "market_cap": 400.0, "shares_basis": ""},
    ]
    check = panel._weight_check(rows, {"GOOGL": 2.0, "GOOG": 2.0, "MSFT": 4.0})
    assert check["checked"] == 2 and check["flagged"] == []
    assert {r["weight_ratio"] for r in rows} == {1.0}


def _snapshot(**overrides):
    base = {
        "ttm": {"revenue": 100.0, "net_income": 10.0, "ebit": 15.0, "dep_amort": 5.0, "pretax_income": 14.0,
                "taxes": 3.0, "operating_cash_flow": 12.0, "capex": 4.0, "dividends_paid": 2.0, "buybacks": 3.0,
                "interest_expense": 1.0},
        "ttm_prior": {"revenue": 80.0},
        "balance": {"equity": 50.0, "cash": 10.0, "total_debt": 30.0, "debt_current": 5.0, "total_assets": 200.0},
        "balance_prior": {"equity": 40.0},
        "debt_includes_current": False,
    }
    for key, value in overrides.items():
        base[key] = {**base[key], **value}
    return base


def test_ev_and_the_multiples_built_on_it():
    snapshot = _snapshot()
    ev = V.enterprise_value(200.0, snapshot)
    assert ev == 200 + 35 - 10
    metrics = V.compute(V.Inputs(snapshot, [], 200.0, ev), sector="Industrials")
    assert metrics["pe"] == 20.0
    assert metrics["ev_ebitda"] == pytest.approx(225 / 20)
    assert metrics["roe"] == pytest.approx(10 / 45 * 100)
    assert metrics["revenue_growth"] == pytest.approx(25.0)
    assert metrics["shareholder_yield"] == pytest.approx(2.5)


def test_longterm_debt_that_already_includes_the_current_portion_is_not_counted_twice():
    snapshot = _snapshot(balance={"total_debt": 35.0, "debt_current": 5.0})
    snapshot["debt_includes_current"] = True
    assert V.debt(snapshot)[0] == 35.0


def test_a_loss_or_negative_equity_leaves_the_multiple_blank():
    snapshot = _snapshot(ttm={"net_income": -5.0}, balance={"equity": -20.0})
    metrics = V.compute(V.Inputs(snapshot, [], 200.0, None), sector="Industrials")
    assert metrics["pe"] is None and metrics["pb"] is None and metrics["roe"] is None


def test_bank_metrics_that_mean_nothing_for_a_bank_are_not_computed():
    metrics = V.compute(V.Inputs(_snapshot(), [], 200.0, 225.0), sector=V.FINANCIALS_SECTOR)
    assert metrics["ev_ebitda"] is None and metrics["fcf_yield"] is None
    assert metrics["pe"] == 20.0 and metrics["pb"] == 4.0


def test_ebit_and_da_fall_back_to_their_parts():
    """Exxon tags no operating income; Microsoft no combined D&A."""
    assert V.ebit({"pretax_income": 40.0, "interest_expense": 2.0}) == 42.0
    assert V.depreciation_and_amortization({"depreciation": 20.0, "amortization": 3.0}) == 23.0


def _year(end, **values):
    base = {"period_end": end, "net_income": 10.0, "total_assets": 100.0, "operating_cash_flow": 12.0,
            "total_debt": 20.0, "current_assets": 30.0, "current_liabilities": 20.0, "shares": 100.0,
            "revenue": 80.0, "gross_profit": 40.0}
    return {**base, **values}


def test_piotroski_scores_only_when_all_nine_signals_are_testable():
    before = _year("2024-12-31")
    better = _year("2025-12-31", net_income=12.0, total_debt=15.0, current_assets=35.0, shares=98.0,
                   revenue=90.0, gross_profit=48.0, operating_cash_flow=15.0)
    assert V.piotroski([before, better]) == (9, 9)
    assert V.piotroski([before, {**better, "current_assets": None}]) == (None, 8)


def _prices(start="2020-01-01", periods=600, value=100.0):
    return pd.Series(value, index=pd.bdate_range(start, periods=periods))


def test_eps_applies_from_the_session_after_it_was_filed():
    prices = _prices(periods=10)
    pe = V.pe_series(prices, [("2020-01-03", "2019-12-31", 5.0)])
    assert pe.loc[:"2020-01-03"].isna().all()          # not known on the filing day itself
    assert pe.loc["2020-01-06"] == 20.0


def test_an_eps_with_no_successor_expires_instead_of_standing_forever():
    """Monster stopped tagging EPS in 2011; its 2011 figure priced 2026 at 193x."""
    prices = _prices(periods=400)
    pe = V.pe_series(prices, [("2020-01-01", "2019-12-31", 5.0)])
    assert pe.loc["2020-03-02"] == 20.0
    assert pe.iloc[-1] != pe.iloc[-1]  # NaN once it has gone unreplaced too long


def test_a_loss_leaves_a_gap():
    pe = V.pe_series(_prices(periods=5), [("2019-12-01", "2019-11-30", -1.0)])
    assert pe.isna().all()


def test_each_eps_part_is_put_on_todays_basis_by_its_own_filing_date():
    """A 2:1 split between the 10-K and the 10-Q: the 10-K's year is on the
    old basis, the 10-Q's year-to-date parts on the new."""
    splits = pd.Series([2.0], index=pd.to_datetime(["2026-03-01"]))
    history = [{"period_end": "2026-06-30", "filed": "2026-08-01",
                "parts": [(3.0, "2026-08-01", 1), (8.0, "2026-02-01", 1), (2.5, "2026-08-01", -1)]}]
    assert V.eps_steps(history, splits)[0][2] == pytest.approx(3.0 + 4.0 - 2.5)


def test_history_stats_need_two_years_and_place_the_latest_point():
    pe = pd.Series(range(1, V.MIN_HISTORY_SESSIONS + 1), index=pd.bdate_range("2020-01-01", periods=V.MIN_HISTORY_SESSIONS), dtype=float)
    stats = V.pe_stats(pe)
    assert stats["percentile"] == 100.0 and stats["current"] == V.MIN_HISTORY_SESSIONS
    assert V.pe_stats(pe.iloc[:-1]) is None


def test_eps_history_uses_only_what_had_been_filed_at_the_time():
    """A later restatement of last year must not leak into an earlier quarter."""
    rows = [
        {"form": "10-K", "fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": 10.0, "filed": "2026-02-10"},
        {"form": "10-Q", "fp": "Q1", "start": "2026-01-01", "end": "2026-03-31", "val": 3.0, "filed": "2026-05-01"},
        {"form": "10-Q", "fp": "Q1", "start": "2025-01-01", "end": "2025-03-31", "val": 2.0, "filed": "2026-05-01"},
        # A 10-K/A two years later restates 2025 to 6.0.
        {"form": "10-K", "fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": 6.0, "filed": "2028-02-10"},
    ]
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": rows}}}}}
    history = {h["period_end"]: h for h in sec.eps_history(facts)}
    q1 = history["2026-03-31"]
    assert sum(v * sign for v, _, sign in q1["parts"]) == 10.0 + 3.0 - 2.0


def test_aggregate_pe_counts_losses_and_blanks_thin_coverage():
    import numpy as np
    import pandas as pd

    from market_recap.compute import valuation as V

    sessions = pd.date_range("2026-01-02", periods=3, freq="B")
    caps = pd.DataFrame({"A": [100.0, 100.0, 100.0], "B": [100.0, 100.0, 100.0]}, index=sessions)
    earnings = pd.DataFrame({"A": [10.0, 10.0, 10.0], "B": [-5.0, np.nan, 5.0]}, index=sessions)
    out = V.aggregate_pe(caps, earnings)
    # A loss lowers the group's earnings rather than dropping out.
    assert out["pe"].iloc[0] == 200.0 / 5.0
    # Half the priced cap without an EPS in force is below the coverage floor.
    assert out["coverage"].iloc[1] == 0.5 and np.isnan(out["pe"].iloc[1])
    assert out["pe"].iloc[2] == 200.0 / 15.0


def test_eps_in_force_keeps_losses_and_expires():
    import numpy as np
    import pandas as pd

    from market_recap.compute import valuation as V

    sessions = pd.DatetimeIndex(["2026-01-05", "2026-02-10", "2026-12-01"])
    eps = V.eps_in_force(sessions, [("2026-02-01", "2025-12-31", -1.5)])
    assert np.isnan(eps.iloc[0])
    assert eps.iloc[1] == -1.5
    assert np.isnan(eps.iloc[2])  # stood longer than EPS_STALE_AFTER_DAYS


def test_pe_series_blanks_an_eps_in_the_wrong_units():
    import numpy as np
    import pandas as pd

    from market_recap.compute import valuation as V

    prices = pd.Series([30.0, 30.0], index=pd.DatetimeIndex(["2021-08-02", "2022-01-03"]))
    steps = [("2021-07-23", "2021-06-30", 3519996.66), ("2021-10-22", "2021-09-30", 1.5)]
    pe = V.pe_series(prices, steps)
    assert np.isnan(pe.iloc[0])
    assert pe.iloc[1] == 20.0


# --- Operating P/E ----------------------------------------------------------------

def _quarter(filed, eps, **core):
    """One eps_history entry with a single-part TTM EPS and its core inputs."""
    base = {"ebit": None, "interest_expense": None, "pretax_income": None, "taxes": None, "net_income": None,
            "equity_gains": None, "minority_share": None, "profit_loss": None, "parent_income": None,
            "shares": 10.0, "shares_filed": filed}
    return {"period_end": filed, "filed": filed, "parts": [(eps, filed, 1)], "core": base | core}


def test_a_quarterly_report_never_replaces_the_annual_reports_year():
    """Comfort Systems' Q1 10-Q tagged Q1 2025 as the whole of 2025."""
    rows = [
        {"form": "10-K", "start": "2025-01-01", "end": "2025-12-31", "val": 1314.0, "filed": "2026-02-19"},
        {"form": "10-Q", "start": "2025-01-01", "end": "2025-12-31", "val": 209.0, "filed": "2026-04-23"},
    ]
    facts = {"facts": {"us-gaap": {"OperatingIncomeLoss": {"units": {"USD": rows}}}}}
    item = sec.ITEMS_BY_KEY["ebit"]
    key = ("2025-01-01", "2025-12-31")
    assert sec._period_values(facts, item, ())[key]["value"] == 1314.0
    assert sec._vintages(facts, item, ["2026-05-01"])["2026-05-01"][key]["value"] == 1314.0


def test_vintages_match_period_values_as_of_each_day():
    rows = [
        {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "val": 8.0, "filed": "2025-02-01"},
        {"form": "10-Q", "start": "2025-01-01", "end": "2025-03-31", "val": 3.0, "filed": "2025-05-01"},
        {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31", "val": 7.5, "filed": "2026-02-01"},
    ]
    facts = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": rows}}}}}
    item = sec.ITEMS_BY_KEY["net_income"]
    days = ["2025-01-01", "2025-02-01", "2025-06-01", "2026-03-01"]
    vintages = sec._vintages(facts, item, days)
    for day in days:
        expected = {k: v["value"] for k, v in sec._period_values(facts, item, (), filed_by=day).items()}
        assert {k: v["value"] for k, v in vintages[day].items()} == expected


def test_tax_rate_is_a_median_that_one_charge_does_not_move():
    history = [_quarter(f"2025-0{i}-01", 1.0, taxes=20.0, pretax_income=100.0) for i in range(1, 6)]
    history.append(_quarter("2025-07-01", 1.0, taxes=90.0, pretax_income=100.0))   # a one-off charge
    assert V.tax_rates(history)[-1] == pytest.approx(0.20)
    # No positive pre-tax income: the federal rate; an extreme rate is bounded.
    assert V.tax_rates([_quarter("2025-01-01", -1.0, taxes=5.0, pretax_income=-10.0)]) == [V.DEFAULT_TAX_RATE]
    assert V.tax_rates([_quarter("2025-01-01", 1.0, taxes=60.0, pretax_income=100.0)]) == [V.TAX_RATE_BOUNDS[1]]


def test_operating_eps_takes_out_a_stake_gain_but_keeps_interest():
    """Alphabet's shape: pre-tax far above operating income on equity gains."""
    q = _quarter("2026-07-23", 20.0, ebit=150.0, interest_expense=2.0, pretax_income=300.0, taxes=40.0,
                 net_income=200.0)
    step = V.operating_steps([q], None, V.OPERATING)[0]
    rate = 40.0 / 300.0
    assert step["eps"] == pytest.approx((150.0 - 2.0) * (1 - rate) / 10.0)
    assert step["removed"] == pytest.approx(20.0 - step["eps"])


def test_operating_eps_keeps_losses_below_the_line_and_odd_interest_signs():
    # Pre-tax below operating income less interest: the loss stays (Disney's
    # operating line is its segment total; Charter tags no interest at all).
    loss = _quarter("2026-01-01", 5.0, ebit=180.0, interest_expense=-18.0, pretax_income=120.0, taxes=30.0)
    no_interest = _quarter("2026-01-01", 5.0, ebit=126.0, pretax_income=75.0, taxes=18.0)
    for q in (loss, no_interest):
        rate = q["core"]["taxes"] / q["core"]["pretax_income"]
        assert V.operating_steps([q], None, V.OPERATING)[0]["eps"] == pytest.approx(
            q["core"]["pretax_income"] * (1 - rate) / 10.0)


def test_operating_eps_is_the_parents_share():
    q = _quarter("2026-01-01", 2.0, ebit=100.0, pretax_income=100.0, taxes=20.0, profit_loss=80.0, parent_income=40.0)
    assert V.operating_steps([q], None, V.OPERATING)[0]["eps"] == pytest.approx((80.0 - 40.0) / 10.0)
    q["core"]["minority_share"] = 30.0     # the direct tag wins
    assert V.operating_steps([q], None, V.OPERATING)[0]["eps"] == pytest.approx((80.0 - 30.0) / 10.0)


def test_share_count_in_the_wrong_units_is_replaced_by_the_implied_one():
    """Waters tagged 98.2 billion diluted shares for 98.2 million."""
    q = _quarter("2026-08-11", 2.0, ebit=100.0, pretax_income=100.0, taxes=20.0, net_income=80.0, shares=40_000.0)
    assert V.operating_steps([q], None, V.OPERATING)[0]["eps"] == pytest.approx(80.0 / 40.0)


def test_financials_and_utilities_are_reported_less_equity_gains():
    q = _quarter("2026-01-01", 10.0, ebit=None, pretax_income=100.0, taxes=20.0, equity_gains=25.0)
    for sector in (V.FINANCIALS_SECTOR, "Utilities"):
        assert V.operating_basis([q], sector) == V.EX_GAINS
    assert V.operating_basis([q], "Industrials") == V.EX_GAINS          # no operating line filed
    q["core"]["ebit"] = 90.0
    assert V.operating_basis([q], "Industrials") == V.OPERATING
    step = V.operating_steps([q], None, V.EX_GAINS)[0]
    assert step["eps"] == pytest.approx(10.0 - 25.0 * (1 - 0.2) / 10.0)


def test_operating_share_count_follows_a_split_after_its_filing():
    import pandas as pd

    splits = pd.Series([4.0], index=[pd.Timestamp("2026-03-01")])
    q = _quarter("2026-01-15", 8.0, ebit=100.0, pretax_income=100.0, taxes=20.0)
    step = V.operating_steps([q], splits, V.OPERATING)[0]
    assert step["reported"] == pytest.approx(2.0)
    assert step["eps"] == pytest.approx(80.0 / 40.0)


# --- Forward P/E ---------------------------------------------------------------------

def test_ntm_eps_weights_this_and_next_year_by_what_is_left():
    trend = {"0y": {"end": "2026-12-31", "eps": 10.0}, "+1y": {"end": "2027-12-31", "eps": 12.0}}
    ntm = V.ntm_eps(trend, pd.Timestamp("2026-10-01"))
    weight = 91 / 365.25
    assert ntm["eps"] == pytest.approx(weight * 10 + (1 - weight) * 12)
    # A fiscal year that ended but has not been reported weighs nothing (Micron's FY26).
    trend = {"0y": {"end": "2026-08-31", "eps": 73.9}, "+1y": {"end": "2027-08-31", "eps": 161.5}}
    assert V.ntm_eps(trend, pd.Timestamp("2026-10-01"))["eps"] == pytest.approx(161.5)
    assert V.ntm_eps({"0y": {"end": "2026-12-31", "eps": 1.0}}, pd.Timestamp("2026-10-01")) is None
    assert V.forward_pe(100.0, {"eps": -1.0}) is None


def test_group_forward_pe_is_cap_over_ntm_earnings_with_coverage():
    out = V.aggregate_forward({"A": 100.0, "B": 300.0, "C": 100.0}, {"A": 5.0, "B": 15.0})
    assert out["pe"] == pytest.approx(400.0 / 20.0) and out["coverage"] == pytest.approx(0.8)


def test_row_takes_yahoo_cap_only_without_a_share_count_and_flags_history_truthfully():
    from market_recap.sources import sec
    ttm = {"net_income": 80e9, "revenue": 370e9}
    trailing = {"shares": None, "shares_as_of": None, "shares_basis": "no complete share count filed",
                "ttm": ttm, "ttm_prior": {}, "balance": {"equity": 650e9}, "balance_prior": {},
                "period_end": "2026-06-30", "filed": "2026-08-10", "lagged": [], "debt_includes_current": False}
    data = sec.Filer("Berkshire", (1067983,), ("us-gaap",), (), trailing)
    row = panel._row("BRK-B", {"sector": "Financials"}, data, 500.0, ["SPX"], pd.DataFrame(), None, fallback_cap=1.07e12)
    assert row["market_cap"] == 1.07e12 and row["shares_basis"] == panel.YAHOO_CAP_BASIS
    assert row["pe"] == pytest.approx(1.07e12 / 80e9, rel=1e-3)
    assert row["pe_history"] is False                                  # no history was built: none to fetch
    filed = dict(trailing, shares=2e9, shares_as_of="2026-07-31", shares_basis="cover page shares outstanding")
    row = panel._row("X", {}, sec.Filer("X", (1,), ("us-gaap",), (), filed), 10.0, [], pd.DataFrame(), {}, fallback_cap=9e12)
    assert row["market_cap"] == 2e10 and row["pe_history"] is True    # the filings' count wins


def test_fiscal_path_needs_both_years_and_tolerates_a_missing_actual():
    ntm = {"eps": 11.0}
    trend = {"0y": {"eps": 10.0, "year_ago_eps": 8.0}, "+1y": {"eps": 12.0}}
    assert V.fiscal_path(trend, ntm) == {"fy_prev": 8.0, "fy0": 10.0, "ntm": 11.0, "fy1": 12.0}
    assert V.fiscal_path({"0y": {"eps": 10.0}, "+1y": {"eps": 12.0}}, ntm)["fy_prev"] is None
    assert V.fiscal_path({"0y": {"eps": 10.0}}, ntm) is None
    assert V.fiscal_path(trend, None) is None


def test_aggregate_path_counts_the_same_companies_at_every_stage():
    caps = {"A": 100.0, "B": 100.0, "C": 100.0}
    stages = {"fy_prev": {"A": 4.0, "B": 4.0, "C": 4.0}, "fy0": {"A": 5.0, "B": 5.0, "C": 5.0},
              "ntm": {"A": 5.5, "B": 5.5, "C": 5.5}, "fy1": {"A": 6.0, "B": 6.0}}
    # C has no FY+1, so no stage counts it: a step is earnings growth, not a new member.
    out = V.aggregate_path(caps, stages)
    assert out is None                                    # A and B hold 67% of the cap, under the 80% floor
    stages["fy1"]["C"] = 6.0
    out = V.aggregate_path(caps, stages)
    assert [s["key"] for s in out["stages"]] == ["fy_prev", "fy0", "ntm", "fy1"]
    assert out["stages"][0]["pe"] == pytest.approx(300 / 12) and out["stages"][3]["pe"] == pytest.approx(300 / 18)
    assert out["stages"][0]["growth"] is None             # nothing before the first stage
    assert out["stages"][1]["growth"] == pytest.approx(25.0)
    assert out["companies"] == 3 and out["coverage"] == pytest.approx(1.0)


def test_aggregate_path_drops_only_the_stage_nobody_reports():
    caps = {"A": 100.0, "B": 100.0}
    stages = {"fy0": {"A": 5.0, "B": 5.0}, "ntm": {"A": 5.5, "B": 5.5}, "fy1": {"A": 6.0, "B": 6.0}}
    out = V.aggregate_path(caps, stages)                  # no last-year actuals at all
    assert [s["key"] for s in out["stages"]] == ["fy0", "ntm", "fy1"]


def test_aggregate_path_leaves_a_loss_blank_not_zero():
    caps = {"A": 100.0}
    out = V.aggregate_path(caps, {"fy_prev": {"A": -1.0}, "fy0": {"A": 2.0}, "ntm": {"A": 3.0}, "fy1": {"A": 4.0}})
    assert out["stages"][0]["pe"] is None
    assert out["stages"][1]["growth"] is None             # growth off a loss is not a percentage
    assert out["stages"][2]["growth"] == pytest.approx(50.0)


def test_scenario_grid_is_price_equals_multiple_times_eps():
    grid = V.scenario_grid(20.0, [-2.0, 0.0, 2.0], [-10.0, 0.0, 10.0])
    assert grid[1][1] == pytest.approx(0.0)               # nothing moves: no change
    assert grid[1][2] == pytest.approx(10.0)              # EPS +10% at an unchanged multiple
    assert grid[0][1] == pytest.approx(-10.0)             # 2 turns lower on 20x
    assert grid[2][2] == pytest.approx((22 / 20 * 1.1 - 1) * 100)
    assert V.scenario_grid(None, [0.0], [0.0]) == [[None]]
    assert V.scenario_grid(1.0, [-2.0], [0.0]) == [[None]]   # a negative multiple is not a price


def _fin(ticker, sub):
    return {"ticker": ticker, "sector": "Financials", "sub_sector": sub}


def test_assign_subgroups_reports_what_it_cannot_place():
    rows = [_fin("A", "Diversified Banks"), _fin("B", "Diversified Banks"), _fin("C", "Diversified Banks"),
            _fin("D", "Regional Banks"), _fin("E", "Multi-Sector Holdings"),
            {"ticker": "Z", "sector": "Energy", "sub_sector": "Oil & Gas"}]
    specs = [{"sector": "Financials", "key": "banks", "label": "Banks", "sub_industries": ["Diversified Banks"]},
             {"sector": "Financials", "key": "regional", "label": "Regional", "sub_industries": ["Regional Banks"]},
             {"sector": "Financials", "key": "ins", "label": "Insurance", "sub_industries": ["Reinsurance"]}]
    out = V.assign_subgroups(rows, specs, min_members=3)
    assert [g["key"] for g in out["groups"]] == ["banks"] and out["groups"][0]["tickers"] == ["A", "B", "C"]
    assert out["groups"][0]["parent"] == "Financials"
    assert out["too_small"] == [{"key": "regional", "label": "Regional", "companies": 1}]
    assert out["unmatched"] == ["Financials: Reinsurance"]            # configured, but no company carries it
    assert out["unassigned"] == [{"sector": "Financials", "sub_industry": "Multi-Sector Holdings", "tickers": ["E"]}]
    # Energy is not divided, so its sub-industry is not an unassigned remainder.


def test_a_sub_industry_in_two_groups_is_a_config_error():
    specs = [{"sector": "Financials", "key": "a", "label": "A", "sub_industries": ["Regional Banks"]},
             {"sector": "Financials", "key": "b", "label": "B", "sub_industries": ["Regional Banks"]}]
    with pytest.raises(ValueError, match="both"):
        V.assign_subgroups([], specs, min_members=1)


def test_the_shipped_subgroups_are_well_formed():
    from market_recap.config import load_config
    settings = load_config()["valuation"]
    specs = settings["subgroups"]
    assert settings["subgroup_min_members"] >= 1
    assert len({s["key"] for s in specs}) == len(specs)
    assert all(s["sub_industries"] and s["label"] for s in specs)
    V.assign_subgroups([], specs, settings["subgroup_min_members"])   # raises on a sub-industry claimed twice


def test_aggregates_draw_each_financials_group_beside_the_sector():
    import types
    from market_recap.config import load_config
    days = pd.bdate_range("2026-01-01", periods=V.MIN_HISTORY_SESSIONS + 60)
    subs = {"B1": "Diversified Banks", "B2": "Diversified Banks", "B3": "Diversified Banks",
            "I1": "Investment Banking & Brokerage", "I2": "Investment Banking & Brokerage", "I3": "Investment Banking & Brokerage",
            "BRK": "Multi-Sector Holdings"}
    rows = [{"ticker": t, "sector": "Financials", "sub_sector": sub, "indices": ["SPX"], "market_cap": 100.0, "price": 10.0,
             "eps_ntm": 1.1, "eps_fy0": 1.0, "eps_fy1": 1.2, "eps_fy_prev": 0.8} for t, sub in subs.items()]
    caps = {t: pd.Series(100.0, index=days) for t in subs}
    earn = {V.OPERATING: {t: pd.Series(10.0 if t.startswith("B") else 5.0, index=days) for t in subs},
            V.REPORTED: {t: pd.Series(5.0, index=days) for t in subs}}
    ctx = types.SimpleNamespace(indices=[types.SimpleNamespace(key="SPX", label="S&P 500")],
                                primary=types.SimpleNamespace(key="SPX"), config=load_config())
    out = panel._aggregates(ctx, rows, caps, earn, {})
    by_key = {s["key"]: s for s in out["series"]}
    assert by_key["Financials"]["kind"] == "sector" and by_key["Financials"]["companies"] == 7
    banks, brokers = by_key["fin-diversified-banks"], by_key["fin-investment-banks"]
    assert banks["kind"] == "subsector" and banks["parent"] == "Financials" and banks["companies"] == 3
    assert banks["stats"]["current"] == pytest.approx(10.0) and brokers["stats"]["current"] == pytest.approx(20.0)
    assert "fin-regional-banks" not in by_key                              # no regional bank in the data
    report = out["subgroups"]
    assert any("Regional Banks" in name for name in report["unmatched"])   # configured, carried by no company
    assert report["unassigned"] == [{"sector": "Financials", "sub_industry": "Multi-Sector Holdings", "tickers": ["BRK"]}]


# --- Tangible book, P / TBV and ROTCE ---------------------------------------------------
def _bank_facts(*, preferred=True, goodwill=True):
    """A calendar-year bank at 2026-09-30: a 10-K for 2025 and a 10-Q with nine
    months of 2026 and 2025, each line in the US-GAAP tag it is filed under."""
    def flow(tag, fy, ytd, ytd_prior):
        rows = [{"start": "2025-01-01", "end": "2025-12-31", "val": fy, "filed": "2026-02-20", "form": "10-K", "fp": "FY"},
                {"start": "2026-01-01", "end": "2026-09-30", "val": ytd, "filed": "2026-11-05", "form": "10-Q", "fp": "Q3"},
                {"start": "2025-01-01", "end": "2025-09-30", "val": ytd_prior, "filed": "2026-11-05", "form": "10-Q", "fp": "Q3"}]
        return {tag: {"units": {"USD": rows}}}

    def inst(tag, now, year_ago):
        return {tag: {"units": {"USD": [
            {"end": "2026-09-30", "val": now, "filed": "2026-11-05", "form": "10-Q", "fp": "Q3"},
            {"end": "2025-09-30", "val": year_ago, "filed": "2025-11-05", "form": "10-Q", "fp": "Q3"}]}}}

    gaap = {}
    gaap |= flow("Revenues", 120.0, 100.0, 85.0)
    gaap |= flow("NetIncomeLoss", 40.0, 36.0, 28.0)                         # TTM 48
    gaap |= flow("NetIncomeLossAvailableToCommonStockholdersBasic", 37.0, 33.0, 25.0)   # TTM 45
    gaap |= inst("StockholdersEquity", 400.0, 360.0)
    if goodwill:
        gaap |= inst("Goodwill", 60.0, 60.0)
        gaap |= inst("IntangibleAssetsNetExcludingGoodwill", 20.0, 24.0)
    if preferred:
        gaap |= inst("PreferredStockValue", 30.0, 30.0)
    return {"facts": {"us-gaap": gaap}}


def test_trailing_snapshot_reads_the_book_lines_and_income_to_common():
    snapshot = sec.trailing_snapshot(_bank_facts())
    assert snapshot["balance"]["goodwill"] == 60.0 and snapshot["balance"]["intangibles"] == 20.0
    assert snapshot["balance"]["preferred"] == 30.0 and snapshot["balance_prior"]["intangibles"] == 24.0
    assert snapshot["ttm"]["income_to_common"] == pytest.approx(45.0)


def test_tangible_book_takes_out_preferred_goodwill_and_intangibles():
    book = V.tangible_book(sec.trailing_snapshot(_bank_facts())["balance"])
    assert book == {"value": 400.0 - 30.0 - 60.0 - 20.0, "assumed_none": []}
    assert V.ptbv(580.0, sec.trailing_snapshot(_bank_facts())["balance"]) == pytest.approx(580.0 / 290.0)


def test_rotce_is_income_to_common_over_average_tangible_common_equity():
    snapshot = sec.trailing_snapshot(_bank_facts())
    prior_tbv = 360.0 - 30.0 - 60.0 - 24.0                                  # 246
    assert V.rotce(snapshot) == pytest.approx(45.0 / ((290.0 + prior_tbv) / 2) * 100)


def test_an_untagged_preferred_is_taken_as_none_and_said_so():
    book = V.tangible_book(sec.trailing_snapshot(_bank_facts(preferred=False))["balance"])
    assert book["value"] == 400.0 - 60.0 - 20.0 and book["assumed_none"] == ["preferred"]


def test_no_goodwill_and_no_intangibles_tagged_is_not_a_tangible_book():
    balance = sec.trailing_snapshot(_bank_facts(goodwill=False))["balance"]
    assert V.tangible_book(balance) is None and V.ptbv(500.0, balance) is None
    assert V.tangible_book({"equity": 100.0, "goodwill": -5.0}) is None     # a negative asset is a filing error


def test_a_negative_tangible_book_has_no_multiple_and_no_return():
    balance = {"equity": 50.0, "goodwill": 80.0, "intangibles": 0.0}
    assert V.tangible_book(balance)["value"] == -30.0
    assert V.ptbv(100.0, balance) is None
    assert V.rotce({"balance": balance, "balance_prior": {}, "ttm": {"income_to_common": 10.0}}) is None


def test_rotce_needs_income_to_common_not_net_income():
    snapshot = {"balance": {"equity": 100.0, "goodwill": 10.0}, "balance_prior": {}, "ttm": {"net_income": 20.0}}
    assert V.rotce(snapshot) is None


def test_group_book_totals_need_coverage_and_skip_members_without_positive_book():
    members = [{"market_cap": 100.0, "tbv": 50.0, "tbv_avg": 48.0, "income_common": 6.0},
               {"market_cap": 100.0, "tbv": 100.0, "tbv_avg": 100.0, "income_common": 10.0},
               {"market_cap": 40.0, "tbv": -5.0, "tbv_avg": None, "income_common": 1.0}]
    out = V.aggregate_book(members)
    assert out["ptbv"] == pytest.approx(200.0 / 150.0) and out["ptbv_coverage"] == pytest.approx(200 / 240)
    assert out["rotce"] == pytest.approx(16.0 / 148.0 * 100)
    # A group whose positive-book members hold under 80% of its cap draws nothing.
    assert V.aggregate_book(members[:1] + [dict(members[2], market_cap=400.0)]) is None
    assert V.aggregate_book([]) is None


# --- P / tangible book against its own history ---------------------------------------------
def _annual_bank_facts():
    """Three 10-Ks of a bank with 100m diluted shares: tangible common book
    is 830, 930 and 1,030 at the three year ends (equity less 50 preferred,
    100 goodwill and 20 intangibles), each filed on the date below."""
    def annual(tag, values, unit="USD", instant=False):
        rows = []
        for year, (val, filed) in zip((2023, 2024, 2025), values):
            row = {"end": f"{year}-12-31", "val": val, "filed": filed, "form": "10-K", "fp": "FY"}
            if not instant:
                row["start"] = f"{year}-01-01"
            rows.append(row)
        return {tag: {"units": {unit: rows}}}

    filed = ["2024-02-20", "2025-02-20", "2026-02-20"]
    pair = lambda *vals: list(zip(vals, filed))  # noqa: E731
    gaap = {}
    gaap |= annual("EarningsPerShareDiluted", pair(2.0, 2.5, 3.0), unit="USD/shares")
    gaap |= annual("WeightedAverageNumberOfDilutedSharesOutstanding", pair(1e8, 1e8, 1e8), unit="shares")
    gaap |= annual("NetIncomeLoss", pair(2e8, 2.5e8, 3e8))
    gaap |= annual("Revenues", pair(9e8, 9e8, 9e8))
    gaap |= annual("StockholdersEquity", pair(1000e6, 1100e6, 1200e6), instant=True)
    gaap |= annual("Goodwill", pair(100e6, 100e6, 100e6), instant=True)
    gaap |= annual("IntangibleAssetsNetExcludingGoodwill", pair(20e6, 20e6, 20e6), instant=True)
    gaap |= annual("PreferredStockValue", pair(50e6, 50e6, 50e6), instant=True)
    return {"facts": {"us-gaap": gaap}}


def _sessions(start, end, price):
    return pd.Series(price, index=pd.bdate_range(start, end))


def test_eps_history_carries_the_balance_sheet_as_filed_that_day():
    history = sec.eps_history(_annual_bank_facts())
    assert [q["filed"] for q in history] == ["2024-02-20", "2025-02-20", "2026-02-20"]
    assert history[0]["book"] == {"equity": 1000e6, "goodwill": 100e6, "intangibles": 20e6, "preferred": 50e6}


def test_tbv_steps_are_book_per_share_on_todays_basis():
    history = sec.eps_history(_annual_bank_facts())
    assert [round(v, 2) for _, _, v in V.tbv_steps(history, None)] == [8.30, 9.30, 10.30]
    split = pd.Series([2.0], index=[pd.Timestamp("2025-06-01")])      # 2:1 after the second filing
    halved = [round(v, 3) for _, _, v in V.tbv_steps(history, split)]
    assert halved == [4.15, 4.65, 10.30]                              # earlier years restated, the latest not


def test_ptbv_series_divides_by_the_book_public_that_day_not_the_next_one():
    steps = V.tbv_steps(sec.eps_history(_annual_bank_facts()), None)
    prices = _sessions("2024-01-02", "2026-06-30", 20.0)
    ptbv = V.ptbv_series(prices, steps)
    assert pd.isna(ptbv[pd.Timestamp("2024-02-20")])                  # filed that evening: not yet in force
    assert ptbv[pd.Timestamp("2024-02-21")] == pytest.approx(20.0 / 8.30)
    assert ptbv[pd.Timestamp("2025-03-03")] == pytest.approx(20.0 / 9.30)
    assert ptbv.iloc[-1] == pytest.approx(20.0 / 10.30)


def test_a_tangible_book_far_above_the_price_is_a_filing_error():
    steps = [("2024-02-20", "2023-12-31", 500.0)]
    prices = _sessions("2024-03-01", "2024-03-29", 10.0)
    assert V.ptbv_series(prices, steps).isna().all()                  # 50x book per share on a 10 share price


def test_a_quarter_with_no_tangible_book_leaves_the_earlier_figure_standing():
    history = sec.eps_history(_annual_bank_facts())
    history[1]["book"] = {"equity": 1100e6, "goodwill": None, "intangibles": None, "preferred": None}
    assert [round(v, 2) for _, _, v in V.tbv_steps(history, None)] == [8.30, 10.30]


def test_aggregates_carry_a_ptbv_history_beside_the_pe_history():
    import types
    from market_recap.config import load_config
    days = pd.bdate_range("2024-01-01", periods=V.MIN_HISTORY_SESSIONS + 60)
    tickers = ["B1", "B2", "B3"]
    rows = [{"ticker": t, "sector": "Financials", "sub_sector": "Diversified Banks", "indices": ["SPX"], "market_cap": 100.0,
             "price": 10.0, "eps_ntm": None} for t in tickers]
    caps = {t: pd.Series(150.0, index=days) for t in tickers}
    earn = {b: {t: pd.Series(15.0, index=days) for t in tickers} for b in (V.OPERATING, V.REPORTED)}
    book = {t: pd.Series(100.0, index=days) for t in tickers}
    book["B3"] = pd.Series(float("nan"), index=days)                     # no tangible book for one of three
    ctx = types.SimpleNamespace(indices=[types.SimpleNamespace(key="SPX", label="S&P 500")],
                                primary=types.SimpleNamespace(key="SPX"), config=load_config())
    thin = {s["key"]: s for s in panel._aggregates(ctx, rows, caps, earn, {}, book)["series"]}
    assert "ptbv" not in thin["Financials"]                              # 2 of 3 equal caps: 67%, under the 80% floor
    book["B3"] = pd.Series(100.0, index=days)
    full = {s["key"]: s for s in panel._aggregates(ctx, rows, caps, earn, {}, book)["series"]}
    assert full["Financials"]["stats_ptbv"]["current"] == pytest.approx(1.5)      # 450 cap over 300 book
    assert full["fin-diversified-banks"]["stats_ptbv"]["current"] == pytest.approx(1.5)
    assert len(full["Financials"]["ptbv"]) == len(full["Financials"]["pe"]) and full["Financials"]["coverage_ptbv"] == 1.0
