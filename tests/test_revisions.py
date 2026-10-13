"""CATALYST LOG: price and estimate moves since an event, on series whose answer is known."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import revisions as R


def days(n, start="2026-10-01"):
    return pd.bdate_range(start, periods=n)


def test_reference_day_is_the_close_before_the_event_unless_it_broke_after_the_close():
    assert R.reference_day(date(2026, 10, 10), False) == date(2026, 10, 9)        # a Saturday event: Friday's close is the last before it
    assert R.reference_day(date(2026, 10, 8), True) == date(2026, 10, 8)
    s = pd.Series([10.0, 11.0, 12.0], index=pd.to_datetime(["2026-10-07", "2026-10-08", "2026-10-12"]))
    assert R.last_on_or_before(s, date(2026, 10, 9)) == (pd.Timestamp("2026-10-08"), 11.0)    # nothing is invented for the 9th
    assert R.last_on_or_before(s, date(2026, 10, 1)) is None


def test_pct_change_needs_a_positive_start_and_both_figures():
    assert R.pct_change(2.0, 3.0) == pytest.approx(50.0)
    assert R.pct_change(-1.0, 2.0) is None and R.pct_change(0.0, 1.0) is None            # off a loss or zero is not a rate
    assert R.pct_change(None, 1.0) is None and R.pct_change(1.0, float("nan")) is None


def test_state_and_summary():
    assert [R.state(v, 3.0) for v in (-3.0, -2.9, 0.0, 2.9, 3.0, None)] == ["down", "flat", "flat", "flat", "up", None]
    s = R.summarize([1.0, -2.0, 0.0, None, float("nan"), 3.0])
    assert s == {"n": 4, "median": pytest.approx(0.5), "up": 2, "down": 1, "flat": 1}
    assert R.summarize([None]) == {"n": 0, "median": None, "up": 0, "down": 0, "flat": 0}


def _table():
    rows = []
    for day, eps_a, eps_b, rev in (("2026-10-07", 10.0, 5.0, 100.0), ("2026-10-09", 10.0, 5.5, 100.0), ("2026-10-12", 9.0, 5.5, 110.0)):
        rows += [{"date": day, "symbol": "A", "period": "0y", "eps": eps_a, "revenue": rev},
                 {"date": day, "symbol": "B", "period": "0y", "eps": eps_b, "revenue": None}]
    return pd.DataFrame(rows)


def test_snapshot_days_pick_the_evening_at_the_reference_close_and_the_latest():
    t = _table()
    assert R.snapshot_days(t, date(2026, 10, 8)) == ("2026-10-07", "2026-10-12")
    assert R.snapshot_days(t, date(2026, 10, 6)) == (None, "2026-10-12")               # the event is before the first snapshot
    assert R.snapshot_days(pd.DataFrame(columns=["date"]), date(2026, 10, 8)) == (None, None)


def test_estimate_changes_between_two_snapshot_days_leave_a_missing_figure_missing():
    t = _table()
    a = R.estimate_changes(t, "A", ["0y", "+1y"], "2026-10-07", "2026-10-12")
    assert a["0y"]["eps"] == pytest.approx(-10.0) and a["0y"]["revenue"] == pytest.approx(10.0)
    assert a["+1y"] == {"eps": None, "revenue": None}                                  # no such period recorded
    b = R.estimate_changes(t, "B", ["0y"], "2026-10-07", "2026-10-12")
    assert b["0y"]["eps"] == pytest.approx(10.0) and b["0y"]["revenue"] is None
    assert R.estimate_changes(t, "NOPE", ["0y"], "2026-10-07", "2026-10-12")["0y"]["eps"] is None
    assert R.estimate_changes(t, "A", ["0y"], None, "2026-10-12")["0y"]["eps"] is None             # no snapshot at the reference
    assert R.estimate_changes(t, "A", ["0y"], "2026-10-12", "2026-10-12")["0y"]["eps"] is None     # nothing has elapsed


def test_basket_path_is_the_median_rebased_at_the_reference_close_and_carries_a_holiday():
    idx = days(5)                                              # Thu 1 Oct .. Wed 7 Oct
    closes = pd.DataFrame({"A": [100, 100, 90, 80, 80.0], "B": [50, 50, 50, 55, 60.0], "C": [10, 10, 11, np.nan, 12.0],
                           "LATE": [np.nan] * 4 + [5.0]}, index=idx)
    path = R.basket_path(closes, ["A", "B", "C", "NOPE"], date(2026, 10, 2))
    assert path.index[0] == pd.Timestamp("2026-10-02") and path.iloc[0] == pytest.approx(100.0)
    assert path.loc["2026-10-06"] == pytest.approx(np.median([80.0, 110.0, 110.0]))     # C carries its last close through its missing day
    assert R.basket_path(closes, ["NOPE"], date(2026, 10, 2)).empty
    assert "LATE" not in R.basket_path(closes, ["LATE"], date(2026, 10, 2)).index.astype(str)
