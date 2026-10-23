"""FLOWS · hedge-fund 13F crowding: parsing, arithmetic, sources and the panel, all offline."""

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_recap import cache
from market_recap.compute import hf_13f as H
from market_recap.panels import flows_hf_13f as panel
from market_recap.sources import sec13f
from market_recap.sources.http import FetchError
from market_recap.util import BuildLog

FIXTURE = Path(__file__).parent / "fixtures" / "sec13f_infotable.xml"


def _members():
    return pd.DataFrame({
        "cusip": ["AAA111111", "BBB222222", "CCC333333"],
        "ticker": ["AAA", "BBB", "CCC"],
        "yahoo_symbol": ["AAA", "BBB", "CCC"],
        "weight": [4.0, 1.0, 0.0],
        "sector": ["Information Technology", "Health Care", "Health Care"],
    })


def _longs(rows):
    return pd.DataFrame(rows, columns=["cusip", "issuer", "shares", "value"])


# --- calendar -------------------------------------------------------------

def test_latest_complete_period_waits_out_the_45_day_deadline():
    assert H.latest_complete_period("2026-10-23") == "2026-06-30"
    assert H.latest_complete_period("2026-08-13") == "2026-03-31"   # day 44 after June: not yet due
    assert H.latest_complete_period("2026-08-14") == "2026-06-30"   # day 45: the deadline itself
    assert H.latest_complete_period("2026-01-20") == "2025-09-30"


def test_prior_quarter_crosses_the_year_end():
    assert H.prior_quarter("2026-06-30") == "2026-03-31"
    assert H.prior_quarter("2026-03-31") == "2025-12-31"
    assert H.prior_quarter("2025-12-31") == "2025-09-30"


# --- parsing ------------------------------------------------------------

def test_information_table_keeps_share_rows_and_tags_options():
    table = H.parse_information_table(FIXTURE.read_text(), "2026-06-30")
    assert list(table.columns) == H.TABLE_COLUMNS
    assert len(table) == 4                                   # the PRN bond row is not equity
    alpha = table[table["cusip"] == "020002101"]
    assert alpha["put_call"].isna().tolist() == [True, True, False]
    assert alpha["put_call"].iloc[2] == "CALL"
    assert alpha["value_usd"].tolist() == [1_000_000.0, 250_000.0, 90_000.0]   # dollars from 2023 on


def test_values_before_the_dollar_change_are_thousands():
    table = H.parse_information_table(FIXTURE.read_text(), "2021-12-31")
    assert table[table["cusip"] == "030003102"]["value_usd"].iloc[0] == 400_000_000.0


def test_long_positions_sum_lines_and_leave_options_out():
    table = H.parse_information_table(FIXTURE.read_text(), "2026-06-30")
    longs = H.long_positions(table).set_index("cusip")
    assert longs.loc["020002101", "shares"] == 6000
    assert longs.loc["020002101", "value"] == 1_250_000.0
    assert "030003102" in longs.index


def test_option_exposure_is_counted_apart():
    table = H.parse_information_table(FIXTURE.read_text(), "2026-06-30")
    exposure = H.option_exposure(table)
    assert exposure == {"put_rows": 0, "call_rows": 1, "put_value": 0.0, "call_value": 90_000.0}


def test_pick_filing_takes_the_latest_accepted_original_for_a_quarter():
    filings = [
        sec13f.Filing("2026-06-30", "2026-08-10", "0000000001-26-000001", "a.xml"),
        sec13f.Filing("2026-06-30", "2026-08-14", "0000000001-26-000002", "b.xml"),
        sec13f.Filing("2026-03-31", "2026-05-15", "0000000001-26-000003", "c.xml"),
    ]
    assert H.pick_filing(filings, "2026-06-30").accession.endswith("000002")
    assert H.pick_filing(filings, "2025-12-31") is None


# --- aggregation and crowding -------------------------------------------

def test_aggregate_counts_distinct_funds_and_ignores_empty_positions():
    longs = {
        1: _longs([["AAA111111", "A", 100, 1000.0], ["BBB222222", "B", 0, 0.0]]),
        2: _longs([["AAA111111", "A", 50, 500.0]]),
        3: _longs([["AAA111111", "A", 0, 0.0]]),
    }
    agg = H.aggregate(longs).set_index("cusip")
    assert agg.loc["AAA111111", "funds"] == 2
    assert agg.loc["AAA111111", "shares"] == 150
    assert "BBB222222" not in agg.index


