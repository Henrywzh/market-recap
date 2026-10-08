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


def test_a_split_lookup_gives_the_same_factor_as_filtering_the_series():
    import numpy as np
    days = pd.date_range("2016-01-04", "2026-10-07", freq="B")
    splits = pd.Series(np.nan, index=days)
    splits[pd.Timestamp("2020-08-31")] = 4.0
    splits[pd.Timestamp("2024-06-10")] = 10.0
    splits[pd.Timestamp("2025-01-02")] = 1 / 3
    after = V.split_lookup(splits)
    for date in ("2015-01-01", "2020-08-28", "2020-08-31", "2022-03-01", "2024-06-10", "2025-01-02", "2026-10-07"):
        ratios = splits.dropna()
        assert after(date) == float(ratios[ratios.index > pd.Timestamp(date)].prod()), date
        assert V.split_factor_after(splits, date) == after(date)
    assert V.split_lookup(None)("2020-01-01") == 1.0
    assert V.split_lookup(pd.Series(np.nan, index=days))("2020-01-01") == 1.0
