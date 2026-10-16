"""MOVES: a session's move in the stock's own terms, never measured against itself."""

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import moves as M

FACTORS = {"reported": 0.87, "down_repeat": 1.12, "down_vix_high": 1.14, "down_no_report": 1.11}


def _walk(n, seed, scale=0.01):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0, scale, n), index=pd.bdate_range("2020-01-01", periods=n))


def test_decompose_splits_the_last_return_with_betas_from_before_it():
    market, sector_extra, noise = _walk(400, 1), _walk(400, 2), _walk(400, 3, 0.005)
    sector = market + sector_extra
    stock = 1.5 * market + 0.5 * sector_extra + noise
    stock.iloc[-1] = -0.08  # a shock on the last day must not move the betas or sigma
    out = M.decompose(stock, market, sector, beta_sessions=252, vol_sessions=60)
    assert out["beta_market"] == pytest.approx(1.5, abs=0.1) and out["beta_sector"] == pytest.approx(0.5, abs=0.1)
    assert out["market"] + out["sector"] + out["own"] == pytest.approx(-0.08)
    assert out["sigma"] == pytest.approx(stock.iloc[-61:-1].std())
    assert out["z_own"] < -10  # the own part is large against the residual noise


def test_without_a_sector_fund_only_the_market_is_taken_out():
    market, noise = _walk(300, 4), _walk(300, 5, 0.004)
    out = M.decompose(market + noise, market, None, beta_sessions=252, vol_sessions=60)
    assert out["sector"] == 0.0 and out["beta_sector"] is None
    assert M.decompose(market.iloc[:30], market.iloc[:30], None, beta_sessions=252, vol_sessions=60) is None


def test_forward_range_is_centred_and_scales_with_todays_volatility():
    returns = _walk(1600, 6)
    returns.iloc[:800] += 0.004  # an early rally must not become an expected drift
    closes = 100 * (1 + returns).cumprod()
    calm = M.forward_range(closes, horizon=5, history_sessions=1260, quantiles=(0.05, 0.5, 0.95))
    wild = returns.copy()
    wild.iloc[-20:] *= 4
    loud = M.forward_range(100 * (1 + wild).cumprod(), horizon=5, history_sessions=1260, quantiles=(0.05, 0.5, 0.95))
    assert abs(calm["bands"][1]["pct"]) < 0.5
    assert loud["sigma_pct"] > 2 * calm["sigma_pct"]
    assert loud["bands"][2]["pct"] - loud["bands"][0]["pct"] > 2 * (calm["bands"][2]["pct"] - calm["bands"][0]["pct"])
    assert M.forward_range(closes.iloc[:200], horizon=5, history_sessions=1260, quantiles=(0.5,)) is None


def test_session_split_and_volume_ratio():
    days = pd.bdate_range("2026-01-05", periods=3)
    prices, opens = pd.Series([100.0, 102.0, 99.0], index=days), pd.Series([99.0, 101.0, 97.0], index=days)
    split = M.session_split(prices, opens)
    assert split["gap"] == pytest.approx(97 / 102 - 1) and split["intraday"] == pytest.approx(99 / 97 - 1)
    assert M.session_split(prices, opens.iloc[:2]) is None  # no open for the last close: no split
    volume = pd.Series([100.0] * 20 + [300.0])
    assert M.volume_ratio(volume, 20) == 3.0 and M.volume_ratio(volume.iloc[:5], 20) is None


