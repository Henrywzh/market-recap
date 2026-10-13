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
from market_recap import validate
from market_recap.panels import catalysts as panel
from market_recap.sources import calendars, nasdaq


def test_heatmap_sums_index_weight_by_sector_and_day():
    # The earnings-weight card, moved here from THEMES: index weight of each earnings date, summed by sector.
    events = [
        {"event_type": "earnings", "date": "2026-10-13", "sector": "Financials", "symbol": "JPM", "index_weights": {"SPX": 1.4}},
        {"event_type": "earnings", "date": "2026-10-13", "sector": "Financials", "symbol": "GS", "index_weights": {"SPX": 0.4}},
        {"event_type": "earnings", "date": "2026-10-14", "sector": "Health Care", "symbol": "JNJ", "index_weights": {"SPX": 1.0}},
        {"event_type": "earnings", "date": "2026-12-01", "sector": "Health Care", "symbol": "X", "index_weights": {"SPX": 1.0}},
        {"event_type": "macro", "date": "2026-10-13", "title": "CPI", "importance": "high"},
    ]
    out = panel._heatmap(events, date(2026, 9, 29), 21)
    assert out["dates"] == ["2026-10-13", "2026-10-14"]
    fin = next(r for r in out["rows"] if r["sector"] == "Financials")
    assert fin["cells"][0] == {"w": 1.8, "top": ["JPM", "GS"], "n": 2} and fin["cells"][1] is None
    assert out["day_totals"] == [1.8, 1.0]


def test_the_validator_takes_a_heatmap_block_or_none_and_refuses_a_malformed_one():
    base = {"events": [{"date": "2026-10-13"}]}
    assert validate._check_catalysts(base) == []                       # an older build has no heatmap key
    assert validate._check_catalysts({**base, "heatmap": {"dates": [], "rows": []}}) == []
    bad = validate._check_catalysts({**base, "heatmap": {"dates": "2026-10-13", "rows": []}})
    assert [(f.severity, f.check) for f in bad] == [("error", "catalysts")]


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


def test_a_recurring_release_missing_from_its_calendar_is_reported():
    from market_recap.panels import catalysts as panel
    releases = [
        {"source": "bls", "match": "^Consumer Price Index$", "label": "CPI", "expect_within_days": 40},
        {"source": "bls", "match": "^Employment Situation$", "label": "Jobs", "expect_within_days": 40},
        {"source": "census", "match": "^Retail", "label": "Retail", "expect_within_days": 40},
    ]
    everything = [
        {"source_id": "bls", "title": "Consumer Price Index", "date": "2026-10-14"},
        {"source_id": "bls", "title": "The Employment Situation", "date": "2026-10-02"},   # renamed
    ]
    missing = panel._expected_missing(everything, releases, date(2026, 9, 23))
    assert missing == ["Jobs (bls, none within 40 days)"]      # census not fetched: already reported as failed


def test_theme_shares_rank_a_name_by_its_cap_among_its_theme_and_skip_a_theme_too_small_to_rank():
    groups = [{"key": "semis", "label": "SEMIS", "bellwethers": ["NVDA", "TSM", "MU", "NOCAP"]},
              {"key": "pair", "label": "PAIR", "bellwethers": ["A", "B"]},
              {"key": "cloud", "label": "CLOUD", "bellwethers": ["NVDA", "MSFT", "ORCL"]}]
    caps = {"NVDA": 5000.0, "TSM": 2000.0, "MU": 1000.0, "NOCAP": None, "A": 1.0, "B": 1.0, "MSFT": 4000.0, "ORCL": 1000.0}
    shares = C.theme_shares(groups, caps)
    assert shares["TSM"]["share"] == pytest.approx(2000 / 8000) and shares["TSM"]["theme"] == "semis"
    assert "NOCAP" not in shares and "A" not in shares and "B" not in shares          # no cap, and a theme of two names
    assert shares["NVDA"]["theme"] == "semis" and shares["NVDA"]["share"] == pytest.approx(5000 / 8000)   # the larger of its two shares
    assert C.theme_importance(0.25, 0.15, 0.05) == "high" and C.theme_importance(0.07, 0.15, 0.05) == "medium"
    assert C.theme_importance(0.01, 0.15, 0.05) == "low" and C.theme_importance(None, 0.15, 0.05) == "low"
    assert C.stronger("low", "high", "medium") == "high" and C.stronger("medium", "low") == "medium"


def test_an_adr_outside_the_indexes_gets_its_theme_importance_not_low(monkeypatch):
    members = {"spx": pd.DataFrame({"yahoo_symbol": ["NVDA", "MU"], "name": ["Nvidia Corp", "Micron Technology Inc"],
                                     "sector": ["Information Technology"] * 2, "weight": [7.0, 0.1]})}
    watchlist = pd.DataFrame({"ticker": ["TSM"], "label": ["TSMC (ADR)"], "name": ["TSMC"], "sector": ["Information Technology"]})
    settings = {"earnings_high_weight": 1.0, "earnings_medium_weight": 0.25, "earnings_theme_high_share": 0.15, "earnings_theme_medium_share": 0.05}
    groups = [{"key": "semis", "label": "SEMIS", "bellwethers": ["NVDA", "TSM", "MU"]}]
    ctx = type("C", (), {"members": members, "watchlist": watchlist, "as_of": "2026-10-13", "config": {"themes": {"groups": groups}}})()
    monkeypatch.setattr(panel.estimates, "market_cap", lambda s, **kw: {"NVDA": 5000.0, "TSM": 2000.0, "MU": 1000.0}[s])
    rows = [{"symbol": s, "timing": "bmo", "eps_forecast": 1.0, "estimates": 5, "last_year_eps": 0.5, "fiscal_quarter": "Q3", "eps": None, "surprise_pct": None}
            for s in ("NVDA", "TSM", "MU")]
    monkeypatch.setattr(panel.nasdaq, "fetch_reported", lambda day, as_of, **kw: rows)
    events, failed = panel._earnings(ctx, settings, [date(2026, 10, 15)], True)
    by = {e["symbol"]: e for e in events}
    assert not failed
    assert by["TSM"]["importance"] == "high" and by["TSM"]["theme"] == {"key": "semis", "label": "SEMIS", "share": 25.0}   # was "low": no index weight
    assert by["NVDA"]["importance"] == "high"
    assert by["MU"]["importance"] == "medium"                                          # 12.5% of its theme, 0.1% of the index
    settings_off = {k: v for k, v in settings.items() if "theme" not in k}
    off = {e["symbol"]: e for e in panel._earnings(ctx, settings_off, [date(2026, 10, 15)], True)[0]}
    assert off["TSM"]["importance"] == "low" and off["TSM"]["theme"] is None            # no theme rule configured: the old rule alone
