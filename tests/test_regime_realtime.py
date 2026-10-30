from market_recap.compute.macro_regime import realtime_points


def test_archive_months_win_and_later_months_come_from_the_ledger():
    history = [{"month": "2026-08", "known": "2026-09-01", "growth": -0.06, "inflation_change_pp": -0.07,
                "quadrant": "SLOWDOWN", "growth_basis": "ads_calibrated"},
               {"month": "2026-09", "known": "2026-10-01", "growth": -0.03, "inflation_change_pp": -0.02,
                "quadrant": "SLOWDOWN", "growth_basis": "ads_calibrated"}]
    ledger = [{"date": "2026-09-30", "month": "2026-09", "growth": 0.1, "inflation_change_pp": 0.1, "quadrant": "REFLATION"},
              {"date": "2026-10-20", "month": "2026-10", "growth": -0.1, "inflation_change_pp": 0.2, "quadrant": "STAGFLATION"},
              {"date": "2026-10-30", "month": "2026-10", "growth": 0.07, "inflation_change_pp": 0.21, "quadrant": "REFLATION"}]
    points = realtime_points(history, ledger, "2026-09")
    assert [p["month"] for p in points] == ["2026-09", "2026-10"]
    assert points[0]["source"] == "archive" and points[0]["quadrant"] == "SLOWDOWN"
    assert points[1] == {"month": "2026-10", "known": "2026-10-30", "growth": 0.07, "inflation_change_pp": 0.21,
                         "quadrant": "REFLATION", "source": "ledger"}


def test_no_window_keeps_every_month_and_empty_inputs_give_none():
    assert len(realtime_points([{"month": "2014-01", "known": "2014-02-03", "quadrant": "GOLDILOCKS"}], [], None)) == 1
    assert realtime_points([], [], "2026-01") == []
