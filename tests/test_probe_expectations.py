"""The expectations probe has to answer the release it was asked about.

Nasdaq files a US release on the next calendar day's page, and lists the
monthly and yearly inflation prints under one name. Kalshi's next open
contract is often a later quarter or a different transform.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import probe_expectations as probe


def _row(name, consensus, previous, country="United States"):
    return {"country": country, "eventName": name, "consensus": consensus, "previous": previous}


def _market(subtitle, bid, ask, last="0.50", oi="10"):
    return {"yes_sub_title": subtitle, "yes_bid_dollars": bid, "yes_ask_dollars": ask,
            "last_price_dollars": last, "open_interest_fp": oi}


def _event(title, close, markets):
    for market in markets:
        market["close_time"] = close
    return {"title": title, "markets": markets}


def test_nasdaq_claims_are_listed_the_day_after_the_release():
    content, lead = probe.read_nasdaq_page(date(2026, 9, 25), [
        _row("Initial Jobless Claims", "201K", "196K"),
        _row("Core Durable Goods Orders", "0.5%", "0.4%"),
        _row("CPI", "2.3%", "2.2%", country="Singapore"),
    ])
    assert content["claims"] == {"value": 201.0, "previous": 196.0, "release": "2026-09-24"}
    assert "durables" not in content
    assert lead == [(date(2026, 9, 24), True), (date(2026, 9, 24), True)]


def test_nasdaq_durables_and_gdp_use_the_release_date_not_the_page_date():
    durables, _ = probe.read_nasdaq_page(date(2026, 9, 26), [
        _row("Durable Goods Orders", "-0.3%", "1.1%"),
    ])
    assert durables["durables"]["value"] == pytest.approx(-0.3)
    assert durables["durables"]["release"] == "2026-09-25"
    gdp, lead = probe.read_nasdaq_page(date(2026, 10, 1), [
        _row("GDP", " ", "1.5%"),
        _row("GDP Price Index", "6.4%", "6.4%"),
        _row("GDP Sales", "2.2%", "1.9%"),
    ])
    assert list(gdp) == ["gdp_final"]
    assert gdp["gdp_final"]["previous"] == pytest.approx(1.5)
    assert gdp["gdp_final"]["value"] is None
    assert lead[-1][0] == date(2026, 9, 30)


def test_nasdaq_inflation_twins_split_into_monthly_and_yearly():
    content, _ = probe.read_nasdaq_page(date(2026, 10, 15), [
        _row("Core CPI", " ", "2.4%"),
        _row("Core CPI", " ", "0.3%"),
        _row("CPI", " ", "0.4%"),
        _row("CPI", " ", "3.4%"),
    ])
    assert content["cpi_mom"]["previous"] == pytest.approx(0.4)
    assert content["cpi_yoy"]["previous"] == pytest.approx(3.4)
    assert content["core_cpi_yoy"]["previous"] == pytest.approx(2.4)
    assert "core_cpi_mom" not in content
    assert content["cpi_yoy"]["release"] == "2026-10-14"


def test_nasdaq_core_pce_yearly_is_not_the_monthly_row():
    content, _ = probe.read_nasdaq_page(date(2026, 10, 1), [
        _row("Core PCE Price Index", " ", "0.2%"),
        _row("Core PCE Price Index", " ", "3.3%"),
    ])
    assert list(content) == ["core_pce_yoy"]
    assert content["core_pce_yoy"]["previous"] == pytest.approx(3.3)
    assert content["core_pce_yoy"]["release"] == "2026-09-30"


def test_two_close_inflation_prints_are_left_blank_rather_than_guessed():
    content, _ = probe.read_nasdaq_page(date(2026, 10, 15), [
        _row("CPI", " ", "1.0%"),
        _row("CPI", " ", "1.2%"),
    ])
    assert content == {}


def test_a_nasdaq_page_with_no_data_is_a_failed_attempt():
    with pytest.raises(RuntimeError, match="HTTP 200 with no data for 2026-09-24"):
        probe.nasdaq_rows(None, date(2026, 9, 24))


def test_nasdaq_queries_the_page_after_each_target():
    days = probe.nasdaq_query_days(date(2026, 9, 23))
    assert date(2026, 9, 25) in days
    assert date(2026, 9, 26) in days
    assert date(2026, 10, 1) in days
    assert date(2026, 10, 3) in days
    assert date(2026, 10, 15) in days
    assert date(2026, 10, 29) in days


def test_kalshi_q3_growth_does_not_answer_the_q2_final():
    events = [
        _event("US real GDP growth in Q3 2026?", "2026-10-30T12:29:00Z", [_market("Above 1.0%", "0.40", "0.44")]),
        _event("US real GDP growth in Q2 2026?", "2026-07-30T12:29:00Z", [_market("Above 1.0%", "0.40", "0.44")]),
    ]
    assert probe.select_kalshi_event("gdp_final", events) is None
    ignored = probe.ignored_kalshi("gdp_final", "KXGDP", events)
    assert ignored == [{"target": "gdp_final", "series": "KXGDP", "event": "US real GDP growth in Q3 2026?",
                        "close": "2026-10-30", "reason": "next open event is a later release"}]


def test_kalshi_monthly_core_pce_does_not_answer_the_yearly_print():
    events = [
        _event("How much will core PCE increase in Aug 2026?", "2026-09-30T12:25:00Z",
               [_market("Above 0.2%", "0.40", "0.44")]),
        _event("How much will core PCE increase in Sep 2026?", "2026-10-29T12:25:00Z",
               [_market("Above 0.2%", "0.40", "0.44")]),
    ]
    assert probe.select_kalshi_event("core_pce_yoy", events) is None
    ignored = probe.ignored_kalshi("core_pce_yoy", "KXPCECORE", events)
    assert ignored[0]["event"] == "How much will core PCE increase in Aug 2026?"
    assert ignored[0]["reason"] == "closes on the release date but is not that print"


def test_kalshi_keeps_the_contract_that_closes_on_the_release():
    september = _event("Inflation in September 2026 (CPI YoY)", "2026-10-14T12:29:00Z",
                       [_market("Above 3.4%", "0.48", "0.52")])
    november = _event("Inflation in November 2026 (CPI YoY)", "2026-12-10T13:29:00Z",
                      [_market("Above 3.4%", "0.48", "0.52")])
    chosen = probe.select_kalshi_event("cpi_yoy", [november, september])
    assert chosen["title"].startswith("Inflation in September")
    mom = _event("CPI in September", "2026-10-14T12:25:00Z", [_market("Above 0.3%", "0.48", "0.52")])
    later = _event("CPI in October", "2026-11-10T13:25:00Z", [_market("Above 0.3%", "0.48", "0.52")])
    assert probe.select_kalshi_event("cpi_mom", [later, mom])["title"] == "CPI in September"


def test_claims_strikes_worded_at_least_are_read_in_thousands():
    event = _event("Initial jobless claims for the week ending September 19, 2026", "2026-09-24T12:25:00Z", [
        _market("At least 180,000", "0.95", "0.99", oi="10"),
        _market("At least 200,000", "0.40", "0.60", last="0.50", oi="20"),
        _market("At least 220,000", "0.05", "0.09", oi="5"),
    ])
    assert probe.select_kalshi_event("claims", [event]) is event
    quote = probe.quote_kalshi_event("claims", event, "KXJOBLESSCLAIMS")
    assert quote["strikes"] == 3
    assert quote["value"] == pytest.approx(200)
    assert quote["release"] == "2026-09-24"
    assert quote["open_interest"] == 35