def test_panel_measures_every_name_and_flags_reporters_only_for_this_session(monkeypatch):
    from types import SimpleNamespace

    from market_recap.panels import moves as panel

    days = _walk(700, 0).index
    market = 100 * (1 + _walk(700, 7)).cumprod()
    tech = market * (1 + _walk(700, 8, 0.004)).cumprod()
    calm = market * (1 + _walk(700, 9, 0.004)).cumprod()
    shock = calm.copy()
    shock.iloc[-1] = shock.iloc[-2] * 0.85
    closes = pd.DataFrame({"AAA": calm, "BBB": shock, "LATE": calm.iloc[:-1]}, index=days)
    members = pd.DataFrame([{"yahoo_symbol": s, "name": s, "sector": "Information Technology", "sub_sector": "x"}
                            for s in ("AAA", "BBB", "LATE")])
    logged = []
    ctx = SimpleNamespace(
        config={"moves": {"market": "SPY", "threshold_sigma": 2.0, "vol_sessions": 60, "beta_sessions": 252,
                          "volume_sessions": 20, "range_sessions": 5, "range_history_sessions": 1260,
                          "range_quantiles": [0.05, 0.5, 0.95], "vix": "^VIX", "vix_median_sessions": 252,
                          "repeat_sessions": 10, "states_file": "no/such/states.json",
                          "range_factors": FACTORS},
                "universe": {"sectors": {"Information Technology": "XLK"}}, "watchlist": []},
        members={"SPX": members}, closes=closes, prices=closes,
        etf_closes=pd.DataFrame({"SPY": market, "XLK": tech}, index=days),
        as_of=days[-1].strftime("%Y-%m-%d"), history_period="3y",
        log=SimpleNamespace(add=logged.append))
    vix = pd.Series(20.0, index=days)
    vix.iloc[-1] = 30.0  # high against its past year
    monkeypatch.setattr(panel.yahoo, "fetch_closes", lambda symbols, period: pd.DataFrame({"^VIX": vix}))
    monkeypatch.setattr(panel.yahoo, "fetch_ohlcv_cache", lambda period: {"open": closes * 0.99, "volume": closes * 0 + 1e6})
    calendar = {"recent": {"session": ctx.as_of, "earnings_reacted": [{"symbol": "BBB"}]}}
    out = panel.build(ctx, inputs={"catalysts": calendar})
    rows = {r["ticker"]: r for r in out["rows"]}
    assert set(rows) == {"AAA", "BBB"} and out["skipped"] == ["LATE"]
    assert out["unusual"] == ["BBB"] and rows["BBB"]["reported"] is True and rows["AAA"]["reported"] is False
    assert rows["BBB"]["gap_pct"] is not None and rows["BBB"]["volume_ratio"] == 1.0
    # A reported shock gets the report factor and keeps its uncalibrated band; a quiet name is untouched.
    shock = rows["BBB"]
    assert shock["direction"] == "down" and shock["tags"]["reported"] is True and shock["tags"]["vix_high"] is True
    assert shock["range_factor"] == FACTORS["reported"] and shock["range_raw"]["bands"][2]["pct"] * 0.87 == pytest.approx(shock["range"]["bands"][2]["pct"], abs=0.01)
    assert rows["AAA"]["direction"] is None and rows["AAA"]["tags"] is None and rows["AAA"]["range_factor"] is None
    assert out["move_states"] is None  # no table file: the card omits it, the build does not fail
    stale = panel.build(ctx, inputs={"catalysts": {"recent": {"session": "2020-01-01", "earnings_reacted": [{"symbol": "BBB"}]}}})
    assert all(r["reported"] is None for r in stale["rows"])


def test_history_of_z_own_is_measured_with_what_was_known_before_each_day():
    market, noise = _walk(400, 11), _walk(400, 12, 0.01)
    stock = market + noise
    out = M.decompose(stock, market, None, beta_sessions=252, vol_sessions=60, history=10)
    assert len(out["z_own_history"]) == 10
    for back in (1, 4, 10):  # the same day measured as the last one of a shorter series
        earlier = M.decompose(stock.iloc[:-back], market.iloc[:-back], None, beta_sessions=252, vol_sessions=60)
        assert out["z_own_history"][back - 1] == pytest.approx(earlier["z_own"])
    short = M.decompose(stock.iloc[:70], market.iloc[:70], None, beta_sessions=252, vol_sessions=60, history=10)
    assert short["z_own_history"][-1] is None and short["z_own_history"][0] is not None  # too early to measure


def test_direction_and_repeat_need_a_same_sign_shock_in_the_sessions_before():
    assert [M.shock_direction(z, 2.0) for z in (-2.0, -1.9, 2.0, 3.1, None, float("nan"))] == ["down", None, "up", "up", None, None]
    assert M.repeat_shock([0.3, -2.4, 1.0], "down", 2.0) is True
    assert M.repeat_shock([0.3, 2.4, 1.0], "down", 2.0) is False  # an opposite shock is not a repeat
    assert M.repeat_shock([None, None], "down", 2.0) is None and M.repeat_shock(None, "up", 2.0) is None


