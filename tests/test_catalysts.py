"""CATALYSTS: the session calendar, rule events and the calendar parsers."""

from __future__ import annotations

from datetime import date
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import catalysts as C
from market_recap.sources import calendars, nasdaq


def test_nyse_holidays_2026_match_the_published_calendar():
    assert sorted(C.nyse_holidays(2026)) == [
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
        date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    ]


def test_early_closes_skip_a_day_that_is_itself_a_holiday():
    assert sorted(C.nyse_early_closes(2026)) == [date(2026, 11, 27), date(2026, 12, 24)]
    assert date(2025, 7, 3) in C.nyse_early_closes(2025)


def test_a_new_year_on_saturday_is_not_moved_into_the_old_year():
    assert date(2021, 12, 31) not in C.nyse_holidays(2022)


def test_options_expire_the_thursday_before_a_good_friday():
    assert C.monthly_expiry(2026, 9) == date(2026, 9, 18)
    assert C.monthly_expiry(2025, 4) == date(2025, 4, 17)


def test_weekly_releases_shift_in_holiday_weeks():
    events = {(e["rule"], e["date"]): e for e in C.rule_events(date(2026, 9, 1), date(2026, 11, 30))}
    assert ("jobless_claims", "2026-11-25") in events          # Thanksgiving Thursday -> Wednesday
    eia = events[("eia_petroleum", "2026-09-10")]              # Labor Day week -> Thursday
    assert eia["time"] == "11:00"
    assert ("quad_witching", "2026-09-18") in events and ("monthly_opex", "2026-10-16") in events


def test_next_sessions_step_over_holidays():
    assert C.next_sessions(date(2026, 11, 25), 2) == [date(2026, 11, 27), date(2026, 11, 30)]


def test_latest_print_transforms_and_keeps_its_period():
    frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=13, freq="MS"), "value": [100.0] * 12 + [103.0]})
    latest = C.latest_print(frame, "yoy")
    assert latest == {"value": pytest.approx(3.0), "period": "2026-01-01"}
    assert C.latest_print(frame, "change")["value"] == pytest.approx(3.0)


def test_ics_times_in_utc_and_eastern_both_land_in_new_york():
    text = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20260930T123000Z\r\nSUMMARY:Personal Income and Outl\r\n ays\\, August 2026\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nDTSTART;TZID=US-Eastern:20261014T083000\r\nSUMMARY:Consumer Price Index\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    first, second = calendars.parse_ics(text, "bea", "x")
    assert (first["title"], first["reference_period"], first["date"], first["time"]) == (
        "Personal Income and Outlays", "August 2026", "2026-09-30", "08:30")
    assert (second["date"], second["time"]) == ("2026-10-14", "08:30")


def test_fed_calendar_times_and_day_lists():
    text = json.dumps({"events": [
        {"month": "2026-10", "days": "28", "time": "2:00 p.m.", "type": "FOMC", "title": "FOMC Meeting"},
        {"month": "2026-10", "days": "1,8", "time": "4:30 p.m.", "type": "Stat", "title": "H.4.1"},
    ]})
    events = calendars.parse_fed(text)
    assert [(e["date"], e["time"]) for e in events] == [("2026-10-28", "14:00"), ("2026-10-01", "16:30"), ("2026-10-08", "16:30")]


def test_treasury_keeps_coupon_auctions_from_today_on():
    rows = [
        {"security_type": "Note", "security_term": "7-Year", "reopening": "No", "offering_amt": "44000000000",
         "announcemt_date": "2026-09-17", "auction_date": "2026-09-24"},
        {"security_type": "Bill", "security_term": "4-Week", "reopening": "Yes", "offering_amt": "90000000000",
         "announcemt_date": "2026-09-22", "auction_date": "2026-09-24"},
        {"security_type": "Note", "security_term": "2-Year", "reopening": "No", "offering_amt": None,
         "announcemt_date": "2026-01-20", "auction_date": "2026-01-26"},
    ]
    events = calendars.parse_treasury(json.dumps({"data": rows}), since="2026-09-23")
    assert [e["title"] for e in events] == ["7-Year Note auction"] and events[0]["detail"].startswith("$44bn")


def test_nasdaq_rows_parse_timing_money_and_negatives():
    text = json.dumps({"data": {"rows": [
        {"symbol": "cost", "time": "time-after-hours", "epsForecast": "$6.48", "noOfEsts": "11", "lastYearEPS": "($0.12)"},
        {"symbol": "AZO", "time": "time-not-supplied", "epsForecast": "", "noOfEsts": "", "eps": "$56.05", "surprise": "2.77"},
    ]}})
    cost, azo = nasdaq.parse_earnings(text)
    assert (cost["symbol"], cost["timing"], cost["eps_forecast"], cost["estimates"], cost["last_year_eps"]) == ("COST", "amc", 6.48, 11, -0.12)
    assert (azo["timing"], azo["eps_forecast"], azo["eps"], azo["surprise_pct"]) == (None, None, 56.05, 2.77)


def test_a_session_the_source_dropped_becomes_an_empty_row():
    """Yahoo dropped 2026-09-22 entirely; counting rows, "1D" spanned two sessions."""
    from market_recap.compute.returns import period_return
    from market_recap.context import mark_missing_sessions

    frame = pd.DataFrame({"X": [100.0, 101.0, 103.0]}, index=pd.to_datetime(["2026-09-18", "2026-09-21", "2026-09-23"]))
    marked = mark_missing_sessions(frame)
    assert pd.Timestamp("2026-09-22") in marked.index and marked.loc["2026-09-22", "X"] != marked.loc["2026-09-22", "X"]
    assert period_return(marked["X"], 1) is None
    # A holiday is not a gap: Labor Day 2026.
    holiday = pd.DataFrame({"X": [1.0, 2.0]}, index=pd.to_datetime(["2026-09-04", "2026-09-08"]))
    assert mark_missing_sessions(holiday).equals(holiday)
