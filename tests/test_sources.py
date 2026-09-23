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


REVENUE = sec.ITEMS_BY_KEY["revenue"]


def _row(start, end, val, filed, fy, form="10-K", fp="FY"):
    return {"form": form, "fp": fp, "fy": fy, "start": start, "end": end, "val": val, "filed": filed}


def _facts(**tags):
    return {"entityName": "Example Corp", "facts": {"us-gaap": {
        tag: {"units": {unit: rows for unit, rows in units.items()}} for tag, units in tags.items()
    }}}


def test_annual_values_fall_back_per_year_not_per_company():
    """A filer that switches revenue tags mid-history must keep both years."""
    facts = _facts(
        Revenues={"USD": [_row("2023-01-01", "2023-12-31", 100, "2024-02-01", 2023)]},
        RevenueFromContractWithCustomerExcludingAssessedTax={"USD": [
            _row("2024-01-01", "2024-12-31", 120, "2025-02-01", 2024)]},
    )
    picked = sec._annual_series(facts, REVENUE)
    assert picked["2023-12-31"]["value"] == 100
    assert picked["2024-12-31"]["value"] == 120


def test_quarterly_durations_are_rejected():
    facts = _facts(Revenues={"USD": [_row("2024-10-01", "2024-12-31", 30, "2025-02-01", 2024)]})
    assert sec._annual_series(facts, REVENUE) == {}


def test_a_restatement_wins_over_the_original_filing():
    facts = _facts(Revenues={"USD": [
        _row("2024-01-01", "2024-12-31", 100, "2025-02-01", 2024),
        _row("2024-01-01", "2024-12-31", 97, "2026-02-01", 2025),
    ]})
    picked = sec._annual_series(facts, REVENUE)
    assert picked["2024-12-31"]["value"] == 97
    assert picked["2024-12-31"]["filed"] == "2026-02-01"


def test_comparatives_are_filed_under_their_own_period_not_the_filings_fy():
    """A FY2025 10-K reports FY2024 as a comparative with fy=2025. Keying on
    fy put CrowdStrike's revenue in the wrong years and dropped one."""
    facts = _facts(Revenues={"USD": [
        # Listed newest-comparative-last, the order that used to decide the winner.
        _row("2024-02-01", "2025-01-31", 3954, "2026-03-01", 2026),
        _row("2025-02-01", "2026-01-31", 4812, "2026-03-01", 2026),
        _row("2024-02-01", "2025-01-31", 3954, "2025-03-10", 2025),
    ]})
    rows = sec.annual_statements(facts)
    assert [(r["fiscal_year"], r["revenue"]) for r in rows] == [(2025, 3954), (2026, 4812)]


@pytest.mark.parametrize("end, year", [
    ("2025-12-31", 2025), ("2026-01-03", 2025),   # 52/53-week year ending early January
    ("2026-01-25", 2026), ("2025-06-30", 2025),   # NVIDIA-style January, Microsoft June
])
def test_fiscal_years_are_named_from_the_period_end(end, year):
    assert sec.fiscal_year(end) == year


def test_a_balance_sheet_figure_is_an_instant_not_a_flow():
    equity = sec.ITEMS_BY_KEY["equity"]
    facts = _facts(StockholdersEquity={"USD": [
        {"form": "10-K", "fp": "FY", "fy": 2025, "end": "2025-12-31", "val": 50, "filed": "2026-02-01"},
        _row("2025-01-01", "2025-12-31", 999, "2026-02-01", 2025),  # a duration under a balance tag
    ]})
    assert {end: v["value"] for end, v in sec._annual_series(facts, equity).items()} == {"2025-12-31": 50}


def test_a_reorganised_filer_is_followed_to_its_predecessor(monkeypatch):
    """Exxon's 2026 holding-company CIK holds one 10-Q; the history is under the
    CIK that submitted it, named in the accession number."""
    new = _facts(Revenues={"USD": [{**_row("2026-01-01", "2026-06-30", 201, "2026-08-03", 2026, "10-Q", "Q2"),
                                    "accn": "0000034088-26-000093"}]})
    old = _facts(Revenues={"USD": [{**_row("2025-01-01", "2025-12-31", 332, "2026-02-18", 2025),
                                    "accn": "0000034088-26-000010"}]})
    monkeypatch.setattr(sec, "fetch_company_facts", lambda cik, use_cache=True: {2115436: new, 34088: old}[cik])
    facts, ciks = sec.fetch_filer_facts(2115436)
    assert ciks == [2115436, 34088]
    assert [r["revenue"] for r in sec.annual_statements(facts)] == [332]


