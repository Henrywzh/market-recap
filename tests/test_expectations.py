"""Forecasts attach only to the release they describe."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import expectations as X
from market_recap.config import load_config
from market_recap.panels import catalysts as panel


def _row(name, consensus, previous="", country="United States"):
    return {"country": country, "eventName": name, "consensus": consensus, "previous": previous}


def _market(subtitle, bid, ask, last="0.50", oi="10"):
    return {
        "yes_sub_title": subtitle, "yes_bid_dollars": bid, "yes_ask_dollars": ask,
        "last_price_dollars": last, "open_interest_fp": oi,
    }


def _contract(title, close, markets):
    for market in markets:
        market["close_time"] = close
    return {"title": title, "markets": markets}


def test_configured_questions_are_ones_the_catalog_knows():
    for release in load_config()["catalysts"]["releases"]:
        for key in release.get("expect") or []:
            assert key in X.CATALOG


def test_nasdaq_claims_on_the_next_days_page_belong_to_the_release():
    points = X.nasdaq_points(date(2026, 9, 25), [
        _row("Initial Jobless Claims", "201K", "196K"),
        _row("Core Durable Goods Orders", "0.5%", "0.4%"),
        _row("CPI", "2.3%", "2.2%", country="Singapore"),
    ])
    assert points == {("2026-09-24", "claims"): {"value": 201.0}}


def test_nasdaq_splits_a_yearly_print_from_the_monthly_one_only_when_they_differ():
    split = X.split_inflation([
        _row("CPI", " ", "0.4%"), _row("CPI", " ", "3.4%"),
    ])
    assert split["yoy"]["previous"] == "3.4%"
    assert X.split_inflation([_row("CPI", " ", "1.0%"), _row("CPI", " ", "1.2%")]) == {}


def test_kalshi_q3_growth_is_not_the_q2_final():
    q3 = _contract(
        "US real GDP growth in Q3 2026?", "2026-10-30T12:29:00Z",
        [_market("Above 1.0%", "0.40", "0.44"), _market("Above 2.0%", "0.20", "0.24")],
    )
    indexed = X.index_kalshi([q3], "gdp")
    assert ("kalshi", "2026-09-30", "gdp") not in indexed
    event = {"date": "2026-09-30", "reference_period": "2nd Quarter 2026 (Third Estimate)"}
    book = X.empty_book()
    book["markets"] = indexed
    assert X.expectations_for(event, ["gdp"], book) == []


def test_kalshi_monthly_core_pce_is_labeled_monthly():
    monthly = _contract(
        "How much will core PCE increase in Aug 2026?", "2026-09-30T12:25:00Z",
        [
            _market("Above 0.1%", "0.70", "0.74"),
            _market("Above 0.2%", "0.40", "0.44"),
            _market("Above 0.3%", "0.10", "0.14"),
        ],
    )
    book = X.empty_book()
    book["markets"] = X.index_kalshi([monthly], "core_pce_mom")
    event = {"date": "2026-09-30", "reference_period": "August 2026"}
    rows = X.expectations_for(event, ["core_pce_yoy", "core_pce_mom"], book)
    assert [row["label"] for row in rows if row["kind"] == "market"] == ["Core PCE m/m"]


def test_cleveland_nowcast_follows_the_month_the_release_covers():
    book = X.empty_book()
    book["models"] = {("2026-9", "cpi_yoy"): {"value": 3.57}, ("2026-8", "cpi_yoy"): {"value": 2.90}}
    september = {"date": "2026-10-14", "reference_period": "September 2026"}
    august = {"date": "2026-09-11", "reference_period": "August 2026"}
    assert X.expectations_for(september, ["cpi_yoy"], book)[0]["value"] == 3.57
    assert X.expectations_for(august, ["cpi_yoy"], book)[0]["value"] == 2.90
    assert X.expectations_for({"date": "2026-09-24", "reference_period": None}, ["cpi_yoy"], book) == []


def test_claims_ladder_is_read_in_thousands_and_surveys_stay_labeled():
    contract = _contract(
        "Initial jobless claims for the week ending September 19, 2026", "2026-09-24T12:25:00Z", [
        _market("At least 180,000", "0.95", "0.99", oi="10"),
        _market("At least 200,000", "0.40", "0.60", last="0.50", oi="20"),
        _market("At least 220,000", "0.05", "0.09", oi="5"),
    ])
    book = X.empty_book()
    book["markets"] = X.index_kalshi([contract], "claims")
    book["points"][("tradingview", "2026-09-24", "claims")] = {"value": 201}
    book["points"][("nasdaq", "2026-09-24", "claims")] = {"value": 201}
    rows = X.expectations_for({"date": "2026-09-24", "reference_period": None}, ["claims"], book)
    assert [(row["kind"], row["source"], row["value"]) for row in rows] == [
        ("survey", "tradingview", 201), ("survey", "nasdaq", 201), ("market", "kalshi", 200),
    ]
    assert rows[-1]["open_interest"] == 35


def test_polymarket_picks_the_decision_that_ends_on_the_meeting_day():
    events = [
        {"title": "Fed Decision in October?", "endDate": "2026-10-28T16:00:00Z",
         "markets": [{"question": "25 bps increase", "outcomePrices": "[0.67, 0.33]"},
                      {"question": "No change", "outcomePrices": "[0.32, 0.68]"}]},
        {"title": "Fed Decision in December?", "endDate": "2026-12-09T16:00:00Z",
         "markets": [{"question": "25 bps increase", "outcomePrices": "[0.40, 0.60]"}]},
    ]
    picked = X.pick_polymarket("2026-10-28", events)
    assert picked["value"] == pytest.approx(0.67)
    assert X.pick_polymarket("2026-12-09", events)["value"] == pytest.approx(0.40)


def test_attach_writes_the_rows_and_forgets_the_private_key(monkeypatch):
    book = X.empty_book()
    book["points"][("tradingview", "2026-09-24", "claims")] = {"value": 201}
    monkeypatch.setattr(
        "market_recap.sources.expectations.load",
        lambda events, use_cache=True: (book, {"forexfactory": "HTTP 429"}),
    )

    class Log:
        def __init__(self):
            self.records = []

        def add(self, record):
            self.records.append(record)

    ctx = type("Ctx", (), {"as_of": "2026-09-24", "log": Log()})()
    events = [{"date": "2026-09-24", "reference_period": None, "_expect": ["claims"]}]
    failed = panel._attach_expectations(ctx, events, True)
    assert "_expect" not in events[0]
    assert events[0]["expectations"][0]["source_label"] == "TradingView"
    assert failed == {"expectations_forexfactory": "HTTP 429"}
    assert ctx.log.records[0].status == "partial"


def test_actual_is_joined_with_the_survey_point_it_is_compared_to():
    from market_recap.compute import expectations as E

    rows = [{"date": "2026-09-24T12:30:00.000Z", "title": "Initial Jobless Claims", "forecast": 201000, "actual": 195000},
            {"date": "2026-09-25T12:30:00.000Z", "title": "Initial Jobless Claims", "forecast": 205000, "actual": None}]
    book = E.empty_book()
    for (day, key), point in E.tradingview_points(rows).items():
        book["points"][("tradingview", day, key)] = point
    for (day, key), point in E.tradingview_actuals(rows).items():
        book["actuals"][("tradingview", day, key)] = point
    released = E.actuals_for({"date": "2026-09-24"}, ["claims"], book)
    assert len(released) == 1
    assert released[0]["kind"] == "actual" and released[0]["value"] == 195000
    assert released[0]["surprise"] == -6000
    # Not out yet: nothing, rather than a zero or the forecast.
    assert E.actuals_for({"date": "2026-09-25"}, ["claims"], book) == []
