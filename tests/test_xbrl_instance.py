"""Company facts read from a filing's own XBRL instance, and the backfill that uses them."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import validate
from market_recap.sources import sec, xbrl_instance

INSTANCE = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:us-gaap="http://fasb.org/us-gaap/2025"
  xmlns:dei="http://xbrl.sec.gov/dei/2025"
  xmlns:co="http://example.com/co">
  <xbrli:context id="q"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="end"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="seg"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
    <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">co:Cards</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
  <xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
    <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
  <dei:DocumentType contextRef="q">10-Q</dei:DocumentType>
  <dei:DocumentFiscalYearFocus contextRef="q">2026</dei:DocumentFiscalYearFocus>
  <dei:DocumentFiscalPeriodFocus contextRef="q">Q2</dei:DocumentFiscalPeriodFocus>
  <dei:EntityCommonStockSharesOutstanding contextRef="end" unitRef="shares" decimals="0">1677436783</dei:EntityCommonStockSharesOutstanding>
  <us-gaap:NetIncomeLoss contextRef="q" unitRef="usd" decimals="-6">5831000000</us-gaap:NetIncomeLoss>
  <us-gaap:NetIncomeLoss contextRef="seg" unitRef="usd" decimals="-6">999</us-gaap:NetIncomeLoss>
  <us-gaap:EarningsPerShareDiluted contextRef="q" unitRef="usdPerShare" decimals="2">3.15</us-gaap:EarningsPerShareDiluted>
  <us-gaap:Goodwill contextRef="end" unitRef="usd" decimals="-6">19012000000</us-gaap:Goodwill>
  <us-gaap:Revenues contextRef="q" unitRef="usd" xsi:nil="true"/>
  <co:CustomMeasure contextRef="q" unitRef="usd" decimals="0">7</co:CustomMeasure>
</xbrli:xbrl>
"""


def _rows():
    return xbrl_instance.facts_from_instance(INSTANCE, accession="0000000001-26-000001", filed="2026-08-06")


def test_instance_keeps_only_undimensioned_facts_in_companyfacts_shape():
    rows = _rows()
    income = rows["us-gaap"]["NetIncomeLoss"]["USD"]
    assert income == [{
        "start": "2026-04-01", "end": "2026-06-30", "val": 5831000000,
        "accn": "0000000001-26-000001", "fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-08-06",
    }]
    assert rows["us-gaap"]["EarningsPerShareDiluted"]["USD/shares"][0]["val"] == 3.15
    # A balance-sheet fact is an instant: an end date and no start.
    assert rows["us-gaap"]["Goodwill"]["USD"][0] == {
        "end": "2026-06-30", "val": 19012000000, "accn": "0000000001-26-000001",
        "fy": 2026, "fp": "Q2", "form": "10-Q", "filed": "2026-08-06"}
    assert rows["dei"]["EntityCommonStockSharesOutstanding"]["shares"][0]["val"] == 1677436783
    # Nil facts, another company's extension tags and dimensional slices are left out.
    assert "Revenues" not in rows["us-gaap"]
    assert "CustomMeasure" not in rows["us-gaap"]


