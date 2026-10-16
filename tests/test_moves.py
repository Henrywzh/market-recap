"""MOVES: a session's move in the stock's own terms, never measured against itself."""

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import moves as M


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
                          "range_quantiles": [0.05, 0.5, 0.95]},
                "universe": {"sectors": {"Information Technology": "XLK"}}, "watchlist": []},
        members={"SPX": members}, closes=closes, prices=closes,
        etf_closes=pd.DataFrame({"SPY": market, "XLK": tech}, index=days),
        as_of=days[-1].strftime("%Y-%m-%d"), history_period="3y",
        log=SimpleNamespace(add=logged.append))
    monkeypatch.setattr(panel.yahoo, "fetch_ohlcv_cache", lambda period: {"open": closes * 0.99, "volume": closes * 0 + 1e6})
    calendar = {"recent": {"session": ctx.as_of, "earnings_reacted": [{"symbol": "BBB"}]}}
    out = panel.build(ctx, inputs={"catalysts": calendar})
    rows = {r["ticker"]: r for r in out["rows"]}
    assert set(rows) == {"AAA", "BBB"} and out["skipped"] == ["LATE"]
    assert out["unusual"] == ["BBB"] and rows["BBB"]["reported"] is True and rows["AAA"]["reported"] is False
    assert rows["BBB"]["gap_pct"] is not None and rows["BBB"]["volume_ratio"] == 1.0
    stale = panel.build(ctx, inputs={"catalysts": {"recent": {"session": "2020-01-01", "earnings_reacted": [{"symbol": "BBB"}]}}})
    assert all(r["reported"] is None for r in stale["rows"])
