from datetime import date

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import watch as W

D = pd.bdate_range("2026-10-05", periods=12)  # D[0] is Monday 2026-10-05


def _series(values, index=None):
    index = D[: len(values)] if index is None else index
    return pd.Series(values, index=index, dtype=float)


def _frame(met, near=None, index=None):
    index = D[: len(met)] if index is None else index
    near = [False] * len(met) if near is None else near
    return pd.DataFrame({"met": met, "near": near}, index=index)


def _states(pattern):
    """'T' triggered, 'n' near, 'q' quiet, 'm' missing, one character per session from D[0]."""
    names = {"T": "triggered", "n": "near", "q": "quiet", "m": "missing"}
    return pd.Series([names[c] for c in pattern], index=D[: len(pattern)], dtype=object)


# --- measure ----------------------------------------------------------------------

def test_level_is_the_series_with_nan_dropped_and_sessions_ignored():
    out = W.measure(_series([3.0, np.nan, 1.0]), "level", 20)
    assert out.tolist() == [3.0, 1.0]


def test_change_pct_is_percent_over_sessions():
    out = W.measure(_series([100.0, 110.0, 121.0]), "change_pct", 1)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1:].tolist() == pytest.approx([10.0, 10.0])
    two = W.measure(_series([100.0, 110.0, 121.0]), "change_pct", 2)
    assert two.iloc[2] == pytest.approx(21.0)


def test_change_bp_takes_a_yield_in_percent():
    out = W.measure(_series([4.00, 4.25, 4.10]), "change_bp", 1)
    assert out.iloc[1:].tolist() == pytest.approx([25.0, -15.0])


def test_nan_is_dropped_before_the_shift():
    out = W.measure(_series([1.0, np.nan, 2.0]), "change_pct", 1)
    assert len(out) == 2
    assert out.iloc[1] == pytest.approx(100.0)


def test_change_over_a_zero_base_is_missing_not_infinite():
    out = W.measure(_series([0.0, 1.0]), "change_pct", 1)
    assert np.isnan(out.iloc[1])


def test_measure_sorts_by_date():
    unordered = pd.Series([3.0, 1.0, 2.0], index=[D[2], D[0], D[1]])
    assert W.measure(unordered, "level", 1).tolist() == [1.0, 2.0, 3.0]


def test_unknown_measure_raises():
    with pytest.raises(ValueError):
        W.measure(_series([1.0, 2.0]), "ratio", 1)


# --- condition --------------------------------------------------------------------

def test_above_meets_from_threshold_and_is_near_between_the_lines():
    out = W.condition(_series([0.90, 0.96, 1.0, 1.2]), op="above", threshold=1.0, near=0.95)
    assert out["met"].tolist() == [False, False, True, True]
    assert out["near"].tolist() == [False, True, False, False]


def test_below_meets_from_threshold_down_and_is_near_above_the_threshold():
    out = W.condition(_series([-6.0, -5.5, -3.5, -2.0]), op="below", threshold=-5.0, near=-3.0)
    assert out["met"].tolist() == [True, True, False, False]
    assert out["near"].tolist() == [False, False, True, False]


def test_missing_reading_is_neither_met_nor_near():
    out = W.condition(_series([np.nan, 2.0]), op="above", threshold=1.0, near=1.5)
    assert out["met"].tolist() == [False, True]
    assert out["near"].tolist() == [False, False]


def test_no_near_line_means_never_near():
    out = W.condition(_series([0.5, 2.0]), op="above", threshold=1.0, near=None)
    assert out["near"].tolist() == [False, False]


def test_condition_frame_is_boolean_on_the_input_index():
    out = W.condition(_series([0.5, 2.0]), op="above", threshold=1.0, near=None)
    assert list(out.index) == list(D[:2])
    assert all(dtype == bool for dtype in out.dtypes)


def test_unknown_op_raises():
    with pytest.raises(ValueError):
        W.condition(_series([1.0]), op="equal", threshold=1.0, near=None)


# --- scenario_states ----------------------------------------------------------------

def test_all_triggers_only_when_every_condition_is_met():
    a = _frame([True, True, False, False], near=[False, False, True, False])
    b = _frame([True, False, True, False], near=[False, True, False, False])
    assert W.scenario_states([a, b], "all").tolist() == ["triggered", "near", "near", "quiet"]


