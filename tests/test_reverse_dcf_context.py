"""FY revenue consensus retains its horizon, units and actual observation time."""
from copy import deepcopy

import pytest

from market_recap.compute.reverse_dcf_context import revenue_context


def trend():
    return {"0y": {"end": "2027-06-30", "revenue": 102, "revenue_year_ago": 100,
                    "revenue_low": 101, "revenue_high": 104, "revenue_analysts": 22,
                    "eps": 8, "analysts": 99},
            "+1y": {"end": "2028-06-30", "revenue": 108, "revenue_year_ago": 102,
                     "revenue_low": 105, "revenue_high": 110, "revenue_analysts": 20}}


def test_uses_revenue_not_eps_and_retains_two_dated_fiscal_periods():
    result = revenue_context(trend(), "2026-10-17T21:11:43Z")
    assert result["observed_at"] == "2026-10-17T21:11:43Z"
    assert result["observed_market_date"] == "2026-10-17"
    assert len(result["periods"]) == 2
    first = result["periods"][0]
    assert first["growth_pct"] == pytest.approx(2)
    assert first["growth_low_pct"] == pytest.approx(1)
    assert first["growth_high_pct"] == pytest.approx(4)
    assert first["analysts"] == 22
    assert result["periods"][1]["growth_pct"] == pytest.approx((108 / 102 - 1) * 100)


@pytest.mark.parametrize("stamp", [None, "", "bad", "2026-10-17", 123])
def test_missing_or_unzoned_observation_time_is_not_invented(stamp):
    assert revenue_context(trend(), stamp) is None


def test_market_date_uses_new_york_not_utc():
    assert revenue_context(trend(), "2026-10-17T00:30:00Z")["observed_market_date"] == "2026-10-16"


def test_missing_revenue_does_not_fall_back_to_eps_or_other_periods():
    assert revenue_context({"0y": {"end": "2027-06-30", "eps": 8}}, "2026-10-17T00:30:00Z") is None


@pytest.mark.parametrize("base", [None, 0, -1, float("nan"), True])
def test_bad_baseline_leaves_growth_missing_without_discarding_revenue(base):
    value = trend(); value["0y"]["revenue_year_ago"] = base
    result = revenue_context(value, "2026-10-17T00:30:00Z")["periods"][0]
    assert result["revenue"] == 102
    assert result["growth_pct"] is None
    assert result["growth_low_pct"] is None


def test_inconsistent_range_is_withheld_but_mean_remains():
    value = trend(); value["0y"]["revenue_low"] = 110
    result = revenue_context(value, "2026-10-17T00:30:00Z")["periods"][0]
    assert result["growth_pct"] == pytest.approx(2)
    assert result["low"] is None and result["high"] is None
    assert result["range_issue"]


def test_zero_revenue_and_missing_revenue_analyst_count_are_not_replaced():
    value = trend(); value["0y"].update(revenue=0, revenue_low=0, revenue_high=0, revenue_analysts=None)
    original = deepcopy(value)
    result = revenue_context(value, "2026-10-17T00:30:00Z")["periods"][0]
    assert result["growth_pct"] == -100
    assert result["analysts"] is None
    assert value == original