def test_shock_tags_gap_led_vix_and_unknowns():
    row = {"gap_pct": -6.0, "intraday_pct": -2.0, "reported": False, "above_200d": True}
    tags = M.shock_tags(row, direction="down", history=[-3.0, 0.1], threshold=2.0, vix_high=True, market_above_200d=False)
    assert tags == {"direction": "down", "reported": False, "gap_led": True, "repeat": True, "vix_high": True,
                    "stock_above_200d": True, "market_above_200d": False}
    quiet = M.shock_tags({"gap_pct": -1.0, "intraday_pct": -2.0, "reported": None, "above_200d": None}, direction="down",
                         history=[], threshold=2.0, vix_high=None, market_above_200d=None)
    assert quiet["gap_led"] is False and quiet["repeat"] is None and quiet["reported"] is None and quiet["vix_high"] is None
    assert M.shock_tags({"reported": None, "above_200d": None}, direction="up", history=None, threshold=2.0,
                        vix_high=None, market_above_200d=None)["gap_led"] is None  # no opens: no gap tag


def test_range_factor_takes_the_first_that_applies_in_the_documented_order():
    def tags(**kw):
        return {"direction": "down", "reported": False, "repeat": False, "vix_high": False} | kw
    assert M.range_factor(tags(reported=True, repeat=True, vix_high=True), FACTORS)[0] == 0.87  # a report beats the rest
    assert M.range_factor(tags(repeat=True, vix_high=True), FACTORS)[0] == 1.12  # repeat before VIX
    assert M.range_factor(tags(vix_high=True), FACTORS)[0] == 1.14
    assert M.range_factor(tags(), FACTORS)[0] == 1.11
    assert M.range_factor(tags(reported=None), FACTORS) == (1.0, None)  # report status unknown: no "no report" claim
    assert M.range_factor(tags(direction="up", repeat=True, vix_high=True), FACTORS) == (1.0, None)  # only drops widen
    assert M.range_factor(tags(direction="up", reported=True), FACTORS)[0] == 0.87
    reason = M.range_factor(tags(repeat=True), FACTORS)[1]
    assert reason and "repeat" in reason


def test_calibrating_a_band_scales_percentages_and_reprices_around_the_last_close():
    band = {"horizon": 5, "sigma_pct": 3.0, "last": 100.0, "observations": 1000, "bands": [
        {"q": 0.05, "pct": -10.0, "price": 90.0}, {"q": 0.5, "pct": 0.5, "price": 100.5}, {"q": 0.95, "pct": 8.0, "price": 108.0}]}
    out = M.calibrate_range(band, 1.12)
    assert [b["pct"] for b in out["bands"]] == [-11.2, 0.56, 8.96]
    assert [b["price"] for b in out["bands"]] == [88.8, 100.56, 108.96]
    assert band["bands"][0]["pct"] == -10.0  # the input is untouched
    assert M.calibrate_range(band, 1.0) is band and M.calibrate_range(None, 1.12) is None


def test_frozen_research_table_ships_only_promoted_conditions_with_their_n():
    from market_recap.panels import moves as panel

    states = panel._move_states({"states_file": "config/move_states_v1.json"})
    assert panel._move_states({"states_file": "config/not_there.json"}) is None
    promoted = {"down": {"earnings", "composition", "repeat"}, "up": {"earnings", "vix_level", "stock_trend", "earnings x market_trend"}}
    for row in states["rows"]:
        assert row["condition"] is None or row["condition"] in promoted[row["direction"]]
        assert set(row["match"]) <= {"reported", "gap_led", "repeat", "vix_high", "stock_above_200d", "market_above_200d"}
        assert row["stats"]["h5"]["n"] >= 30 and row["stats"]["h5"]["lo"] <= row["stats"]["h5"]["mean"] <= row["stats"]["h5"]["hi"]
    assert {r["direction"] for r in states["rows"] if not r["match"]} == {"down", "up"}
    assert states["source"]["commit"] and states["horizons"] == [1, 5, 20]