def test_all_is_near_only_when_every_condition_is_met_or_near():
    a = _frame([False], near=[True])
    b = _frame([True])
    assert W.scenario_states([a, b], "all").tolist() == ["near"]
    quiet = _frame([False], near=[False])
    assert W.scenario_states([quiet, b], "all").tolist() == ["quiet"]


def test_any_triggers_on_one_met_and_is_near_on_one_near():
    a = _frame([False, False, False, False], near=[False, True, False, False])
    b = _frame([False, False, True, False])
    assert W.scenario_states([a, b], "any").tolist() == ["quiet", "near", "triggered", "quiet"]


def test_reading_is_carried_forward_at_most_five_sessions():
    a = _frame([True] * 7)  # D[0]..D[6]
    b = _frame([True], index=pd.DatetimeIndex([D[0]]))
    states = W.scenario_states([a, b], "all")
    # B's one reading carries over D[1]..D[5] (five rows); D[6] has no reading left.
    assert states.tolist() == ["triggered"] * 6 + ["missing"]


def test_carried_reading_also_joins_an_any_match():
    a = _frame([True], index=pd.DatetimeIndex([D[0]]))
    b = _frame([False] * 7)
    assert W.scenario_states([a, b], "any").tolist() == ["triggered"] * 6 + ["quiet"]


def test_missing_when_no_condition_has_a_reading_for_any():
    a = pd.DataFrame({"met": [np.nan, True], "near": [np.nan, False]}, index=D[:2])
    b = pd.DataFrame({"met": [np.nan, False], "near": [np.nan, False]}, index=D[:2])
    assert W.scenario_states([a, b], "any").tolist() == ["missing", "triggered"]


def test_states_are_on_the_union_of_dates():
    a = _frame([True], index=pd.DatetimeIndex([D[0]]))
    b = _frame([False], index=pd.DatetimeIndex([D[1]]))
    states = W.scenario_states([a, b], "any")
    assert list(states.index) == list(D[:2])


def test_no_conditions_gives_no_states():
    assert len(W.scenario_states([], "all")) == 0


def test_unknown_match_raises():
    with pytest.raises(ValueError):
        W.scenario_states([_frame([True])], "some")


# --- episodes -----------------------------------------------------------------------

def test_runs_closer_than_the_merge_gap_merge_and_count_triggered_sessions_only():
    # Two quiet sessions between the runs: under the default gap of 5 they merge.
    out = W.episodes(_states("TTqqTTT"))
    assert out == [{"start": "2026-10-05", "end": "2026-10-13", "sessions": 5}]


def test_a_gap_of_the_merge_gap_or_more_keeps_runs_apart():
    states = _states("TTqqqqqTT")  # five quiet sessions between the runs
    assert W.episodes(states, merge_gap=5) == [
        {"start": "2026-10-05", "end": "2026-10-06", "sessions": 2},
        {"start": "2026-10-14", "end": "2026-10-15", "sessions": 2},
    ]
    assert W.episodes(states, merge_gap=6) == [{"start": "2026-10-05", "end": "2026-10-15", "sessions": 4}]


def test_near_and_missing_sessions_count_as_not_triggered_for_the_gap():
    assert len(W.episodes(_states("TnTmT"), merge_gap=5)) == 1
    assert len(W.episodes(_states("TnTmT"), merge_gap=1)) == 3


def test_zero_merge_gap_keeps_gapped_runs_apart_but_not_consecutive_sessions():
    assert W.episodes(_states("TTqT"), merge_gap=0) == [
        {"start": "2026-10-05", "end": "2026-10-06", "sessions": 2},
        {"start": "2026-10-08", "end": "2026-10-08", "sessions": 1},
    ]
    assert W.episodes(_states("TTT"), merge_gap=0) == [{"start": "2026-10-05", "end": "2026-10-07", "sessions": 3}]


def test_no_triggered_session_gives_no_episodes_and_order_is_oldest_first():
    assert W.episodes(_states("qqnm")) == []
    out = W.episodes(_states("TqqqqqqqqT"), merge_gap=5)
    assert [e["start"] for e in out] == ["2026-10-05", "2026-10-16"]


# --- lifecycle ----------------------------------------------------------------------

