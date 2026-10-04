"""CHAIN: report timing across markets, the pair study, the season, the
graph's integrity and the earnings-history parsing behind it."""

from __future__ import annotations

from datetime import date
import json
import tomllib

import pandas as pd
import pytest

from market_recap.compute import chain as C
from market_recap.config import CHAIN_EVIDENCE_PATH, CHAIN_PATH
from market_recap.panels import chain as P
from market_recap.sources import earnings_history as H

US = C.Market("US", "America/New_York", C.time(16, 0), "^GSPC", "amc")
KR = C.Market("KR", "Asia/Seoul", C.time(15, 30), "^KS11", "bmo")
JP = C.Market("JP", "Asia/Tokyo", C.time(15, 30), "^N225", "amc")
NL = C.Market("NL", "Europe/Amsterdam", C.time(17, 30), "^AEX", "bmo")


def _series(market: C.Market, days: list[str], moves: list[float]) -> C.Series:
    return C.Series(pd.Series(moves, index=pd.DatetimeIndex(days)), market)


# --- When a report is news, and which session trades it -------------------------

def test_a_timed_report_is_its_own_instant():
    at = C.info_time({"ts": "2026-08-26T20:20:00+00:00", "timed": True}, US)
    assert at == pd.Timestamp("2026-08-26T20:20:00Z")


def test_an_untimed_report_takes_the_release_market_custom():
    # Korea: an hour before the open, Seoul time.
    kr = C.info_time({"ts": "2026-07-28T00:00:00+00:00", "local": "2026-07-28", "timed": False}, KR)
    assert kr == pd.Timestamp("2026-07-28T07:00", tz="Asia/Seoul").tz_convert("UTC")
    # US after the close, unless the SEC release says before the open.
    amc = C.info_time({"ts": "2026-08-26T00:00:00+00:00", "local": "2026-08-26", "timed": False}, US)
    assert amc == pd.Timestamp("2026-08-26T16:05", tz="America/New_York").tz_convert("UTC")
    bmo = C.info_time({"ts": "2026-07-15T00:00:00+00:00", "local": "2026-07-15", "timed": False, "timing": "bmo"}, NL)
    assert bmo == pd.Timestamp("2026-07-15T07:00", tz="Europe/Amsterdam").tz_convert("UTC")


def test_tokyo_closed_half_an_hour_earlier_before_november_2024():
    assert JP.close_at(date(2024, 11, 1)).hour == 15 and JP.close_at(date(2024, 11, 1)).minute == 0
    assert JP.close_at(date(2024, 11, 5)).minute == 30


def test_an_evening_us_report_is_traded_by_asia_next_morning_and_new_york_next_day():
    info = pd.Timestamp("2026-08-24T16:20", tz="America/New_York").tz_convert("UTC")   # a Monday
    seoul = _series(KR, ["2026-08-24", "2026-08-25", "2026-08-26"], [0.1, 2.0, 0.3])
    york = _series(US, ["2026-08-24", "2026-08-25", "2026-08-26"], [0.2, 1.5, 0.1])
    assert seoul.day(seoul.first_after(info)) == "2026-08-25"
    assert york.day(york.first_after(info)) == "2026-08-25"


def test_a_tokyo_afternoon_report_is_traded_by_new_york_the_same_day():
    info = pd.Timestamp("2026-07-30T15:35", tz="Asia/Tokyo").tz_convert("UTC")
    york = _series(US, ["2026-07-29", "2026-07-30", "2026-07-31"], [0.0, 1.0, 0.0])
    tokyo = _series(JP, ["2026-07-29", "2026-07-30", "2026-07-31"], [0.0, 0.0, 3.0])
    assert york.day(york.first_after(info)) == "2026-07-30"
    assert tokyo.day(tokyo.first_after(info)) == "2026-07-31"


def test_no_session_within_five_days_is_no_reaction():
    info = pd.Timestamp("2026-01-01T12:00Z")
    late = _series(US, ["2025-12-31", "2026-01-20"], [0.0, 1.0])
    assert late.first_after(info) is None


