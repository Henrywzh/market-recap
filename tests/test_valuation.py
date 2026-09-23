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