WINDOW = {"added": date(2026, 10, 5), "horizon": date(2027, 3, 31), "as_of": date(2026, 10, 9)}


def test_live_scenario_reports_state_change_and_record():
    out = W.lifecycle(_states("qqTTn"), None, **WINDOW)
    assert out == {
        "state": "near",
        "previous_state": "triggered",
        "changed": True,
        "since": "2026-10-09",
        "first_triggered": "2026-10-07",
        "triggered_sessions": 2,
        "killed_on": None,
        "outcome": None,
    }


def test_since_is_the_start_of_the_current_run():
    out = W.lifecycle(_states("qTTTT"), None, **WINDOW)
    assert out["since"] == "2026-10-06"
    assert out["changed"] is False


def test_dates_after_as_of_are_ignored():
    out = W.lifecycle(_states("qqqTT"), None, added=date(2026, 10, 5), horizon=date(2027, 3, 31),
                      as_of=date(2026, 10, 7))
    assert out["state"] == "quiet"
    assert out["first_triggered"] is None
    assert out["triggered_sessions"] == 0


def test_sessions_before_added_do_not_count_toward_the_trigger_record():
    out = W.lifecycle(_states("TTqT"), None, added=date(2026, 10, 7), horizon=date(2027, 3, 31),
                      as_of=date(2026, 10, 8))
    assert out["first_triggered"] == "2026-10-08"
    assert out["triggered_sessions"] == 1
    assert out["state"] == "triggered"
    assert out["previous_state"] == "quiet"
    assert out["changed"] is True


def test_kill_is_sticky_and_dated_from_its_session():
    states = _states("qTTTq")
    kill = pd.Series([False, False, True, False, False], index=D[:5])
    out = W.lifecycle(states, kill, added=date(2026, 10, 5), horizon=date(2027, 3, 31),
                      as_of=date(2026, 10, 12))
    assert out["state"] == "killed"
    assert out["killed_on"] == "2026-10-07"
    assert out["since"] == "2026-10-07"
    assert out["outcome"] == "killed"
    assert out["previous_state"] == "killed"
    assert out["changed"] is False


def test_the_kill_session_is_the_change():
    kill = pd.Series([False, False, True], index=D[:3])
    out = W.lifecycle(_states("qTT"), kill, added=date(2026, 10, 5), horizon=date(2027, 3, 31),
                      as_of=date(2026, 10, 7))
    assert out["state"] == "killed"
    assert out["previous_state"] == "triggered"
    assert out["changed"] is True


def test_kill_outside_the_window_is_ignored():
    states = _states("qqqqq")
    before_added = pd.Series([True, False, False, False, False], index=D[:5])  # 10-05, added 10-06
    after_horizon = pd.Series([False, False, False, False, True], index=D[:5])  # 10-09, horizon 10-08
    for kill in (before_added, after_horizon):
        out = W.lifecycle(states, kill, added=date(2026, 10, 6), horizon=date(2026, 10, 8),
                          as_of=date(2026, 10, 9))
        assert out["killed_on"] is None
        assert out["state"] == "expired"


def test_expired_scenario_that_triggered_within_the_window_is_triggered():
    out = W.lifecycle(_states("qTqqq"), None, added=date(2026, 10, 5), horizon=date(2026, 10, 7),
                      as_of=date(2026, 10, 9))
    assert out["state"] == "expired"
    assert out["outcome"] == "triggered"
    assert out["since"] == "2026-10-08"
    assert out["previous_state"] == "expired"
    assert out["changed"] is False


def test_expired_scenario_with_no_trigger_in_the_window_is_not_triggered():
    out = W.lifecycle(_states("qqqqq"), None, added=date(2026, 10, 5), horizon=date(2026, 10, 7),
                      as_of=date(2026, 10, 9))
    assert out["outcome"] == "not triggered"
    assert out["first_triggered"] is None


def test_a_trigger_only_after_the_horizon_is_not_triggered():
    out = W.lifecycle(_states("qqqTT"), None, added=date(2026, 10, 5), horizon=date(2026, 10, 7),
                      as_of=date(2026, 10, 12))
    assert out["outcome"] == "not triggered"