def test_crowded_names_rank_by_holders_then_value_and_only_members_count():
    agg = pd.DataFrame({
        "cusip": ["AAA111111", "BBB222222", "CCC333333", "ZZZ999999"],
        "issuer": ["A", "B", "C", "Z"],
        "funds": [3, 3, 1, 9],
        "shares": [1, 1, 1, 1],
        "value": [600.0, 300.0, 100.0, 9999.0],
    })
    crowded = H.crowded_names(agg, _members(), total_value=1000.0, top=10)
    assert crowded["ticker"].tolist() == ["AAA", "BBB", "CCC"]    # ZZZ is not an S&P 500 member
    assert crowded.loc[0, "hf_pct"] == pytest.approx(60.0)
    assert crowded.loc[0, "ratio"] == pytest.approx(15.0)         # 60% against a 4% index weight
    assert pd.isna(crowded.loc[2, "ratio"])                       # zero index weight: no ratio


def test_outside_index_and_concentration():
    agg = pd.DataFrame({"cusip": ["AAA111111", "ZZZ999999"], "issuer": ["A", "Z"],
                        "funds": [1, 1], "shares": [1, 1], "value": [300.0, 100.0]})
    assert H.outside_index(agg, _members(), 400.0) == {"names": 1, "value_share_pct": 25.0}
    assert H.concentration(agg, 400.0, top=1) == pytest.approx(75.0)
    assert H.concentration(agg.iloc[0:0], 0.0) is None


def test_option_totals_sum_over_filers():
    total = H.option_totals([
        {"put_rows": 1, "call_rows": 0, "put_value": 5.0, "call_value": 0.0},
        {"put_rows": 0, "call_rows": 2, "put_value": 0.0, "call_value": 7.0},
    ])
    assert total == {"put_rows": 1, "call_rows": 2, "put_value": 5.0, "call_value": 7.0}


# --- changes: shares, valued at one price -------------------------------

def test_a_price_move_with_no_buying_is_not_an_add():
    prior = _longs([["AAA111111", "A", 100, 1.0]]).assign(funds=1)
    now = _longs([["AAA111111", "A", 100, 2.0]]).assign(funds=1)
    moves = H.changes(now, prior, _members(), {"AAA": 50.0})
    assert moves["adds"] == [] and moves["cuts"] == []


def test_adds_and_cuts_are_share_changes_at_the_latest_price():
    now = pd.DataFrame({"cusip": ["AAA111111", "BBB222222"], "issuer": ["A", "B"],
                        "funds": [3, 1], "shares": [300, 40], "value": [0.0, 0.0]})
    prior = pd.DataFrame({"cusip": ["AAA111111", "BBB222222"], "issuer": ["A", "B"],
                          "funds": [2, 2], "shares": [100, 100], "value": [0.0, 0.0]})
    moves = H.changes(now, prior, _members(), {"AAA": 10.0, "BBB": 5.0})
    assert moves["adds"] == [{"ticker": "AAA", "d_holders": 1, "d_value": 2000.0}]
    assert moves["cuts"] == [{"ticker": "BBB", "d_holders": -1, "d_value": -300.0}]
    assert moves["adds_by_holders"][0]["ticker"] == "AAA"
    assert moves["cuts_by_holders"][0]["ticker"] == "BBB"


def test_a_name_without_a_price_has_no_dollar_change():
    now = pd.DataFrame({"cusip": ["AAA111111"], "issuer": ["A"], "funds": [2], "shares": [200], "value": [0.0]})
    prior = pd.DataFrame({"cusip": ["AAA111111"], "issuer": ["A"], "funds": [2], "shares": [100], "value": [0.0]})
    moves = H.changes(now, prior, _members(), {})
    assert moves["adds"] == []
    assert moves["adds_by_holders"] == []                         # no change in holders either


def test_sector_tilt_is_a_difference_of_two_normalised_mixes():
    agg = pd.DataFrame({"cusip": ["AAA111111", "BBB222222"], "issuer": ["A", "B"],
                        "funds": [1, 1], "shares": [1, 1], "value": [750.0, 250.0]})
    tilt = {row["sector"]: row for row in H.sector_tilt(agg, _members())}
    assert tilt["Information Technology"]["hf_pct"] == pytest.approx(75.0)
    assert tilt["Information Technology"]["sp_pct"] == pytest.approx(80.0)   # 4 of 5 index points
    assert tilt["Information Technology"]["tilt_pts"] == pytest.approx(-5.0)
    assert sum(r["hf_pct"] for r in tilt.values()) == pytest.approx(100.0)
    assert sum(r["sp_pct"] for r in tilt.values()) == pytest.approx(100.0)


# --- sources --------------------------------------------------------------

