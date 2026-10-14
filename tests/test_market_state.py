"""MARKET STATE: the readings and the state statistics, on series whose answer is known."""

import json

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import market_state as M
from market_recap.config import load_config
from market_recap.panels import market_state as P

SECTORS = {"Information Technology": "XLK", "Financials": "XLF", "Energy": "XLE"}


def frame(n=700, seed=2, start="2018-01-02"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    cols = ["SPY", "RSP", "IWM", "XLK", "XLF", "XLE", "^VIX"]
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, (n, len(cols))), axis=0)), index=idx, columns=cols)
    closes["^VIX"] = 15 + 5 * np.abs(np.sin(np.arange(n) / 40))
    return closes


def feats(closes, **over):
    args = dict(market="SPY", equal_weight="RSP", small_caps="IWM", vix="^VIX", sectors=["XLK", "XLF", "XLE"],
                relative_sessions=63, high_sessions=252, long_ma=200, short_ma=50)
    args.update(over)
    return M.features(closes, **args)


def test_features_measure_relative_return_share_above_the_lines_and_distance_from_the_high():
    c = frame()
    c["RSP"] = c["SPY"] * np.linspace(1.0, 0.9, len(c))          # equal weight loses ten percent against the market
    f = feats(c)
    assert f["rsp_spy"].iloc[-1] == pytest.approx(((c["RSP"] / c["SPY"]).iloc[-1] / (c["RSP"] / c["SPY"]).iloc[-64] - 1) * 100)
    assert f["rsp_spy"].iloc[-1] < 0 and f["rsp_spy"].iloc[:63].isna().all()          # no history, no reading
    assert f["spy_drawdown"].iloc[:251].isna().all() and (f["spy_drawdown"].dropna() <= 0).all()
    # three funds: one forced well above its line, two well below
    c["XLK"] = np.linspace(50, 200, len(c)); c["XLF"] = np.linspace(200, 50, len(c)); c["XLE"] = np.linspace(200, 50, len(c))
    f = feats(c)
    assert f["sector_above_200"].iloc[-1] == pytest.approx(100 / 3) and f["sector_above_50"].iloc[-1] == pytest.approx(100 / 3)
    assert f["sector_above_200"].iloc[:199].isna().all()


def test_a_fund_that_starts_late_is_left_out_of_the_share_until_it_has_a_line():
    c = frame()
    c.loc[c.index[:300], "XLE"] = np.nan
    f = feats(c)
    # before XLE has 200 sessions, the share is of the two funds that do
    day = c.index[250]
    assert f.loc[day, "sector_above_200"] in (0.0, 50.0, 100.0)
    assert f["sector_above_200"].iloc[-1] in (0.0, pytest.approx(100 / 3), pytest.approx(200 / 3), 100.0)


def test_forward_outcomes_follow_the_path_and_the_last_horizon_has_none():
    price = pd.Series([100, 110, 99, 105, 120, 108.0, 130, 140], index=pd.bdate_range("2024-01-01", periods=8))
    out = M.forward_outcomes(price, 3, floor_pct=5)
    assert out["ret"].iloc[0] == pytest.approx(5.0)                                  # 100 -> 105
    assert out["worst_dd"].iloc[0] == pytest.approx((99 / 110 - 1) * 100)             # the entry close is the first peak
    assert out["hit"].iloc[0] == 1.0 and out["hit"].iloc[3] == 1.0                    # 120 -> 108 is a 10% fall
    rising = M.forward_outcomes(pd.Series([100, 101, 102, 103, 104.0], index=pd.bdate_range("2024-01-01", periods=5)), 3, floor_pct=5)
    assert rising["worst_dd"].iloc[0] == 0.0 and rising["hit"].iloc[0] == 0.0      # a path that never falls has no fall
    assert out.iloc[-3:].isna().all().all() and out.iloc[:-3].notna().all().all()
    assert M.forward_outcomes(price.iloc[:3], 3, 5).isna().all().all()                # too short: nothing, not an error


def test_block_bootstrap_indices_are_reproducible_and_in_range():
    a = M.block_indices(500, 63, 20, seed=1)
    assert a.shape == (20, 500) and a.min() >= 0 and a.max() < 500
    assert (a == M.block_indices(500, 63, 20, seed=1)).all() and not (a == M.block_indices(500, 63, 20, seed=2)).all()
    # inside a block the rows are consecutive
    assert (np.diff(a[0, :63]) == 1).all()