def test_the_session_the_scenario_expires_reads_as_a_change():
    out = W.lifecycle(_states("qqq"), None, added=date(2026, 10, 5), horizon=date(2026, 10, 6),
                      as_of=date(2026, 10, 7))
    assert out["state"] == "expired"
    assert out["previous_state"] == "quiet"
    assert out["changed"] is True


def test_a_single_reading_has_no_previous_state():
    out = W.lifecycle(_states("T"), None, added=date(2026, 10, 5), horizon=date(2027, 3, 31),
                      as_of=date(2026, 10, 5))
    assert out["previous_state"] is None
    assert out["changed"] is False


def test_no_readings_is_missing():
    empty = pd.Series([], index=pd.DatetimeIndex([]), dtype=object)
    out = W.lifecycle(empty, None, **WINDOW)
    assert out["state"] == "missing"
    assert out["since"] is None


# --- release_probabilities ------------------------------------------------------------

def test_discrete_ladder_reads_exact_strikes():
    ladder = [[0.2, 0.8], [0.3, 0.5], [0.4, 0.2]]
    out = W.release_probabilities(ladder, 0.3, tick=0.1, band=None)
    # above: P(print > 0.3) = 0.5; below: P(print < 0.3) = 1 - P(print > 0.2) = 0.2
    assert out == {"p_above": 0.5, "p_inline": 0.3, "p_below": 0.2}


def test_discrete_ladder_matches_strikes_within_tolerance():
    # 0.3 - 0.1 is not exactly 0.2 in floating point; the strike still matches.
    ladder = [[0.2, 0.8], [0.3, 0.5]]
    out = W.release_probabilities(ladder, 0.3, tick=0.1, band=None)
    assert out["p_below"] == 0.2


def test_discrete_ladder_missing_a_needed_strike_is_none():
    ladder = [[0.2, 0.8], [0.4, 0.2]]
    assert W.release_probabilities(ladder, 0.3, tick=0.1, band=None) is None


def test_continuous_ladder_interpolates_at_the_band_either_side():
    ladder = [[0.0, 0.9], [0.2, 0.7], [0.4, 0.3], [0.6, 0.1]]
    out = W.release_probabilities(ladder, 0.3, tick=None, band=0.05)
    # p_above = P(> 0.35) = 0.4; p_below = 1 - P(> 0.25) = 1 - 0.6 = 0.4
    assert out == {"p_above": 0.4, "p_inline": 0.2, "p_below": 0.4}


def test_continuous_ladder_outside_its_strikes_is_none():
    ladder = [[0.0, 0.9], [0.2, 0.7], [0.4, 0.3], [0.6, 0.1]]
    assert W.release_probabilities(ladder, 0.55, tick=None, band=0.1) is None
    assert W.release_probabilities(ladder, 0.05, tick=None, band=0.1) is None


def test_no_forecast_or_too_few_points_is_none():
    assert W.release_probabilities([[0.2, 0.8], [0.3, 0.5]], None, tick=0.1, band=None) is None
    assert W.release_probabilities([[0.3, 0.5]], 0.3, tick=0.1, band=None) is None


def test_neither_tick_nor_band_is_none():
    assert W.release_probabilities([[0.2, 0.8], [0.3, 0.5]], 0.3, tick=None, band=None) is None


def test_noisy_ladder_is_made_non_increasing_from_the_low_strike_up():
    ladder = [[0.2, 0.6], [0.3, 0.65], [0.4, 0.2]]
    out = W.release_probabilities(ladder, 0.3, tick=0.1, band=None)
    # 0.65 at 0.3 is lowered to the running minimum 0.6 set at 0.2, so it reads 0.6.
    assert out == {"p_above": 0.6, "p_inline": 0.0, "p_below": 0.4}


def test_input_is_sorted_by_strike_before_reading():
    ladder = [[0.4, 0.2], [0.2, 0.8], [0.3, 0.5]]
    out = W.release_probabilities(ladder, 0.3, tick=0.1, band=None)
    assert out == {"p_above": 0.5, "p_inline": 0.3, "p_below": 0.2}


def test_inline_is_zero_when_the_ladder_is_flat_across_the_forecast():
    ladder = [[0.2, 0.5], [0.3, 0.5], [0.4, 0.5]]
    out = W.release_probabilities(ladder, 0.3, tick=0.1, band=None)
    assert out == {"p_above": 0.5, "p_inline": 0.0, "p_below": 0.5}
