"""The calculations the whole page depends on agreeing about."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.config import load_config
from market_recap.compute import returns as R


@pytest.fixture
def prices() -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=1500)
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        {name: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(index)))) for name in "ABCD"},
        index=index,
    )


def test_period_return_refuses_a_window_it_cannot_measure(prices):
    """A short history must return None, never a shorter window relabelled."""
    assert R.period_return(prices["A"].head(50), 252) is None
    assert R.period_return(prices["A"], 252) is not None


def test_period_return_matches_a_hand_computed_value(prices):
    series = prices["A"]
    expected = (series.iloc[-1] / series.iloc[-22] - 1) * 100
    assert R.period_return(series, 21) == pytest.approx(expected)


def test_drawdown_counts_sessions_not_calendar_days():
    index = pd.bdate_range("2024-01-01", periods=10)
    series = pd.Series([10, 11, 12, 11, 10, 9, 9, 9, 9, 9], index=index, dtype=float)
    result = R.drawdown_from_high(series)
    assert result["drawdown_pct"] == pytest.approx(-25.0)
    assert result["trading_days_since_high"] == 7
    assert result["high_date"] == index[2].strftime("%Y-%m-%d")


def test_advance_decline_separates_unchanged_from_missing():
    index = pd.bdate_range("2024-01-01", periods=2)
    frame = pd.DataFrame(
        {"up": [1.0, 2.0], "down": [2.0, 1.0], "flat": [1.0, 1.0], "absent": [np.nan, np.nan]},
        index=index,
    )
    result = R.advance_decline(frame)
    assert (result["advancers"], result["decliners"], result["unchanged"]) == (1, 1, 1)
    assert result["ratio"] == pytest.approx(0.5)


def test_pct_above_moving_average_is_none_when_history_is_short(prices):
    assert R.pct_above_moving_average(prices.head(50), 200) is None
    value = R.pct_above_moving_average(prices, 200)
    assert 0.0 <= value <= 100.0


# Technical indicators are computed in the browser; see tests/js/ and
# tests/test_technicals_parity.py.


def test_ytd_return_uses_the_last_print_of_the_prior_year():
    index = pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02", "2026-03-02"])
    series = pd.Series([90.0, 100.0, 105.0, 110.0], index=index)
    assert R.ytd_return(series) == pytest.approx(10.0)


def test_cross_listing_premium_uses_the_declared_ratio():
    """A premium computed with a fitted ratio is zero by construction.

    The panel must use the depositary's published ratio, so a pair whose US
    line is priced exactly at parity shows zero and one at a genuine premium
    shows it.
    """
    from market_recap.panels import cross_listing

    index = pd.bdate_range("2026-07-10", periods=60)
    home = pd.Series(1_800_000.0, index=index)
    fx = pd.Series(1_350.0, index=index)
    parity = home / fx * 0.1  # 1 ADS = 1/10 share

    frame = pd.DataFrame({"us": parity, "home": home, "fx": fx})
    frame["premium_pct"] = (frame["us"] / (frame["home"] / frame["fx"] * 0.1) - 1) * 100
    assert frame["premium_pct"].abs().max() == pytest.approx(0.0, abs=1e-9)

    premium_frame = frame.copy()
    premium_frame["us"] = parity * 1.4
    premium_frame["premium_pct"] = (
        premium_frame["us"] / (premium_frame["home"] / premium_frame["fx"] * 0.1) - 1
    ) * 100
    assert premium_frame["premium_pct"].iloc[-1] == pytest.approx(40.0)

    diag = cross_listing._diagnostics(premium_frame, min_pairs=10)
    assert diag["sessions"] == 60


def test_cross_listing_verdict_flags_a_timing_dominated_series():
    """A premium whose daily swing exceeds its own level spread is noise."""
    from market_recap.panels import cross_listing

    # The threshold is the contract's, so the test cannot drift from the page.
    floor = float(load_config()["cross_listing_diagnostics"]["min_autocorrelation"])

    timing_noise = {"daily_change_sd_pp": 11.7, "level_sd_pp": 9.0, "autocorr_1d": 0.14}
    assert cross_listing._verdict(timing_noise, min_autocorrelation=floor)["daily_change_usable"] is False

    persistent = {"daily_change_sd_pp": 0.4, "level_sd_pp": 3.2, "autocorr_1d": 0.95}
    assert cross_listing._verdict(persistent, min_autocorrelation=floor)["daily_change_usable"] is True


def test_a_missing_session_is_not_stepped_over(prices):
    """Yahoo once served a session as an all-NaN row. Dropping it before
    counting back made the next day's "1D" a two-session move."""
    series = prices["A"].copy()
    series.iloc[-2] = np.nan
    assert R.period_return(series, 1) is None
    expected = (series.iloc[-1] / series.iloc[-3] - 1) * 100
    assert R.period_return(series, 2) == pytest.approx(expected)


def test_a_basket_return_does_not_depend_on_share_prices(prices):
    """Weighting by weight x price let a high-priced stock dominate its sector."""
    weights = pd.Series({"A": 50.0, "B": 30.0, "C": 15.0, "D": 5.0})
    base = R.basket_return(prices, weights, 21, min_weight_share=0.9)
    rescaled = prices.assign(D=prices["D"] * 40)  # D becomes a $4,000 stock
    assert R.basket_return(rescaled, weights, 21, min_weight_share=0.9) == pytest.approx(base)


def test_a_basket_return_is_buy_and_hold_of_todays_weights(prices):
    weights = pd.Series({"A": 50.0, "B": 30.0, "C": 15.0, "D": 5.0})
    first, last = prices.iloc[-22], prices.iloc[-1]
    shares = weights / last  # holdings that are worth today's weights today
    expected = ((shares * last).sum() / (shares * first).sum() - 1) * 100
    assert R.basket_return(prices, weights, 21, min_weight_share=0.9) == pytest.approx(expected)


def test_a_basket_missing_too_much_weight_is_not_reported(prices):
    weights = pd.Series({"A": 50.0, "B": 30.0, "C": 15.0, "D": 5.0})
    thin = prices.copy()
    thin.loc[thin.index[-1], "A"] = np.nan
    assert R.basket_return(thin, weights, 1, min_weight_share=0.9) is None
    small_gap = prices.copy()
    small_gap.loc[small_gap.index[-1], "D"] = np.nan
    without_d = R.basket_return(prices[["A", "B", "C"]], weights[["A", "B", "C"]], 1, min_weight_share=0.9)
    assert R.basket_return(small_gap, weights, 1, min_weight_share=0.9) == pytest.approx(without_d)


def test_period_changes_match_by_date_across_a_month_never_published():
    """FRED has no October 2025 CPI; counting rows compared Aug 2026 with Jul 2025."""
    from market_recap.compute import periods
    months = pd.date_range("2025-01-01", "2026-08-01", freq="MS").drop(pd.Timestamp("2025-10-01"))
    series = pd.Series(range(100, 100 + len(months)), index=months, dtype=float)
    yoy = periods.transform(series, "yoy")
    assert yoy["2026-08-01"] == pytest.approx((series["2026-08-01"] / series["2025-08-01"] - 1) * 100)
    assert pd.isna(periods.transform(series, "mom")["2025-11-01"])   # its prior month was never published


def test_pct_above_moving_average_survives_one_missing_session(prices):
    # A session the feed missed for every name must not blank the reading.
    gapped = prices.copy()
    gapped.iloc[-30] = float("nan")
    assert R.pct_above_moving_average(gapped, 200) is not None