def _recent(forms):
    """The submissions 'recent' block from (form, report, filed, accession, primary) rows."""
    return {
        "form": [row[0] for row in forms],
        "reportDate": [row[1] for row in forms],
        "filingDate": [row[2] for row in forms],
        "accessionNumber": [row[3] for row in forms],
        "primaryDocument": [row[4] for row in forms],
    }


def test_submissions_keep_only_original_13f_hr():
    recent = _recent([
        ("13F-HR/A", "2026-06-30", "2026-09-02", "0000000001-26-000009", "amend.xml"),
        ("13F-HR", "2026-06-30", "2026-08-14", "0000000001-26-000008", "primary_doc.xml"),
        ("13F-NT", "2026-06-30", "2026-08-14", "0000000001-26-000007", "notice.xml"),
        ("10-Q", "2026-06-30", "2026-08-14", "0000000001-26-000006", "q.htm"),
    ])
    rows = sec13f._rows(recent)
    assert [r.accession for r in rows] == ["0000000001-26-000008"]


def test_the_holdings_document_is_not_the_primary_document():
    names = ["0001-index.html", "primary_doc.xml", "infotable.xml", "xslForm13F_X02/x.xsl"]
    assert sec13f._information_table_name(names) == "infotable.xml"
    assert sec13f._information_table_name(["primary_doc.xml"]) is None


