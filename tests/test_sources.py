"""Parsing rules that protect the page from a malformed upstream file."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.sources import ishares, sec, ssga, vanguard
from market_recap.sources.http import FetchError
from market_recap.util import clean_float, freshness_status


def test_class_shares_are_translated_for_the_price_feed():
    assert ssga.to_yahoo_symbol("BRK.B") == "BRK-B"
    assert ssga.to_yahoo_symbol("AAPL") == "AAPL"


def test_annual_values_falls_back_per_year_not_per_company():
    """A filer that switches revenue tags mid-history must keep both years."""
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"form": "10-K", "fp": "FY", "fy": 2023, "start": "2023-01-01",
                     "end": "2023-12-31", "val": 100, "filed": "2024-02-01"},
                ]}},
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                    {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-01-01",
                     "end": "2024-12-31", "val": 120, "filed": "2025-02-01"},
                ]}},
            }
        }
    }
    picked = sec._annual_values(facts, sec.LINE_ITEMS["revenue"])
    assert picked[2023]["value"] == 100
    assert picked[2024]["value"] == 120


def test_quarterly_durations_are_rejected():
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-10-01",
                     "end": "2024-12-31", "val": 30, "filed": "2025-02-01"},
                ]}}
            }
        }
    }
    assert sec._annual_values(facts, ("Revenues",)) == {}


def test_a_restatement_wins_over_the_original_filing():
    rows = [
        {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-01-01",
         "end": "2024-12-31", "val": 100, "filed": "2025-02-01"},
        {"form": "10-K", "fp": "FY", "fy": 2024, "start": "2024-01-01",
         "end": "2024-12-31", "val": 97, "filed": "2026-02-01"},
    ]
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}}
    picked = sec._annual_values(facts, ("Revenues",))
    assert picked[2024]["value"] == 97
    assert picked[2024]["filed"] == "2026-02-01"


def test_clean_float_treats_non_finite_as_absent():
    assert clean_float(float("nan")) is None
    assert clean_float(float("inf")) is None
    assert clean_float("nope") is None
    assert clean_float(1.23456, 2) == 1.23


def test_missing_observation_date_is_unknown_not_current():
    assert freshness_status(None, "daily_close") == "unknown"
    assert freshness_status(pd.Timestamp.today(), "daily_close") == "current"


def test_ishares_historical_sheet_parses_nav_and_units():
    """The flow series depends entirely on this sheet being read correctly."""
    workbook = """<?xml version="1.0"?>
