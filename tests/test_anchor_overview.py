import numpy as np
import pandas as pd
import pytest

from market_recap.compute import anchor as A
from market_recap.panels import overview


def _close(values, start="2020-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_ladder_steps_down_at_minus_eight_and_minus_twelve():
    assert A.ladder_multiplier(-0.05) == 1.0
    assert A.ladder_multiplier(-0.08) == 0.6   # the threshold is inclusive of the step down
    assert A.ladder_multiplier(-0.10) == 0.6
    assert A.ladder_multiplier(-0.12) == 0.3
    assert A.ladder_multiplier(-0.30) == 0.3


def test_friend_core_caps_at_half_below_the_200_day_average():
    rng = np.random.default_rng(3)
    up = _close(100 * np.exp(np.cumsum(0.0005 + rng.normal(0, 0.002, 400))))
    core = A.friend_core(up, lag=0)
    assert bool(core["trend_on"].iloc[-1]) is True
    assert core["target"].iloc[-1] == pytest.approx(1.0)       # calm market: vol-scaled to the 1.0 cap
    down = _close(list(up.to_numpy()) + list(up.iloc[-1] * np.exp(-0.004 * np.arange(1, 120))))
    core_down = A.friend_core(down, lag=0)
    assert bool(core_down["trend_on"].iloc[-1]) is False
    assert core_down["target"].iloc[-1] <= 0.5 + 1e-12


def test_the_signal_is_lagged_one_session():
    close = _close(100 * np.exp(0.001 * np.arange(300)))
    lagged, unlagged = A.friend_core(close), A.friend_core(close, lag=0)
    assert lagged["target"].iloc[-1] == pytest.approx(unlagged["target"].iloc[-2])


def test_copper_oil_gate_has_hysteresis():
    n = 600
    idx = pd.bdate_range("2020-01-01", periods=n)
    oil = pd.Series(50.0, index=idx)
    # Flat, then a slump (z well below -0.25), then a partial recovery that
    # stays between the bounds: the gate must stay off until z > +0.25.
    log_copper = np.concatenate([np.zeros(300) + np.random.default_rng(0).normal(0, 0.01, 300),
                                 np.linspace(0, -0.3, 100), np.full(200, -0.25)])
    copper = pd.Series(np.exp(log_copper) * 3.0, index=idx)
    gate = A.copper_oil(copper, oil, idx, lag=0)
    slump_end = gate["state"].iloc[399]
    assert slump_end == 0.0
    assert gate["cap"].iloc[399] == 0.5


def test_simulation_applies_the_ladder_from_the_prior_close():
    close = _close([100, 90, 80, 80, 80])
    path = A.simulate(close, pd.Series(1.0, index=close.index))
    # Day 2 (-10%) put the overlay 10% down, so day 3 runs at x0.6.
    assert path["ladder"].iloc[2] == pytest.approx(0.6)
    assert path["exposure"].iloc[1] == pytest.approx(1.0)


def test_ahead_keeps_releases_and_relevant_earnings_only():
    catalysts = {"events": [
        {"lane": "macro", "date": "2026-09-29", "title": "JOLTS", "importance": "medium", "event_type": "economic_release"},
        {"lane": "macro", "date": "2026-09-29", "title": "Speech", "importance": "medium", "event_type": "central_bank"},
        {"lane": "macro", "date": "2026-10-05", "title": "Too far", "importance": "high", "event_type": "economic_release"},
        {"lane": "single_name", "date": "2026-09-30", "symbol": "MU", "name": "Micron", "watchlist": False, "index_weights": {"SPX": 1.8}},
        {"lane": "single_name", "date": "2026-09-30", "symbol": "SMALL", "name": "Small Co", "watchlist": False},
        {"lane": "single_name", "date": "2026-09-30", "symbol": "WATCH", "name": "Watched", "watchlist": True},
    ]}
    items = overview.ahead(catalysts, top={"MU"}, as_of="2026-09-25")
    titles = [i.get("title") if i["kind"] == "macro" else i["symbol"] for i in items]
    assert titles == ["JOLTS", "MU", "WATCH"]


def test_stock_row_reads_returns_and_distance_from_the_52_week_high():
    close = _close(list(np.linspace(100, 120, 300)) + [114.0])
    row = overview.stock_row("S&P 500", "SPX", close)
    assert row["from_high_pct"] == pytest.approx(-5.0)
    assert row["1D"] == pytest.approx(-5.0)
    assert row["sessions_since_high"] == 1
    assert 2 <= len(row["spark"]) <= overview.SPARK_POINTS


def test_breadth_counts_up_and_down_names_and_new_highs():
    idx = pd.bdate_range("2025-01-01", periods=300)
    rising = np.linspace(50, 100, 300)
    closes = pd.DataFrame({
        "UP": rising,                                          # at a 52-week high
        "DOWN": rising[::-1],                                  # at a 52-week low
        "FLATUP": np.r_[np.full(299, 80.0), 81.0],             # up today only
    }, index=idx)
    out = overview.breadth(closes)
    assert out["1D"] == {"up": 2, "down": 1}
    assert out["1M"] == {"up": 2, "down": 1}
    assert (out["new_highs"], out["new_lows"]) == (2, 1)
    assert out["above_200d"] == pytest.approx(200 / 3, abs=0.1)


def test_rates_change_in_basis_points_and_spreads_show_in_bp():
    idx = pd.bdate_range("2026-08-01", periods=40)
    hy = pd.Series(np.r_[np.full(39, 3.00), 3.10], index=idx)       # FRED serves percent
    row = overview.rate_row("BAMLH0A0HYM2", "High yield OAS", "bp", hy)
    assert row["value"] == pytest.approx(310.0)
    assert row["change_1d_bp"] == pytest.approx(10.0)
    assert row["change_1m_bp"] == pytest.approx(10.0)


def test_risk_line_lists_only_core_series_past_their_line():
    risk = {"sections": [{"key": "credit", "horizon": "tactical", "tiles": [
        {"key": "hy_oas", "label": "HY OAS", "core": True, "breach": False, "value": 280, "unit": "bp"},
        {"key": "ccc_oas", "label": "CCC OAS", "core": False, "breach": True, "value": 1112, "unit": "bp"},
        {"key": "real_10y", "label": "10Y REAL", "core": True, "breach": True, "value": 2.6, "unit": "pct"},
    ]}]}
    line = overview.risk_line(risk)
    assert line["core"] == 2 and [p["label"] for p in line["past"]] == ["10Y REAL"]
