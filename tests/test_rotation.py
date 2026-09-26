import numpy as np
import pandas as pd
import pytest

from market_recap.compute import rotation as R


def _closes(values: dict[str, list[float]]) -> pd.DataFrame:
    days = pd.bdate_range("2026-01-05", periods=len(next(iter(values.values()))))
    return pd.DataFrame(values, index=days, dtype=float)


def test_cap_basket_is_buy_and_hold_at_todays_units():
    closes = _closes({"A": [10, 11, 12], "B": [20, 20, 18]})
    held = R.units(closes, pd.Series({"A": 60.0, "B": 40.0}))
    level = R.basket(closes, held)
    value = closes.mul(held).sum(axis=1)
    assert level.iloc[-1] == pytest.approx(value.iloc[-1] / value.iloc[0])
    # Today's weights are the ones given.
    today = closes.iloc[-1] * held
    assert (today / today.sum())["A"] == pytest.approx(0.6)


def test_equal_basket_averages_daily_returns():
    closes = _closes({"A": [10, 11], "B": [10, 9]})
    assert R.basket(closes, None).iloc[-1] == pytest.approx(1.0)


def test_a_listing_mid_window_does_not_jump_the_level():
    closes = _closes({"A": [10, 10, 10], "B": [np.nan, 50, 55]})
    held = R.units(closes, pd.Series({"A": 50.0, "B": 50.0}))
    level = R.basket(closes, held)
    assert level.iloc[1] == pytest.approx(1.0)
    assert level.iloc[2] > 1.0


def test_thin_rows_are_not_sessions():
    closes = _closes({"A": [10, np.nan, 11], "B": [10, np.nan, 11], "C": [10, 10.5, 11]})
    kept = R.sessions(closes)
    assert len(kept) == 2
    assert R.basket(kept, None).iloc[-1] == pytest.approx(1.1)


def test_contributions_add_up_to_the_groups_excess():
    rng = np.random.default_rng(0)
    paths = 100 * np.cumprod(1 + rng.normal(0, 0.01, size=(40, 6)), axis=0)
    closes = pd.DataFrame(paths, index=pd.bdate_range("2026-01-05", periods=40), columns=list("ABCDEF"))
    held = R.units(closes, pd.Series([30, 20, 15, 15, 10, 10], index=closes.columns, dtype=float))
    bench = R.basket(closes, held)
    group = ["A", "C", "E"]
    level = R.basket(closes[group], held[group])
    n = 21
    base = R.window_return(bench, n)
    excess = R.window_return(level, n) - base
    weights = R.start_weights(closes[group], held[group], n)
    moves = R.member_returns(closes[group], n)
    assert float((weights * (moves - base)).sum()) == pytest.approx(excess)


def test_rrg_is_neutral_for_a_group_that_tracks_the_index():
    days = pd.bdate_range("2025-01-06", periods=200)
    bench = pd.Series(np.linspace(1, 1.3, 200), index=days)
    wheel = R.rrg(bench * 1.0, bench)
    assert not wheel.empty
    assert wheel["ratio"].round(6).eq(100).all()
    assert wheel["momentum"].round(6).eq(100).all()


def test_rrg_weeks_end_on_their_last_session():
    days = pd.bdate_range("2025-01-06", periods=120)
    bench = pd.Series(1.0, index=days)
    group = pd.Series(np.linspace(1, 1.2, 120), index=days)
    wheel = R.rrg(group, bench)
    assert wheel["date"].iloc[-1] == days[-1]
    # A steadily outperforming group sits right of centre.
    assert wheel["ratio"].iloc[-1] > 100


@pytest.mark.parametrize("ratio,momentum,expected", [
    (101, 101, "leading"), (101, 99, "weakening"), (99, 99, "lagging"), (99, 101, "improving"), (None, 100, None),
])
def test_quadrants(ratio, momentum, expected):
    assert R.quadrant(ratio, momentum) == expected