def test_requests_are_paced_at_five_a_second(monkeypatch):
    clock = {"now": 100.0}
    slept = []
    monkeypatch.setattr(sec13f, "_last_call", 0.0)
    monkeypatch.setattr(sec13f.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(sec13f.time, "sleep", lambda s: (slept.append(s), clock.update(now=clock["now"] + s)))
    sec13f._throttle()
    sec13f._throttle()
    sec13f._throttle()
    assert slept == [pytest.approx(0.2), pytest.approx(0.2)]


def test_filings_are_fetched_once_and_cached_as_immutable(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    calls = []
    index = json.dumps({"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}})

    def fake_get(url, timeout):
        calls.append(url)
        return index if url.endswith("index.json") else FIXTURE.read_text()

    monkeypatch.setattr(sec13f, "_get", fake_get)
    filing = sec13f.Filing("2026-06-30", "2026-08-14", "0001040273-26-000003", "primary_doc.xml")
    first = sec13f.information_table_xml(1040273, filing)
    second = sec13f.information_table_xml(1040273, filing)
    assert first == second == FIXTURE.read_text()
    assert len(calls) == 2                                   # index and table, each once
    assert calls[1].endswith("/000104027326000003/infotable.xml")


def test_identifiers_come_from_the_spy_file(monkeypatch):
    rows = [
        ["Fund Name:", "SPDR S&P 500 ETF"], [None, None], ["Ticker Symbol:", "SPY"], [None, None],
        ["Name", "Ticker", "Identifier", "SEDOL", "Weight"],
        ["NVIDIA CORP", "NVDA", "67066G104", "2379504", 8.0],
        ["BERKSHIRE HATHAWAY INC CL B", "BRK.B", "084670702", "2073390", 1.5],
        ["CASH", "-", "-", None, 0.1],
    ]
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, header=False, index=False, engine="openpyxl")
    monkeypatch.setattr(sec13f.ssga, "_download", lambda *a, **k: buffer.getvalue())
    frame = sec13f.sp500_identifiers()
    assert frame["cusip"].tolist() == ["67066G104", "084670702"]
    assert frame.loc[1, "yahoo_symbol"] == "BRK-B"


# --- panel ----------------------------------------------------------------

def _ctx(as_of="2026-10-23"):
    closes = pd.DataFrame({"AAA": [9.0, 10.0], "BBB": [4.0, 5.0], "CCC": [1.0, None]},
                          index=pd.to_datetime(["2026-10-21", "2026-10-22"]))
    priced = pd.DataFrame({"yahoo_symbol": ["AAA", "BBB", "CCC"],
                           "sector": ["Information Technology", "Health Care", "Health Care"]})
    return SimpleNamespace(
        as_of=as_of, closes=closes, log=BuildLog(), holdings_as_of="2026-10-22",
        primary=SimpleNamespace(key="SPX"), priced=lambda key: priced,
    )


def _table_xml(rows):
    body = "".join(
        f"<infoTable><nameOfIssuer>{name}</nameOfIssuer><cusip>{cusip}</cusip>"
        f"<value>{value}</value><shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt>"
        f"<sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>"
        for name, cusip, value, shares in rows
    )
    return f'<?xml version="1.0" encoding="utf-8"?><informationTable>{body}</informationTable>'


@pytest.fixture
def fake_13f(monkeypatch):
    holdings = {
        # filer -> quarter -> rows (name, cusip, value in dollars, shares)
        1: {"2026-06-30": [("AAA CO", "AAA111111", 6000.0, 600), ("BBB CO", "BBB222222", 4000.0, 800)],
            "2026-03-31": [("AAA CO", "AAA111111", 3000.0, 300)]},
        2: {"2026-06-30": [("AAA CO", "AAA111111", 2000.0, 200), ("ZZZ CO", "ZZZ999999", 2000.0, 400)],
            "2026-03-31": [("AAA CO", "AAA111111", 2000.0, 200)]},
    }
    filers = [
        {"cik": 1, "label": "One", "style": "fundamental"},
        {"cik": 2, "label": "Two", "style": "activist"},
        {"cik": 3, "label": "Three", "style": "multi"},
    ]
    filings = {
        cik: [sec13f.Filing(q, f"{q[:4]}-08-14", f"000000000{cik}-26-00000{i}", "primary_doc.xml")
              for i, q in enumerate(sorted(by_quarter, reverse=True), start=1)]
        for cik, by_quarter in holdings.items()
    }
    monkeypatch.setattr(panel, "load_filers", lambda: filers)
    # SSGA's file carries no sector; the sector comes from the priced members.
    monkeypatch.setattr(panel.sec13f, "sp500_identifiers", lambda: _members().drop(columns="sector"))
    monkeypatch.setattr(panel.sec13f, "thirteen_f_filings", lambda cik, **kw: filings.get(cik, []))

    def table(cik, filing, **kw):
        quarter = filing.period
        rows = holdings[cik][quarter]
        return _table_xml(rows)

    monkeypatch.setattr(panel.sec13f, "information_table_xml", table)
    return holdings


def test_panel_builds_a_json_safe_section_from_the_curated_filers(fake_13f):
    ctx = _ctx()
    out = panel.build(ctx, {})
    json.dumps(out, allow_nan=False)
    assert out["period"] == "2026-06-30" and out["period_label"] == "Q2 2026"
    assert out["prior_period"] == "2026-03-31"
    assert out["filers"]["in_aggregate"] == 2                  # the multi-strategy filer is not fetched
    assert out["filers"]["excluded_style"] == ["Three"]
    assert out["n_funds"] == 2
    assert [r["ticker"] for r in out["crowded"]] == ["AAA", "BBB"]   # ZZZ is outside the S&P 500
    aaa = out["crowded"][0]
    assert aaa["funds"] == 2 and aaa["sector"] == "Information Technology"
    assert aaa["hf_pct"] == pytest.approx(100 * 8000 / 14000, abs=0.01)  # 8000 of the 14000 long dollars
    assert out["outside_sp500"]["names"] == 1
    assert out["outside_sp500"]["value_share_pct"] == pytest.approx(100 * 2000 / 14000, abs=0.01)


def test_panel_changes_use_only_filers_that_reported_both_quarters(fake_13f):
    out = panel.build(_ctx(), {})
    assert out["moves"]["common_funds"] == 2
    adds = {a["ticker"]: a for a in out["moves"]["adds"]}
    assert adds["BBB"]["d_value"] == pytest.approx(800 * 5.0)  # new 800 shares at the latest close
    assert adds["AAA"]["d_value"] == pytest.approx((800 - 500) * 10.0)   # 300 more shares at 10
    assert out["moves"]["cuts"] == []


def test_panel_option_totals_and_no_nan_in_payload(fake_13f):
    out = panel.build(_ctx(), {})
    assert out["options"]["call_rows"] == 0
    assert out["sector_tilt"]


def test_a_failed_filer_is_logged_and_skipped(fake_13f, monkeypatch):
    def broken(cik, **kw):
        raise FetchError(f"CIK{cik}: refused")
    monkeypatch.setattr(panel.sec13f, "thirteen_f_filings", broken)
    ctx = _ctx()
    out = panel.build(ctx, {})
    assert out == {"unavailable": "no 13F-HR for Q2 2026 read from the curated list"}
    assert any(r.status == "error" for r in ctx.log.sources)


def test_missing_identifiers_make_the_section_unavailable(monkeypatch):
    def broken():
        raise FetchError("SSGA: unreachable")
    monkeypatch.setattr(panel.sec13f, "sp500_identifiers", broken)
    out = panel.build(_ctx(), {})
    assert "unavailable" in out and "SSGA" in out["unavailable"]


def test_quarter_labels():
    assert panel.quarter_label("2026-06-30") == "Q2 2026"
    assert panel.quarter_label("2025-12-31") == "Q4 2025"