def test_a_filing_agent_is_not_mistaken_for_a_predecessor(monkeypatch):
    new = _facts(Revenues={"USD": [{**_row("2026-01-01", "2026-06-30", 1, "2026-08-03", 2026, "10-Q", "Q2"),
                                    "accn": "0001193125-26-000001"}]})
    agent = {"entityName": "Donnelley Financial", "facts": {}}
    monkeypatch.setattr(sec, "fetch_company_facts", lambda cik, use_cache=True: {7: new, 1193125: agent}[cik])
    assert sec.fetch_filer_facts(7)[1] == [7]


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


def _shares(end, val, filed, tag="WeightedAverageNumberOfDilutedSharesOutstanding"):
    return tag, {"form": "10-K", "fp": "FY", "fy": 0, "start": f"{int(end[:4]) - 1}{end[4:]}", "end": end,
                 "val": val, "filed": filed}


def _split_facts(share_rows, eps_rows=()):
    gaap = {}
    for tag, row in share_rows:
        gaap.setdefault(tag, {"units": {"shares": []}})["units"]["shares"].append(row)
    if eps_rows:
        gaap["EarningsPerShareDiluted"] = {"units": {"USD/shares": list(eps_rows)}}
    gaap["Revenues"] = {"units": {"USD": [_row("2018-10-01", "2019-09-30", 1, "2019-11-01", 2019)]}}
    return {"entityName": "Example Corp", "facts": {"us-gaap": gaap}}


def test_a_split_puts_older_years_on_todays_share_basis():
    """Apple's FY2016 was last filed before its 2020 4:1 split; left alone its
    EPS reads 8.31 beside 2.98 and the chart shows a 70% collapse."""
    facts = _split_facts(
        [_shares("2017-09-30", 5_251, "2019-10-31"),   # old basis, never restated
         _shares("2018-09-30", 5_000, "2019-10-31"),   # old basis ...
         _shares("2018-09-30", 20_000, "2020-10-30")],  # ... restated after the split
        [_row("2016-10-01", "2017-09-30", 9.21, "2019-10-31", 2019),
         _row("2017-10-01", "2018-09-30", 11.91, "2019-10-31", 2019),
         _row("2017-10-01", "2018-09-30", 2.98, "2020-10-30", 2020)],
    )
    splits = sec.share_splits(facts)
    assert splits == [("2019-10-31", 4)]
    shares = sec._annual_series(facts, sec.ITEMS_BY_KEY["shares"], splits)
    eps = sec._annual_series(facts, sec.ITEMS_BY_KEY["eps_diluted"], splits)
    assert shares["2017-09-30"]["value"] == 21_004
    assert eps["2017-09-30"]["value"] == pytest.approx(9.21 / 4)
    assert eps["2018-09-30"]["value"] == 2.98  # already restated: not adjusted twice


def test_basic_and_diluted_counts_are_not_read_as_splits_of_each_other():
    facts = _split_facts([
        _shares("2018-09-30", 5_000, "2019-10-31"),
        _shares("2018-09-30", 4_950, "2019-11-01", tag="WeightedAverageNumberOfSharesOutstandingBasic"),
        _shares("2018-09-30", 5_000, "2020-10-30"),
    ])
    assert sec.share_splits(facts) == []


def test_a_split_is_read_from_eps_when_no_plain_share_count_exists():
    """Alphabet tags its counts per share class; its 20:1 split is visible only
    in EPS, which is rounded to cents."""
    facts = _split_facts([], [
        _row("2020-01-01", "2020-12-31", 58.61, "2021-02-03", 2020),
        _row("2020-01-01", "2020-12-31", 2.93, "2023-02-03", 2022),
    ])
    assert sec.share_splits(facts) == [("2021-02-03", 20)]
