import numpy as np
import pandas as pd
import pytest

from market_recap.compute import sentiment as S


def _series(values, start="2024-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_score_is_the_normal_cdf_of_the_trailing_z_and_flips_for_fear():
    rng = np.random.default_rng(0)
    base = list(rng.normal(0, 1, 300))
    high = _series(base + [5.0])
    greed = S.score(high, fear_when_high=False)
    fear = S.score(high, fear_when_high=True)
    assert greed.iloc[-1] > 99 and fear.iloc[-1] < 1
    assert greed.iloc[-1] + fear.iloc[-1] == pytest.approx(100)
    # Nothing is scored before the minimum history.
    assert greed.index[0] >= high.index[S.MIN_PERIODS - 1]


def test_rating_bands_follow_cnn():
    assert [S.rating(v) for v in (10, 30, 50, 60, 90)] == ["EXTREME FEAR", "FEAR", "NEUTRAL", "GREED", "EXTREME GREED"]
    assert S.rating(None) is None


def test_strength_nets_new_highs_against_new_lows():
    idx = pd.bdate_range("2024-01-01", periods=300)
    up = np.linspace(50, 100, 300)
    closes = pd.DataFrame({"A": up, "B": up, "C": up[::-1], "D": np.full(300, 10.0) + np.sin(np.arange(300))}, index=idx)
    # A and B at highs, C at a low, D in between: (2 - 1) / 4.
    assert S.strength(closes).iloc[-1] == pytest.approx(25.0)


def test_mcclellan_summation_rises_when_breadth_improves():
    idx = pd.bdate_range("2024-01-01", periods=80)
    # Three of ten names rise for 40 sessions, then eight of ten.
    ups = [3] * 40 + [8] * 40
    steps = np.array([[1.01 if i < n else 0.99 for i in range(10)] for n in ups])
    closes = pd.DataFrame(np.cumprod(steps, axis=0), index=idx, columns=[f"S{i}" for i in range(10)])
    summation = S.mcclellan_summation(closes)
    assert summation.iloc[-1] > summation.iloc[40]


def test_gauge_needs_six_components_and_reports_each():
    idx = pd.bdate_range("2023-01-02", periods=400)
    rng = np.random.default_rng(1)
    raw = {key: pd.Series(rng.normal(0, 1, 400).cumsum(), index=idx) for key, _, _ in S.COMPONENTS}
    out = S.gauge(raw, idx)
    assert 0 <= out["score"] <= 100 and out["components_counted"] == 7
    assert [c["key"] for c in out["components"]] == [k for k, _, _ in S.COMPONENTS]
    five = {k: v for k, v in list(raw.items())[:5]}
    assert S.gauge(five, idx)["score"] is None


def test_junk_spread_is_hy_less_ig_in_bp():
    idx = pd.bdate_range("2026-01-01", periods=3)
    assert S.junk_spread(pd.Series([3.0, 3.1, 3.2], index=idx), pd.Series([0.8, 0.8, 0.9], index=idx)).iloc[-1] == pytest.approx(230.0)


def test_a_component_too_short_to_score_drops_out_instead_of_failing_the_gauge():
    idx = pd.bdate_range("2023-01-02", periods=400)
    rng = np.random.default_rng(2)
    raw = {key: pd.Series(rng.normal(0, 1, 400).cumsum(), index=idx) for key, _, _ in S.COMPONENTS}
    raw["put_call"] = raw["put_call"].tail(60)   # a cold cache: fewer than MIN_PERIODS sessions
    out = S.gauge(raw, idx)
    assert out["score"] is not None and out["components_counted"] == 6
    assert next(c for c in out["components"] if c["key"] == "put_call")["score"] is None
