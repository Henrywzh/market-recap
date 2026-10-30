from __future__ import annotations

import numpy as np
import pandas as pd

from market_recap.compute import trade_conditions as T
from market_recap.config import load_config
from market_recap.panels import trade_conditions as P


def test_runs_record_changes_and_drop_a_leading_unknown():
    s = pd.Series([None, "A", "A", "B", None, "B"], index=pd.bdate_range("2024-01-01", periods=6), dtype=object)
    assert T.runs(s) == [["2024-01-02", "A"], ["2024-01-04", "B"], ["2024-01-05", None], ["2024-01-08", "B"]]


def test_fed_cycle_compares_the_target_with_its_level_a_lookback_earlier():
    target = pd.Series([1.0, 1.25, 1.25], index=pd.to_datetime(["2022-01-01", "2023-03-01", "2023-12-31"]))
    sessions = pd.to_datetime(["2022-02-01", "2023-03-02", "2023-08-29", "2023-09-01"])
    state = T.fed_cycle(target, sessions, 182)
    assert state.iloc[0] is None  # not yet a lookback of history
    assert list(state.iloc[1:]) == ["HIKING", "HIKING", "HOLD"]


def test_quadrant_applies_from_the_day_after_it_was_read_and_the_ledger_follows_the_archive():
    history = [{"known": "2026-09-01", "quadrant": "SLOWDOWN"}, {"known": "2026-10-01", "quadrant": "SLOWDOWN"}]
    ledger = [{"date": "2026-10-29", "quadrant": "REFLATION"}]
    events = T.quadrant_events(history, ledger)
    sessions = pd.to_datetime(["2026-09-01", "2026-09-02", "2026-10-29", "2026-10-30"])
    assert list(T.quadrant_states(events, sessions).fillna("-")) == ["-", "SLOWDOWN", "SLOWDOWN", "REFLATION"]


def test_equal_weight_z_uses_only_trailing_sessions():
    idx = pd.bdate_range("2020-01-01", periods=300)
    market = pd.Series(100.0, index=idx)
    equal = pd.Series(np.r_[np.linspace(100, 101, 299), 110], index=idx)
    z, state = T.equal_weight_z(equal, market, 252, 1.0)
    assert state.iloc[250] is None and state.iloc[-1] == "EW LEADING"
    # The jump on the last day does not reach back into earlier z-scores.
    z2, _ = T.equal_weight_z(equal.iloc[:-1], market.iloc[:-1], 252, 1.0)
    assert np.allclose(z.iloc[:-1].dropna(), z2.dropna())


def test_assemble_gives_every_condition_runs_options_and_today():
    cfg = load_config()["trade_conditions"]
    idx = pd.bdate_range("2018-01-01", "2026-10-29")
    rng = np.random.default_rng(1)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx)))), index=idx)
    closes = pd.DataFrame({"SPY": spy, "RSP": spy * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx)))), "^VIX": 14 + 10 * rng.random(len(idx))})
    fed = pd.Series([1.5, 0.25, 5.5, 4.0], index=pd.to_datetime(["2018-01-01", "2020-03-16", "2023-07-27", "2025-12-11"]))
    ten = pd.Series(np.linspace(2, 4.5, len(idx)), index=idx)
    out = P.assemble(closes=closes, fed_target=fed, ten_year=ten,
                     quadrant_history=[{"known": "2026-09-01", "quadrant": "SLOWDOWN"}],
                     ledger=[{"date": "2026-10-29", "quadrant": "REFLATION"}], cfg=cfg, as_of="2026-10-29")
    by = {c["key"]: c for c in out["conditions"]}
    assert set(by) == {"fed", "rates", "trend", "vix", "breadth", "quadrant"}
    assert by["fed"]["today"] == "HOLD" and by["rates"]["today"] == "RISING"
    assert by["quadrant"]["today"] == "REFLATION"  # the latest read, for "like today"
    assert by["quadrant"]["runs"][-1][1] == "SLOWDOWN"  # but it applies to sessions after the read
    for c in out["conditions"]:
        assert all(r[1] is None or r[1] in c["options"] for r in c["runs"])