<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<ss:Worksheet ss:Name="Holdings"><ss:Table><ss:Row><ss:Cell><ss:Data>x</ss:Data></ss:Cell></ss:Row></ss:Table></ss:Worksheet>
<ss:Worksheet ss:Name="Historical"><ss:Table>
<ss:Row><ss:Cell><ss:Data>As Of</ss:Data></ss:Cell><ss:Cell><ss:Data>NAV per Share</ss:Data></ss:Cell><ss:Cell><ss:Data>Ex-Dividends</ss:Data></ss:Cell><ss:Cell><ss:Data>Shares Outstanding</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data>Sep 21, 2026</ss:Data></ss:Cell><ss:Cell><ss:Data>776.844051</ss:Data></ss:Cell><ss:Cell><ss:Data>--</ss:Data></ss:Cell><ss:Cell><ss:Data>1103450000</ss:Data></ss:Cell></ss:Row>
<ss:Row><ss:Cell><ss:Data>Sep 18, 2026</ss:Data></ss:Cell><ss:Cell><ss:Data>765.357123</ss:Data></ss:Cell><ss:Cell><ss:Data>2.20</ss:Data></ss:Cell><ss:Cell><ss:Data>1,106,100,000</ss:Data></ss:Cell></ss:Row>
</ss:Table></ss:Worksheet>
</ss:Workbook>"""
    frame = ishares._parse_historical(workbook)
    assert list(frame.columns) == ["date", "nav", "shares_outstanding"]
    assert len(frame) == 2
    # Oldest first, so a diff() is a forward-in-time change.
    assert frame.iloc[0]["date"] < frame.iloc[1]["date"]
    # Thousands separators must survive; a dropped comma is a 1000x flow error.
    assert frame.iloc[0]["shares_outstanding"] == 1_106_100_000
    assert frame.iloc[1]["nav"] == pytest.approx(776.844051)


def test_vanguard_rejects_a_fund_it_only_brokers(monkeypatch):
    """Vanguard's endpoint answers for funds it carries but does not issue.

    QQQ comes back as 'Invesco QQQ Trust' with isExternalFund set. Treating
    that as a Vanguard fund would attach Vanguard's share-class semantics to
    someone else's product.
    """
    external = {"fundProfile": {"ticker": "QQQ", "isETF": True, "isExternalFund": True,
                                "longName": "Invesco QQQ Trust"}}
    monkeypatch.setattr(vanguard, "_cached_json", lambda *a, **k: external)
    with pytest.raises(FetchError) as caught:
        vanguard.fetch_fund_facts("QQQ")
    assert caught.value.not_found


def test_vanguard_accepts_its_own_fund(monkeypatch):
    internal = {
        "fundProfile": {"ticker": "VOO", "fundId": "0968", "isETF": True, "isInternalFund": True,
                        "hasMoreThan1ShareClass": True,
                        "associatedFundIds": {"investorFundId": "0040", "admiralFundId": "0540"},
                        "inceptionDate": "2010-09-07T00:00:00-04:00"},
        "currentPrice": {"premiumOrDiscount": "0.0200000000",
                         "dailyPrice": {"regular": {"price": "712.76", "asOfDate": "2026-09-21T00:00:00-04:00"}}},
    }
    monkeypatch.setattr(vanguard, "_cached_json", lambda *a, **k: internal)
    facts = vanguard.fetch_fund_facts("VOO")
    assert facts["multi_share_class"] is True
    assert facts["premium_pct"] == pytest.approx(0.02)
    assert facts["nav"] == pytest.approx(712.76)


def _parse_holdings(payload: bytes):
    """Run fetch_holdings' parsing over a payload without going to the network."""
    import market_recap.sources.ssga as ssga_module

    original = ssga_module._download
    ssga_module._download = lambda *a, **k: payload
    try:
        return ssga_module.fetch_holdings("TEST")
    finally:
        ssga_module._download = original


def _holdings_file(rows: list[list]) -> bytes:
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["Fund Name:", "Test Fund"])
    sheet.append(["Ticker Symbol:", "TEST"])
    sheet.append(["Holdings:", "As of 21-Sep-2026"])
    sheet.append([])
    sheet.append(["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held"])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_index_futures_are_not_index_members():
    """QNDX holds Nasdaq-100 micro futures to equitise cash, under the ticker
    HWBZ6 -- which matches an equity ticker pattern exactly. Left in the
    basket it inflated the member count, sat in the breadth and
    advance/decline denominators as a name that can never advance, and was
    sent to the price feed every build as a permanently missing symbol.

    The issuer's own file separates them: a listed security carries a SEDOL
    and these positions do not.
    """
    payload = _holdings_file([
        ["NVIDIA CORP", "NVDA", "67066G104", "2379504", 8.29, "-", 152905],
        ["APPLE INC", "AAPL", "037833100", "2046251", 7.48, "-", 92596],
        ["NASD100 MICRO EMINDEC26", "HWBZ6", "ADI393JG6", "-", 0.0032, "-", 10],
        ["SSI US GOV MONEY MARKET CLASS", "-", "924QSGII3", "-", 0.185, "-", None],
        ["US DOLLAR", "-", "999USDZ92", "-", 0.21, "-", None],
        ["TPG INC", "2602335D", "436CVR021", "-", 0.000003, "-", 1],
    ])
    frame, as_of, _url = _parse_holdings(payload)

    assert list(frame["ticker"]) == ["NVDA", "AAPL"]
    assert "sedol" not in frame.columns, "the discriminator is internal, not a published column"
    assert as_of == "2026-09-21", "the as-of date comes from the file, not from today"


def test_the_as_of_date_is_read_from_the_file_not_assumed():
    """SSGA publishes the prior session's basket during the morning. A
    dashboard that relabels it as today is quietly wrong."""
    payload = _holdings_file([["NVIDIA CORP", "NVDA", "67066G104", "2379504", 100.0, "-", 1]])
    _frame, as_of, _url = _parse_holdings(payload)
    assert as_of == "2026-09-21"