def test_merge_adds_rows_without_duplicating_or_mutating():
    existing = {"entityName": "Co", "facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"start": "2025-04-01", "end": "2025-06-30", "val": 1, "accn": "old", "form": "10-Q", "filed": "2025-08-01"}]}}}}}
    merged = xbrl_instance.merge_into(existing, _rows())
    again = xbrl_instance.merge_into(merged, _rows())
    assert len(merged["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]) == 2
    assert len(again["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]) == 2
    assert "dei" in merged["facts"]
    assert len(existing["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"]) == 1


def _filing(accession, filed, hours_ago):
    return sec.LatestFiling("10-Q", accession, filed, datetime.now(timezone.utc) - timedelta(hours=hours_ago))


def _stale_facts():
    return {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 1, "accn": "k", "form": "10-K", "filed": "2026-02-20"}]}}},
        # An 8-K's cover facts are newer than the 10-K and must not hide the missing 10-Qs.
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2026-09-01", "val": 5, "accn": "8k", "form": "8-K", "filed": "2026-09-22"}]}}}}}


def test_backfill_reads_every_statement_filing_company_facts_lack(monkeypatch):
    q1, q2 = _filing("a-q1", "2026-05-07", 3000), _filing("a-q2", "2026-08-06", 1000)
    monkeypatch.setattr(sec, "_checked", {1: {"latest": q2}})
    monkeypatch.setattr(sec, "_backfilled", {})
    monkeypatch.setattr(sec, "_unprocessed", {})
    monkeypatch.setattr(sec, "_statement_filings", lambda block: [q2, q1])
    monkeypatch.setattr(sec, "_recent_block", lambda cik, **kw: {})
    seen = []

    def fake(cik, filing):
        seen.append(filing.accession)
        return {"us-gaap": {"NetIncomeLoss": {"USD": [{"start": "2026-01-01", "end": "2026-06-30", "val": 9,
                                                       "accn": filing.accession, "form": "10-Q", "filed": filing.filed}]}}}

    monkeypatch.setattr(sec, "instance_facts", fake)
    out = sec._backfill(1, _stale_facts())
    assert seen == ["a-q1", "a-q2"]  # oldest first
    assert sec._carries(out, "a-q1") and sec._carries(out, "a-q2")
    assert sec.filing_check()["backfilled"] == {"0000000001": "a-q1, a-q2"}


def test_backfill_leaves_a_filing_still_inside_the_processing_margin(monkeypatch):
    fresh = _filing("a-new", "2026-10-05", 1)
    monkeypatch.setattr(sec, "_checked", {1: {"latest": fresh}})
    monkeypatch.setattr(sec, "_backfilled", {})
    monkeypatch.setattr(sec, "_statement_filings", lambda block: [fresh])
    monkeypatch.setattr(sec, "_recent_block", lambda cik, **kw: {})
    monkeypatch.setattr(sec, "instance_facts", lambda *a: (_ for _ in ()).throw(AssertionError("must not fetch")))
    facts = _stale_facts()
    assert sec._backfill(1, facts) is facts


def test_backfill_reports_a_filing_it_cannot_read_instead_of_guessing(monkeypatch):
    q2 = _filing("a-q2", "2026-08-06", 1000)
    monkeypatch.setattr(sec, "_checked", {1: {"latest": q2}})
    monkeypatch.setattr(sec, "_backfilled", {})
    monkeypatch.setattr(sec, "_unprocessed", {})
    monkeypatch.setattr(sec, "_statement_filings", lambda block: [q2])
    monkeypatch.setattr(sec, "_recent_block", lambda cik, **kw: {})
    monkeypatch.setattr(sec, "instance_facts", lambda *a: (_ for _ in ()).throw(LookupError("no XBRL instance")))
    facts = _stale_facts()
    assert sec._backfill(1, facts) is facts
    assert "no XBRL instance" in sec.filing_check()["unprocessed"]["0000000001"]


def test_backfill_does_nothing_when_company_facts_carry_the_latest_filing(monkeypatch):
    q2 = _filing("k", "2026-08-06", 1000)
    monkeypatch.setattr(sec, "_checked", {1: {"latest": q2}})
    monkeypatch.setattr(sec, "instance_facts", lambda *a: (_ for _ in ()).throw(AssertionError("must not fetch")))
    facts = _stale_facts()
    assert sec._backfill(1, facts) is facts


def test_backfill_skips_an_ifrs_filer(monkeypatch):
    amendment = _filing("a-20fa", "2026-05-22", 3000)
    monkeypatch.setattr(sec, "_checked", {1: {"latest": amendment}})
    monkeypatch.setattr(sec, "instance_facts", lambda *a: (_ for _ in ()).throw(AssertionError("must not fetch")))
    facts = {"facts": {"ifrs-full": {}, "dei": {}}}
    assert sec._backfill(1, facts) is facts


def test_validate_warns_on_an_unreadable_filing_and_notes_a_backfilled_one():
    manifest = {"sec_filings": {"unprocessed": {"0000831001": "10-Q x: no XBRL instance"},
                                "backfilled": {"0000831001": "0000831001-26-000045"}}}
    findings = validate._check_sec_filings(manifest)
    assert [(f.severity, f.check) for f in findings] == [("warning", "sec_filings"), ("notice", "sec_filings")]
    assert validate._check_sec_filings({}) == []
    # Many filers lagging is one line, not one line each.
    many = {"sec_filings": {"backfilled": {f"{n:010d}": "acc" for n in range(61)}}}
    (line,) = validate._check_sec_filings(many)
    assert "61 filers" in line.detail


def test_backfill_ignores_an_amendment_with_no_statements_but_not_an_original(monkeypatch):
    def run(form):
        filing = sec.LatestFiling(form, "a-x", "2026-05-22", datetime.now(timezone.utc) - timedelta(hours=3000))
        monkeypatch.setattr(sec, "_checked", {1: {"latest": filing}})
        monkeypatch.setattr(sec, "_unprocessed", {})
        monkeypatch.setattr(sec, "_backfilled", {})
        monkeypatch.setattr(sec, "_statement_filings", lambda block: [filing])
        monkeypatch.setattr(sec, "_recent_block", lambda cik, **kw: {})
        monkeypatch.setattr(sec, "instance_facts", lambda *a: {"dei": {}})
        facts = _stale_facts()
        assert sec._backfill(1, facts) is facts
        return dict(sec._unprocessed)

    assert run("20-F/A") == {}
    assert "no US-GAAP facts" in run("10-Q")[1]
