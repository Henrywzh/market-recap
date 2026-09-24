"""MONITOR research queue: peers, evidence, state transitions and sectors."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import monitor as M
from market_recap.panels import monitor
from market_recap.sources import estimates
from market_recap.sources.monitor_state import validate_previous

from test_monitor import _ctx, _dates, _row


def _trend(eps=10.0, eps_30d=10.0, eps_90d=10.0, up=2, down=1, analysts=12, end="2026-12-31"):
    return {"0y": {"end": end, "eps": eps, "eps_30d": eps_30d, "eps_90d": eps_90d,
                   "up_30d": up, "down_30d": down, "analysts": analysts, "low": None, "high": None}}


def _reading(**kw):
    return M.expectation_reading(_trend(**kw), revision_pct=2.0, min_analysts=3)


def test_parse_trend_keeps_fiscal_period_end_and_revision_counts():
    payload = {"quoteSummary": {"result": [{"earningsTrend": {"trend": [
        {"period": "0y", "endDate": "2027-06-30",
         "earningsEstimate": {"avg": {"raw": 19.76}, "numberOfAnalysts": {"raw": 40}},
         "epsTrend": {"current": {"raw": 19.76}, "30daysAgo": {"raw": 19.73}, "90daysAgo": {"raw": 19.37}},
         "epsRevisions": {"upLast30days": {"raw": 12}, "downLast30days": {}}},
        {"period": "-1y", "endDate": "2026-06-30"},
    ]}}]}}
    parsed = estimates.parse_trend(payload)
    assert set(parsed) == {"0y"}
    assert parsed["0y"]["end"] == "2027-06-30"
    assert parsed["0y"]["eps_90d"] == 19.37
    assert parsed["0y"]["up_30d"] == 12
    # An empty object is an unknown count, not zero revisions.
    assert parsed["0y"]["down_30d"] is None
    assert estimates.parse_trend({"quoteSummary": {"result": []}}) is None


def test_expectation_states_distinguish_stale_from_steady():
    assert _reading(eps=9.7)["state"] == "cut"
    assert _reading(eps=9.7)["change_30d_pct"] == pytest.approx(-3.0)
    assert _reading(eps=10.3)["state"] == "raised"
    assert _reading(eps=10.1)["state"] == "steady"
    # Nobody revised and nothing moved: not evidence that it was checked.
    assert _reading(up=0, down=0)["state"] == "stale"
    assert _reading(analysts=2)["state"] == "thin"
    # A loss narrowing is a raise even though the ratio of negatives falls.
    assert _reading(eps=-0.5, eps_30d=-1.0)["state"] == "raised"
    assert M.expectation_reading(None, revision_pct=2.0, min_analysts=3) is None


def test_evidence_is_listed_both_ways_and_unknown_is_never_steady():
    row = {"revenue_growth_pct": 4.0, "fcf_positive": True, "filed": "2026-08-01"}
    state, support, against = M.evidence(row, as_of="2026-09-22", revision_pct=2.0, report_days=100)
    assert state == "unknown" and len(support) == 2 and against == []

    row["expectations"] = _reading(eps=10.1)
    assert M.evidence(row, as_of="2026-09-22", revision_pct=2.0, report_days=100)[0] == "steady"

    row["expectations"] = _reading(eps=9.5, up=1, down=6)
    state, support, against = M.evidence(row, as_of="2026-09-22", revision_pct=2.0, report_days=100)
    assert state == "deteriorating"
    assert any("cut 5.0%" in item for item in against)
    assert any("6 analysts revised down" in item for item in against)
    # Support stays visible beside the case against; nothing is netted.
    assert any("Revenue +4.0%" in item for item in support)

    row = {"expectations": _reading(eps=10.1), "reported": {"date": "2026-05-01", "surprise_pct": -8.0}}
    assert M.evidence(row, as_of="2026-09-22", revision_pct=2.0, report_days=100)[0] == "steady"
    row["reported"]["date"] = "2026-09-01"
    assert M.evidence(row, as_of="2026-09-22", revision_pct=2.0, report_days=100)[0] == "deteriorating"


def test_price_state_needs_both_checks():
    assert M.price_state(True, True) == "stabilising"
    assert M.price_state(True, False) == "weak"
    assert M.price_state(False, None) == "weak"
    assert M.price_state(True, None) is None


def test_peer_basket_excludes_the_company_and_incomplete_peers():
    dates = _dates(count=30)
    frame = pd.DataFrame({"A": np.linspace(100, 50, 30), "B": np.full(30, 100.0),
                          "C": np.linspace(100, 110, 30)}, index=dates)
    frame.loc[dates[-3], "C"] = np.nan
    window, reason = M.peer_window(frame, ["A", "B", "C"], dates[-1], 21)
    assert reason is None and list(window.columns) == ["A", "B"]
    median, count = M.peer_median_return(window, exclude="A")
    assert (median, count) == (0.0, 1)
    assert M.peer_index(window, exclude="A").iloc[-1] == pytest.approx(1.0)


def _two_builds():
    dates = _dates(count=270)
    d1 = dates[-2]
    aaa = np.full(270, 100.0); aaa[-22:-1] = 100.0; aaa[-2] = 90.0; aaa[-1] = 78.0
    bbb = np.full(270, 100.0); bbb[-2] = 75.0; bbb[-1] = 95.0
    ccc = np.full(270, 100.0)
    values = {"AAA": aaa, "BBB": bbb, "CCC": ccc}
    first = _ctx(as_of=d1.strftime("%Y-%m-%d"), members=("AAA", "BBB", "CCC"), close_dates=dates[:-1],
                 close_values={k: v[:-1] for k, v in values.items()})
    second = _ctx(members=("AAA", "BBB", "CCC"), close_dates=dates, close_values=values)
    one = monitor.build(first, trends={}, notes={})
    two = monitor.build(second, previous=one, trends={}, notes={"CCC": {
        "status": "watch", "since": "2026-09-01", "reason": "check", "outcome": None}})
    return one, two


def test_first_build_is_a_baseline_and_the_next_session_lists_changes():
    one, two = _two_builds()
    bbb = _row(one, "BBB")
    assert bbb["candidate"] is True and bbb["reasons"] == ["drawdown", "peer_laggard"]
    assert bbb["first_seen"]["baseline"] is True
    assert one["changes"] == []

    kinds = {(c["ticker"], c["kind"]) for c in two["changes"]}
    assert ("AAA", "entered") in kinds
    assert ("BBB", "left") in kinds
    aaa = _row(two, "AAA")
    assert aaa["first_seen"] == {"date": two["as_of"], "reasons": ["drawdown", "peer_laggard"], "baseline": False}
    assert aaa["anomaly"] == "company"
    assert aaa["why_today"] == ["entered"]
    # BBB keeps its first date after leaving, and its outcome since then.
    assert _row(two, "BBB")["first_seen"]["date"] == one["as_of"]
    assert _row(two, "BBB")["since_first_seen_pct"] == pytest.approx(26.67, abs=0.01)
    assert _row(two, "CCC")["note"]["status"] == "watch"
    assert two["previous_as_of"] == one["as_of"]
    validate_previous(two)


def test_rerunning_a_session_compares_with_the_build_before_it():
    one, two = _two_builds()
    # Rerun of the first session: still a baseline, nothing "entered".
    again = monitor.build(_ctx(as_of=one["as_of"], members=("AAA", "BBB", "CCC"),
                               close_dates=_dates(one["as_of"], 270)), previous=one, trends={}, notes={})
    assert again["changes"] == [] and again["previous_as_of"] is None
    # Rerun of the second session: same changes, same comparison date.
    dates = _dates(count=270)
    rerun_ctx = _ctx(members=("AAA", "BBB", "CCC"), close_dates=dates)
    rerun_ctx.closes = pd.DataFrame({t: r for t, r in zip(("AAA", "BBB", "CCC"), (
        np.r_[np.full(268, 100.0), 90.0, 78.0], np.r_[np.full(268, 100.0), 75.0, 95.0], np.full(270, 100.0)))},
        index=dates)
    rerun = monitor.build(rerun_ctx, previous=two, trends={}, notes={})
    assert rerun["previous_as_of"] == one["as_of"]
    assert {(c["ticker"], c["kind"]) for c in rerun["changes"]} >= {("AAA", "entered"), ("BBB", "left")}


def test_state_log_records_transitions_only_and_ignores_unknown_readings():
    log = monitor._log_state([], "2026-09-21", {"candidate": True, "price_state": "weak", "evidence_state": None})
    assert log == [["2026-09-21", True, "weak", None]]
    same = monitor._log_state(log, "2026-09-22", {"candidate": True, "price_state": None, "evidence_state": None})
    assert same == log
    moved = monitor._log_state(log, "2026-09-22", {"candidate": True, "price_state": "stabilising",
                                                     "evidence_state": "steady"})
    assert moved[-1] == ["2026-09-22", True, "stabilising", "steady"]
    # A rerun of the same session replaces that session's entry.
    rerun = monitor._log_state(moved, "2026-09-22", {"candidate": True, "price_state": "weak",
                                                      "evidence_state": "steady"})
    assert rerun[-1] == ["2026-09-22", True, "weak", "steady"] and len(rerun) == 2


def test_changes_name_stabilisation_and_new_evidence_against():
    row = {"ticker": "X", "sector": "Tech", "candidate": True, "reasons": ["drawdown"], "anomaly": "drawdown",
           "price_state": "stabilising", "evidence_state": "deteriorating", "rs_improving": True,
           "evidence_against": ["FY1 EPS cut 4.0% in 30 days"], "evidence_for": []}
    before = {"date": "2026-09-21", "candidate": True, "price_state": "weak", "evidence_state": "steady"}
    found = monitor._changes(row, before, new_row=False, baseline=False, was_index=True,
                             as_of="2026-09-22", settings={"threshold_pct": 20, "peer_excess_pp": 10})
    assert [c["kind"] for c in found] == ["stabilising", "evidence_down"]
    assert "cut 4.0%" in found[1]["text"]
    # A name neither queued nor watched does not produce price/evidence alerts.
    row["candidate"] = False
    before["candidate"] = False
    assert monitor._changes(row, before, new_row=False, baseline=False, was_index=True,
                            as_of="2026-09-22", settings={"threshold_pct": 20, "peer_excess_pp": 10}) == []


def test_a_night_without_estimates_is_not_a_transition():
    row = {"ticker": "X", "sector": "Tech", "candidate": True, "reasons": ["drawdown"], "anomaly": "drawdown",
           "price_state": "weak", "evidence_state": "unknown", "expectations": None,
           "evidence_against": [], "evidence_for": []}
    before = {"date": "2026-09-21", "candidate": True, "price_state": "weak", "evidence_state": "steady"}
    assert monitor._changes(row, before, new_row=False, baseline=False, was_index=True,
                            as_of="2026-09-22", settings={"threshold_pct": 20, "peer_excess_pp": 10}) == []
    log = [["2026-09-21", True, "weak", "steady"]]
    assert monitor._log_state(log, "2026-09-22", monitor._loggable(row)) == log
    # Filings can still turn evidence against it without an estimate.
    row["evidence_state"], row["evidence_against"] = "deteriorating", ["Free cash flow negative"]
    assert [c["kind"] for c in monitor._changes(
        row, before, new_row=False, baseline=False, was_index=True, as_of="2026-09-22",
        settings={"threshold_pct": 20, "peer_excess_pp": 10})] == ["evidence_down"]


def test_watchlist_names_are_measured_but_not_peers():
    dates = _dates(count=270)
    ctx = _ctx(members=("AAA", "BBB", "CCC"), close_dates=dates)
    ctx.closes["WWW"] = np.linspace(100, 60, len(dates))
    ctx.watchlist = pd.DataFrame([{"ticker": "WWW", "label": "Watched", "priced": True, "sector": "Technology"}])
    payload = monitor.build(ctx, trends={}, notes={})
    www = _row(payload, "WWW")
    assert www["membership"] == "watchlist" and www["in_universe"] is False
    assert www["drawdown_pct"] is not None and www["peer_count"] == 3
    assert _row(payload, "AAA")["peer_count"] == 2
    assert payload["universe"]["members"] == 3
    validate_previous(payload)


def test_sector_event_needs_to_trail_like_for_like():
    dates = _dates(count=270)
    falling = np.full(270, 100.0); falling[-1] = 85.0
    values = {"AAA": falling, "BBB": falling, "CCC": np.full(270, 100.0), "DDD": np.full(270, 100.0)}
    ctx = _ctx(members=tuple(values), close_dates=dates, close_values=values)
    ctx.members["SPX"]["sector"] = ["Technology", "Technology", "Energy", "Energy"]
    payload = monitor.build(ctx, trends={}, notes={})
    sectors = {s["sector"]: s for s in payload["sectors"]}
    assert payload["members_median_return_pct"] == pytest.approx(-7.5)
    tech = sectors["Technology"]
    # XLTECH rises with the market (fixture), so the cap-weighted leg does not
    # trail: the sector's median member alone is not a sector event.
    assert tech["median_excess_pct"] == pytest.approx(-7.5)
    assert tech["event"] is False
    ctx.etf_closes.loc[dates[-22:], "XLTECH"] = np.linspace(105, 90, 22)
    tech = next(s for s in monitor.build(ctx, trends={}, notes={})["sectors"] if s["sector"] == "Technology")
    assert tech["event"] is True
    # Energy has no ETF configured; its median member leads, so no event.
    assert sectors["Energy"]["event"] is False and sectors["Energy"]["etf"] is None


def test_reported_quarter_is_read_from_catalysts_and_kept():
    payload = {"events": [{"event_type": "earnings", "symbol": "AAA", "date": "2026-09-21", "eps": 1.1,
                           "eps_forecast": 1.0, "surprise_pct": None}],
               "recent": {"earnings_reacted": [{"event_type": "earnings", "symbol": "AAA", "date": "2026-09-21",
                                                "eps": 1.1, "eps_forecast": 1.0, "surprise_pct": 10.0,
                                                "return_1d": -4.2}]}}
    found = monitor._reported_events(payload, "2026-09-22")
    assert found["AAA"]["return_1d"] == -4.2 and found["AAA"]["surprise_pct"] == 10.0
    kept = monitor._newer_report(found["AAA"], None)
    assert kept == found["AAA"]


def test_notes_need_a_status_and_a_reason(tmp_path):
    path = tmp_path / "notes.toml"
    path.write_text('[[note]]\nticker = "abc"\nstatus = "exclude"\nreason = "restating"\n'
                    '[[note]]\nticker = "XYZ"\nstatus = "maybe"\nreason = "?"\n')
    notes, problems = monitor.load_notes(path)
    assert notes == {"ABC": {"status": "exclude", "since": None, "reason": "restating", "outcome": None}}
    assert problems == ["monitor note 2 needs ticker, status (watch or exclude) and reason"]
