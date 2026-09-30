"""EVENTS: read-through, index impact and the consensus quarter check."""

from datetime import date

import numpy as np
import pandas as pd

from market_recap.compute import events as E


def test_co_move_is_the_regression_slope_on_report_sessions_only():
    leader = [10.0, -5.0, 8.0, -4.0, None]
    follower = [5.0, -2.5, 4.0, 1.0, 3.0]          # the last pair is dropped: no leader move
    stats = E.co_move(leader, follower, min_reports=4)
    assert stats["n"] == 4
    assert stats["beta"] == round((50 + 12.5 + 32 - 4) / (100 + 25 + 64 + 16), 2)
    assert stats["hit"] == 0.75
    assert E.co_move(leader[:3], follower[:3], min_reports=4) is None


def test_candidates_drop_the_name_itself_and_its_other_share_class():
    rng = np.random.default_rng(0)
    base = rng.normal(size=300)
    frame = pd.DataFrame({
        "GOOGL": base, "GOOG": base + rng.normal(scale=0.01, size=300),
        "META": base + rng.normal(scale=0.5, size=300), "XOM": rng.normal(size=300),
    })
    picks = E.candidates(frame.corr(), "GOOGL", count=5, same_issuer={"GOOG"})
    assert [s for s, _ in picks][0] == "META"
    assert "GOOG" not in dict(picks) and "GOOGL" not in dict(picks)


def test_daily_excess_keeps_a_missing_print_missing():
    idx = pd.bdate_range("2026-01-05", periods=4)
    closes = pd.DataFrame({"A": [100.0, np.nan, 110.0, 121.0]}, index=idx)
    index_close = pd.Series([100.0, 100.0, 100.0, 110.0], index=idx)
    out = E.daily_excess(closes, index_close)["A"]
    assert pd.isna(out.iloc[1]) and pd.isna(out.iloc[2])      # no one-day move across the gap
    assert round(out.iloc[3], 6) == 0.0                        # +10% against +10%


def test_index_impact_is_weight_times_move():
    out = E.index_impact({"SPX": 1.832, "NDX": 5.087}, 9.06)
    assert out["NDX"]["points_pct"] == 0.46 and out["SPX"]["points_pct"] == 0.17
    assert E.index_impact({"SPX": 1.0}, None) == {}


def test_yahoo_consensus_is_used_only_for_the_calendar_quarter():
    event = {"fiscal_quarter": "Aug/2026", "eps_forecast": 31.24, "estimates": 10, "last_year_eps": 2.86}
    trend = {"0q": {"end": "2026-08-31", "eps": 31.7, "eps_30d": 31.0, "low": 28.0, "high": 37.4,
                    "revenue": 51.35e9, "revenue_year_ago": 11.3e9, "up_30d": 3, "down_30d": 1}}
    out = E.consensus(trend, event)
    assert out["source"] == "nasdaq + yahoo" and out["revenue"] == 51.35e9
    assert out["eps"] == 31.24 and out["eps_change_30d_pct"] == round(100 * (31.7 / 31.0 - 1), 2)
    rolled = {"0q": {**trend["0q"], "end": "2026-11-30"}}         # Yahoo already on the next quarter
    out = E.consensus(rolled, event)
    assert out["source"] == "nasdaq" and "revenue" not in out
    assert out["eps_growth_pct"] == round(100 * (31.24 / 2.86 - 1), 1)


def test_pre_event_snapshot_day_and_reaction_session():
    assert E.pre_event_day(date(2026, 9, 30), "amc") == date(2026, 9, 30)
    assert E.pre_event_day(date(2026, 10, 5), "bmo") == date(2026, 10, 2)    # Monday -> Friday
    sessions = [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
    assert E.reaction_session(date(2026, 9, 30), "amc", sessions) == date(2026, 10, 1)
    assert E.reaction_session(date(2026, 9, 30), "bmo", sessions) == date(2026, 9, 30)


def test_setup_reads_the_run_in_against_the_sector():
    idx = pd.bdate_range("2025-01-01", periods=300)
    close = pd.Series(np.linspace(100, 130, 300), index=idx)
    sector = pd.Series(np.linspace(100, 100, 300), index=idx)
    out = E.setup(close, sector)
    assert out["from_high_pct"] == 0.0 and out["above_50d"] is True
    assert out["vs_sector_20d"] == out["ret_20d"]


def test_outcome_compares_the_move_with_the_implied_move_the_afternoon_before():
    from market_recap.panels import events as panel

    entry = {"reactions": [{"date": "2026-09-29", "timing": "amc", "session": "2026-09-30",
                            "move_pct": -12.0, "excess_pct": -10.0, "index_pct": -2.0}]}
    event = {"symbol": "AAA", "date": "2026-09-29", "timing": "amc", "eps": 1.1, "eps_forecast": 1.0, "surprise_pct": 10.0}
    history = pd.DataFrame([
        {"underlying": "AAA", "day": "2026-09-29", "expiry": "2026-10-02", "days": 3, "straddle_pct": 8.0, "atm_iv": 0.9},
        {"underlying": "AAA", "day": "2026-09-28", "expiry": "2026-10-02", "days": 4, "straddle_pct": 9.0, "atm_iv": 0.9},
    ])
    excess = pd.DataFrame({"PEER": [-4.5]}, index=[pd.Timestamp("2026-09-30")])
    out = panel._outcome("AAA", event, entry, history, excess, {"with": [{"symbol": "PEER", "beta": 0.5}]})
    assert out["implied"]["snapshot_day"] == "2026-09-29" and out["implied"]["straddle_pct"] == 8.0
    assert out["vs_implied"] == 1.5
    assert out["peers"] == [{"symbol": "PEER", "beta": 0.5, "expected_pct": -5.0, "excess_pct": -4.5}]
    # No reaction on file for that report yet: no outcome card, rather than a blank one.
    assert panel._outcome("AAA", {**event, "date": "2026-09-30"}, entry, history, excess, {}) is None