def test_mean_difference_finds_a_real_shift_and_not_a_random_one_and_refuses_a_rare_state():
    rng = np.random.default_rng(4)
    n = 3000
    idx = M.block_indices(n, 63, 600, seed=3)
    mask = (np.arange(n) // 120) % 3 == 0                                           # stretches, as real states come
    shifted = rng.normal(0, 1, n) + 2.0 * mask
    found = M.mean_difference(shifted, mask, idx)
    assert found["diff"] == pytest.approx(2.0, abs=0.2) and found["lo"] > 0
    nothing = M.mean_difference(rng.normal(0, 1, n), mask, idx)
    assert nothing["lo"] < 0 < nothing["hi"]                                         # no difference detected
    rare = np.zeros(n, dtype=bool); rare[:5] = True
    assert M.mean_difference(shifted, rare, idx) == {"inside": None, "outside": None, "diff": None, "lo": None, "hi": None}


def test_episodes_count_separate_stretches_not_days():
    mask = np.zeros(400, dtype=bool)
    mask[10:40] = True; mask[50:60] = True; mask[300:310] = True
    assert M.episodes(mask, gap=63) == 2                                            # the first two are one episode
    assert M.episodes(mask, gap=5) == 3 and M.episodes(np.zeros(5, dtype=bool), gap=5) == 0


def test_a_rule_does_not_hold_on_a_day_with_a_missing_reading():
    f = pd.DataFrame({"rsp_spy": [-3.0, np.nan, 1.0, -3.0], "spy_drawdown": [-1.0, -1.0, -1.0, -8.0]})
    both = [{"reading": "rsp_spy", "op": "lt", "value": -2}, {"reading": "spy_drawdown", "op": "gt", "value": -5}]
    assert M.holds(f, both).tolist() == [True, False, False, False]
    assert M.holds(f, both[:1]).tolist() == [True, False, False, True]


def cfg(**over):
    c = dict(load_config()["market_state"])
    c.update(history_start="2018-06-01", resamples=200, min_days=20, **over)
    return c


def test_panel_assembles_without_inventing_and_marks_what_holds_now():
    c = frame(n=1500)
    c["^VIX"] = 14.0
    c.iloc[-30:, c.columns.get_loc("^VIX")] = 30.0                                                     # stress now
    p = P.assemble(as_of=c.index[-1].date(), closes=c, sectors=SECTORS, market="SPY", cfg=cfg())
    json.dumps(p, allow_nan=False)                                                  # no NaN reaches the page
    states = {s["key"]: s for s in p["states"]}
    assert states["stress"]["active_now"] and states["stress"]["days_now"] == 30
    assert p["inputs"]["scored_through"] < p["inputs"]["prices_through"]            # the last horizon has no outcome
    assert (pd.Timestamp(p["inputs"]["prices_through"]) - pd.Timestamp(p["inputs"]["scored_through"])).days >= 63
    # the stress days are the last 30, so none is scored: the state has no days to measure and says so
    assert states["stress"]["days"] == 0 and states["stress"]["status"] == "insufficient" and states["stress"]["outcomes"] is None
    assert {r["key"] for r in p["readings"]} == set(M.READINGS) and all(len(r["spark"]) == 252 for r in p["readings"])
    assert all(r['unit'] == '%' for r in p['readings'] if r['key'] in ('rsp_spy', 'iwm_spy'))
    assert 'ratio change' in P._rule_text([{'reading': 'rsp_spy', 'op': 'lt', 'value': -2}], cfg())
    assert P._rule_text([{'reading': 'rsp_spy', 'op': 'lt', 'value': -2}], cfg()).endswith('-2%')
    assert {s["etf"] for s in p["sectors"]} == {"XLK", "XLF", "XLE"}
    assert sorted(p["sectors"], key=lambda r: -r["vs_200_pct"]) == p["sectors"]


def test_a_state_with_enough_days_reports_outcomes_with_a_range_and_a_detection_flag():
    c = frame(n=2000, seed=8)
    c["^VIX"] = np.where((np.arange(len(c)) // 150) % 3 == 0, 30.0, 14.0)           # stress in stretches
    p = P.assemble(as_of=c.index[-1].date(), closes=c, sectors=SECTORS, market="SPY", cfg=cfg())
    s = {x["key"]: x for x in p["states"]}["stress"]
    assert s["status"] == "ok" and s["days"] > 300 and s["episodes"] >= 3
    for key in ("ret", "worst_dd", "hit"):
        o = s["outcomes"][key]
        assert o["lo"] <= o["diff"] <= o["hi"] and isinstance(o["detected"], bool)
    assert 0 <= s["outcomes"]["hit"]["inside"] <= 100                                # a probability in percent
    assert s["rule"] == "VIX > 25"
