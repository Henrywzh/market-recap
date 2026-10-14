import pandas as pd
import pytest

from market_recap.compute.blackout import calendar_momentum


def curve(values, as_of=None, window=1):
    dates = pd.date_range("2026-01-01", periods=len(values)).strftime("%Y-%m-%d").tolist()
    return calendar_momentum(dates, values, as_of or dates[-1], [window])["windows"][0]


def test_linear_level_has_constant_speed_and_zero_acceleration():
    w = curve(range(25), window=7)
    assert w["now_delta_pp"] == 7
    assert w["now_velocity_pp_per_day"] == 1
    assert w["now_acceleration_pp_per_day2"] == 0
    assert w["velocity_pp_per_day"][:7] == [None] * 7
    assert w["acceleration_pp_per_day2"][:14] == [None] * 14


def test_acceleration_sign_is_not_velocity_sign():
    w = curve([0, 5, 8])
    assert w["now_velocity_pp_per_day"] == 3  # still rising, but slowing
    assert w["now_acceleration_pp_per_day2"] == -2
    w = curve([9, 4, 1])
    assert w["now_velocity_pp_per_day"] == -3  # falling, but slowing
    assert w["now_acceleration_pp_per_day2"] == 2


def test_future_schedule_does_not_leak_into_current_derivatives():
    w = curve([0, 2, 5, 99, 100], as_of="2026-01-03")
    assert w["now_velocity_pp_per_day"] == 3
    assert w["now_acceleration_pp_per_day2"] == 1
    assert w["ahead_delta_pp"] == 94


def test_missing_values_or_calendar_days_are_not_bridged():
    w = curve([0, None, 3, 4], window=2)
    assert w["now_delta_pp"] is None
    assert w["now_acceleration_pp_per_day2"] is None
    w = calendar_momentum(["2026-01-01", "2026-01-03"], [0, 4], "2026-01-03", [1])["windows"][0]
    assert w["now_velocity_pp_per_day"] is None
    assert curve([None] * 5)["now_delta_pp"] is None


def test_zero_is_valid_and_invalid_dates_and_windows_fail():
    assert curve([0, 0, 0])["now_acceleration_pp_per_day2"] == 0
    assert curve([0, 1], as_of="2025-12-31")["now_delta_pp"] is None
    for windows in [[0], [True], [1.5]]:
        with pytest.raises(ValueError):
            calendar_momentum(["2026-01-01"], [0], "2026-01-01", windows)
    with pytest.raises(ValueError):
        calendar_momentum(["2026-01-01"] * 2, [0, 1], "2026-01-01", [1])
