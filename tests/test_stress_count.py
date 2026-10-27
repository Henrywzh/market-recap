import json
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import stress_count as SC

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = tomllib.loads((ROOT / "config/dashboard.toml").read_text())["risk"]["stress"]
SECTORS = SETTINGS["sector_roster"]


def _sessions(n=400):
    return pd.bdate_range("2024-01-01", periods=n)


def _inputs(n=400, *, spx=None, vix=15.0, spread=2.0, anfci=-0.5, sectors_up=True):
    idx = _sessions(n)
    price = pd.Series(np.linspace(100, 160, n) if spx is None else spx, index=idx)
    sectors = pd.DataFrame({s: (np.linspace(50, 80, n) if sectors_up else np.linspace(80, 50, n)) for s in SECTORS}, index=idx)
    weekly = pd.Series(anfci, index=pd.date_range(idx[0] - pd.Timedelta(days=30), idx[-1], freq="W-FRI"))
    return dict(spx=price, sectors=sectors, vix=pd.Series(vix, index=idx), spread=pd.Series(spread, index=idx), anfci=weekly)


def _series(**kw):
    return SC.input_series(**_inputs(**kw), long_ma=200)


def _evaluate(**kw):
    return SC.evaluate(_series(**kw), SETTINGS, history_sessions=50)


def test_calm_market_has_no_vote_on_and_a_raw_count_of_zero():
    out = _evaluate()
    assert out["raw"] == 0 and out["groups_on"] == 0
    assert out["known"] == out["total"] == 9


def test_each_input_flips_only_its_own_vote():
    base = {v["key"]: v["on"] for g in _evaluate()["groups"] for v in g["votes"]}
    assert not any(base.values())
    loud = {v["key"]: v["on"] for g in _evaluate(vix=30.0)["groups"] for v in g["votes"]}
    assert loud["vix_high"] and not loud["rv_high"]
    wide = {v["key"]: v["on"] for g in _evaluate(spread=3.5)["groups"] for v in g["votes"]}
    assert wide["spread_high"] and not wide["spread_widening"]
    tight = {v["key"]: v["on"] for g in _evaluate(anfci=0.3)["groups"] for v in g["votes"]}
    assert tight["anfci_tight"] and not tight["anfci_rising"]


def test_falling_market_turns_on_price_participation_and_volatility_votes():
    n = 400
    falling = np.r_[np.linspace(100, 160, n - 60), np.linspace(160, 120, 60)]
    out = _evaluate(spx=falling, sectors_up=False)
    on = {v["key"] for g in out["groups"] for v in g["votes"] if v["on"]}
    assert {"below_200", "drawdown_5", "thin_sectors"} <= on


def test_missing_input_is_unknown_not_off_and_blocks_the_raw_count():
    inputs = _inputs()
    inputs["anfci"] = pd.Series(dtype=float)
    out = SC.evaluate(SC.input_series(**inputs, long_ma=200), SETTINGS, history_sessions=50)
    conditions = next(g for g in out["groups"] if g["key"] == "conditions")
    assert [v["on"] for v in conditions["votes"]] == [None, None]
    assert conditions["known"] == 0 and conditions["total"] == 2
    assert out["raw"] is None and out["groups_on"] is None
    assert out["known"] == 7 and out["on_known"] == 0


def test_group_score_counts_groups_not_votes():
    votes = pd.DataFrame({"a": [1.0], "b": [1.0], "c": [0.0], "d": [1.0]})
    raw, groups = SC.score(votes, {"one": ["a", "b"], "two": ["c"], "three": ["d"]})
    assert (raw.iloc[0], groups.iloc[0]) == (3, 2)


def test_weekly_value_is_carried_for_two_weeks_then_dropped():
    weekly = pd.Series([1.0], index=[pd.Timestamp("2024-01-05")])
    days = pd.bdate_range("2024-01-05", "2024-02-09")
    out = SC.weekly_on_sessions(weekly, days)
    assert out.loc["2024-01-19"] == 1.0
    assert np.isnan(out.loc["2024-01-22"])


def test_history_is_trimmed_and_unknown_days_are_none():
    out = _evaluate()
    assert len(out["history"]["dates"]) == len(out["history"]["raw"]) == 50
    early = SC.evaluate(_series(n=210), SETTINGS, history_sessions=500)
    assert early["history"]["raw"][0] is None            # 200-day average not yet defined
    json.dumps(early)


def test_week_ago_count_is_the_raw_count_five_sessions_back():
    out = _evaluate()
    assert out["week_ago"] == 0


def test_config_matches_the_research_protocol():
    protocol = json.loads((ROOT / "research/risk_environment_v2/protocol.json").read_text()) \
        if (ROOT / "research/risk_environment_v2/protocol.json").exists() else None
    if protocol is None:
        pytest.skip("research folder not present")
    configured = {g["key"]: [v["key"] for v in SETTINGS["votes"] if v["group"] == g["key"]] for g in SETTINGS["groups"]}
    assert configured == protocol["groups"]
    assert SETTINGS["reference"] == protocol["scores"]["primary_high_raw"]


def test_every_configured_vote_names_a_known_input_and_operator():
    for vote in SETTINGS["votes"]:
        assert vote["input"] in SC.INPUTS and vote["op"] in SC.OPERATORS
        assert vote["group"] in {g["key"] for g in SETTINGS["groups"]}
    assert len({v["key"] for v in SETTINGS["votes"]}) == len(SETTINGS["votes"])