def test_daily_excess_is_beyond_the_index_and_skips_gaps():
    days = pd.DatetimeIndex(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-20"])
    close = pd.Series([100.0, 110.0, 110.0, 121.0], index=days)
    index = pd.Series([100.0, 101.0, 101.0, 101.0], index=days)
    out = C.daily_excess(close, index)
    assert out.loc["2026-01-06"] == pytest.approx(9.0)
    assert out.loc["2026-01-07"] == pytest.approx(0.0)
    assert pd.Timestamp("2026-01-20") not in out.index        # a 13-day gap is not a session's move


# --- The pair study ----------------------------------------------------------------

def _pair_fixture():
    days = pd.bdate_range("2026-01-05", periods=40)
    follow = C.Series(pd.Series([0.5] * 40, index=days), US)
    evening = lambda day: (pd.Timestamp(day).tz_localize("America/New_York") + pd.Timedelta(hours=16, minutes=30)).tz_convert("UTC")  # noqa: E731
    lead_reports = [C.Report(evening(days[5]), 8.0, 6, 4.0, "t")]
    # The follower reports 10 sessions later, after its close.
    follow_reports = [C.Report(evening(days[16]), -3.0, 17, -2.0, "t")]
    return days, follow, lead_reports, follow_reports


def test_pair_records_carry_the_move_the_drift_and_the_follower_report():
    days, follow, lead, mine = _pair_fixture()
    rows = C.pair_records("A", lead, "B", follow, mine)
    assert len(rows) == 1
    r = rows[0]
    assert r["follow_day"] == days[6].strftime("%Y-%m-%d")          # the session after an evening report
    # From the session after (7) to the eve of its own reaction session (16): 10 sessions of 0.5.
    assert r["drift"] == pytest.approx(5.0)
    assert r["follow_surprise"] == -3.0 and r["follow_reaction"] == -2.0


def test_a_surprise_is_clipped_for_the_study():
    days, follow, lead, mine = _pair_fixture()
    lead[0].surprise = 900.0
    assert C.pair_records("A", lead, "B", follow, mine)[0]["lead_surprise"] == C.SURPRISE_CLIP


def test_t_statistics_are_across_lead_reports_not_pairs():
    rows = []
    for lead_day, moves in (("2026-01-02", [1.0, 1.2, 0.8]), ("2026-02-02", [0.4, 0.6, 0.5]), ("2026-03-02", [0.9, 1.1, 1.0])):
        for i, m in enumerate(moves):
            rows.append({"lead": "A", "lead_day": lead_day, "follow": f"F{i}", "lead_move": 2.0, "follow_move": m})
    out = C._clustered(rows, lambda r: r["follow_move"])
    assert out["reports"] == 3 and out["pairs"] == 9
    assert out["t"] is not None


def test_priced_in_counts_a_session_once_however_many_leads_traded_it():
    info = pd.Timestamp("2026-04-30T21:00Z")
    rows = [
        {"follow": "B", "follow_report_info": info, "follow_reaction": -1.0, "follow_surprise": 5.0,
         "lead_info": pd.Timestamp("2026-04-20T21:00Z"), "follow_day": "2026-04-21", "follow_move": 2.0},
        {"follow": "B", "follow_report_info": info, "follow_reaction": -1.0, "follow_surprise": 5.0,
         "lead_info": pd.Timestamp("2026-04-20T22:00Z"), "follow_day": "2026-04-21", "follow_move": 2.0},
        {"follow": "B", "follow_report_info": info, "follow_reaction": -1.0, "follow_surprise": 5.0,
         "lead_info": pd.Timestamp("2026-04-24T21:00Z"), "follow_day": "2026-04-27", "follow_move": 1.0},
    ]
    out = C.priced_in(rows)
    assert out["reports"] == 1


def test_seasons_start_a_week_after_the_quarter():
    assert C.season_window(date(2026, 10, 4)) == (date(2026, 7, 7), date(2026, 10, 7), "CQ2 2026")
    assert C.season_window(date(2026, 10, 8))[2] == "CQ3 2026"
    assert C.season_window(date(2027, 1, 3))[2] == "CQ3 2026"
    assert C.season_window(date(2027, 1, 7))[2] == "CQ4 2026"


def test_a_supply_link_outranks_a_rivalry_for_the_same_pair():
    edges = [
        {"from": "TSM", "to": "SAMSUNG", "type": "competes", "named": True},
        {"from": "SAMSUNG", "to": "NVDA", "type": "supplies", "named": True},
        {"from": "SAMSUNG", "to": "TSM", "type": "supplies", "named": False},
    ]
    cats = P.categories(edges)
    assert cats[("NVDA", "SAMSUNG")] == ("from_customer", True)     # the customer reports, the supplier follows
    assert cats[("SAMSUNG", "NVDA")] == ("from_supplier", True)
    assert cats[("TSM", "SAMSUNG")][0] == "from_customer"


def test_an_adr_keeps_yahoos_clock_when_the_sec_side_agrees():
    # 07:00 in Amsterdam is before New York's open: SEC's "bmo" agrees.
    assert P._us_side("2026-07-15T05:00:00+00:00") == ("2026-07-15", "bmo")
    assert P._us_side("2026-08-26T20:20:00+00:00") == ("2026-08-26", "amc")


# --- The graph itself ----------------------------------------------------------------

def test_every_link_joins_two_companies_in_the_graph():
    graph = tomllib.loads(CHAIN_PATH.read_text(encoding="utf-8"))
    keys = [n["key"] for n in graph["nodes"]]
    assert len(keys) == len(set(keys))
    layers = {l["key"] for l in graph["layers"]}
    for n in graph["nodes"]:
        assert n["layer"] in layers, n
        assert n["market"] in graph["markets"], n
        assert n.get("releases", n["market"]) in graph["markets"], n
    for e in graph["edges"]:
        assert e["type"] in ("supplies", "competes", "partner"), e
        assert e["from"] in keys, e
        for t in e["to"]:
            assert (t[1:] in graph["groups"]) if t.startswith("@") else t in keys, (e, t)
    for members in graph["groups"].values():
        assert set(members) <= set(keys)


def test_the_evidence_file_covers_every_link():
    graph = P.load_graph()
    evidence = json.loads(CHAIN_EVIDENCE_PATH.read_text(encoding="utf-8"))["edges"]
    missing = [f"{e['from']}>{e['to']}" for e in graph["edge_list"] if f"{e['from']}>{e['to']}" not in evidence]
    assert not missing, f"rerun scripts/chain_evidence.py: {missing[:5]}"


# --- Earnings history ------------------------------------------------------------------

def test_the_archive_keeps_reports_and_falls_back_to_calls():
    text = json.dumps({"rows": [
        {"ts": "2025-05-28T20:20:00+00:00", "local": "2025-05-28T16:20:00-04:00", "type": "Earnings", "surprise_pct": 2.8},
        {"ts": "2025-06-26T16:00:00+00:00", "local": "2025-06-26T12:00:00-04:00", "type": "Meeting"},
        {"ts": "2025-02-26T05:00:00+00:00", "local": "2025-02-26T00:00:00-05:00", "type": "Earnings", "surprise_pct": None},
    ]})
    rows = H.parse_archive(text)
    assert [r["timed"] for r in rows] == [False, True]
    calls = H.parse_archive(json.dumps({"rows": [{"ts": "2025-02-20T07:30:00+00:00", "local": "2025-02-20T08:30:00+01:00", "type": "Call"}]}))
    assert len(calls) == 1


def test_recent_quarters_read_bare_epochs_and_midnight_as_untimed():
    payload = {"quoteSummary": {"result": [{
        "earnings": {"earningsChart": {"quarterly": [
            {"surprisePct": "6.16", "periodEndDate": 1785456000, "reportedDate": 1787775600, "actual": 2.22, "estimate": 2.09},
            {"surprisePct": "14.56", "periodEndDate": {"raw": 1774915200}, "reportedDate": {"raw": 1777507200}},
        ]}},
        "calendarEvents": {"earnings": {"earningsDate": [1794945600], "isEarningsDateEstimate": False}},
    }]}}
    rows, upcoming = H.parse_recent(json.dumps(payload))
    assert [r["timed"] for r in rows] == [False, True]
    assert rows[1]["period_end"] == "2026-07-31"
    assert upcoming["ts"].startswith("2026-11-17")


def test_merge_prefers_the_recent_row_for_the_same_report():
    archive = [{"ts": "2025-10-31T07:00:00+00:00", "source": "yahoo_archive"},
               {"ts": "2025-04-30T07:00:00+00:00", "source": "yahoo_archive"}]
    recent = [{"ts": "2025-10-31T07:01:00+00:00", "source": "yahoo_recent"}]
    merged = H.merge(archive, recent)
    assert [r["source"] for r in merged] == ["yahoo_archive", "yahoo_recent"]


def test_the_layer_matrix_groups_pairs_by_where_lead_and_follower_sit():
    rows = [{"lead": "A", "follow": "B", "lead_day": f"2026-0{m}-01", "lead_move": 2.0, "follow_move": 1.0} for m in range(1, 4)]
    rows += [{"lead": "B", "follow": "A", "lead_day": "2026-01-02", "lead_move": -1.0, "follow_move": 0.5}]
    out = C.layer_matrix(rows, {"A": "chips", "B": "cloud"})
    assert out["chips"]["cloud"]["reports"] == 3 and out["chips"]["cloud"]["mean"] == 1.0
    assert out["cloud"]["chips"]["mean"] == -0.5          # signed by the lead's move: against it
    assert out["chips"]["cloud"]["same_way_pct"] == 100


def test_the_replay_carries_two_seasons_of_moves_and_reports():
    days = pd.bdate_range("2026-04-01", "2026-10-02")
    s = C.Series(pd.Series(0.5, index=days), US)
    at = list(days).index(pd.Timestamp("2026-08-27"))
    rep = C.Report(pd.Timestamp("2026-08-26T20:20Z"), 6.2, at, 0.5, "t")
    out = P._replay({"NVDA": {}}, {"NVDA": s}, {"NVDA": [rep]}, date(2026, 10, 2))
    assert [x["label"] for x in out] == ["CQ2 2026", "CQ1 2026"]
    assert out[0]["dates"][0] == "2026-07-07" and out[0]["through"] == "2026-10-02"
    assert len(out[0]["moves"]["NVDA"]) == len(out[0]["dates"])
    assert out[0]["reports"] == [{"key": "NVDA", "day": "2026-08-27", "surprise": 6.2, "move": 0.5}]
    assert out[1]["reports"] == []
