import io
import zipfile

from market_recap.compute import segments as C
from market_recap.panels import segments as P
from market_recap.sources import segments as S

HEAD = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"><body>
<div style="display:none"><ix:header><ix:hidden>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="q">June 30, 2026</ix:nonNumeric>
</ix:hidden><ix:resources>
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<xbrli:context id="q"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="cloud"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>
<xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">abc:CloudMember</xbrldi:explicitMember>
<xbrldi:explicitMember dimension="srt:ConsolidationItemsAxis">us-gaap:OperatingSegmentsMember</xbrldi:explicitMember>
</xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="ads"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>
<xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">abc:AdsMember</xbrldi:explicitMember>
</xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="elim"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>
<xbrldi:explicitMember dimension="srt:ConsolidationItemsAxis">us-gaap:IntersegmentEliminationMember</xbrldi:explicitMember>
</xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
</ix:resources></ix:header></div>
"""
BODY = """<p>
<ix:nonFraction name="us-gaap:Revenues" contextRef="q" unitRef="usd" scale="6" format="ixt:num-dot-decimal">1,000</ix:nonFraction>
<ix:nonFraction name="us-gaap:Revenues" contextRef="cloud" unitRef="usd" scale="6" format="ixt:num-dot-decimal"><span>400</span></ix:nonFraction>
<ix:nonFraction name="us-gaap:Revenues" contextRef="ads" unitRef="usd" scale="6">600</ix:nonFraction>
<ix:nonFraction name="us-gaap:OperatingIncomeLoss" contextRef="cloud" unitRef="usd" scale="6" sign="-">25</ix:nonFraction>
<ix:nonFraction name="us-gaap:Revenues" contextRef="elim" unitRef="usd" scale="6">9</ix:nonFraction>
<ix:nonFraction name="us-gaap:OperatingIncomeLoss" contextRef="ads" unitRef="usd" scale="6" format="ixt:fixed-zero">—</ix:nonFraction>
</p></body></html>"""
LABELS = """<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink"><link:labelLink>
<link:loc xlink:type="locator" xlink:href="abc.xsd#abc_CloudMember" xlink:label="loc1"/>
<link:label xlink:type="resource" xlink:label="lab1" xlink:role="http://www.xbrl.org/2003/role/label">Cloud segment [Member]</link:label>
<link:label xlink:type="resource" xlink:label="lab1" xlink:role="http://www.xbrl.org/2003/role/terseLabel">Cloud</link:label>
<link:labelArc xlink:type="arc" xlink:from="loc1" xlink:to="lab1"/>
</link:labelLink></link:linkbase>"""


def _zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def test_inline_filing_keeps_segment_and_total_figures_with_scale_sign_and_labels():
    out = S.parse_filing(_zip({"abc-20260630.htm": HEAD + BODY, "abc-20260630_lab.xml": LABELS}), want_labels=True)
    facts = {(f[0], f[2]): f[6] for f in out["facts"]}
    assert facts[("Revenues", "abc_CloudMember")] == 400e6
    assert facts[("Revenues", "abc_AdsMember")] == 600e6
    assert facts[("OperatingIncomeLoss", "abc_CloudMember")] == -25e6
    assert facts[("OperatingIncomeLoss", "abc_AdsMember")] == 0
    assert out["totals"] == [["Revenues", "2026-04-01", "2026-06-30", 1000e6]]  # the elimination is not a business
    assert out["labels"] == {"abc_CloudMember": "Cloud"}
    assert out["period_end"] == "June 30, 2026"


def test_number_formats():
    assert S._number("1,234.5", "ixt:num-dot-decimal") == 1234.5
    assert S._number("1.234,5", "ixt:num-comma-decimal") == 1234.5
    assert S._number("(12)", None) == 12
    assert S._number("—", None) == 0
    assert S._number("n/a", None) is None


def _filing(accession, filed, facts, totals=(), labels=None):
    return {"accession": accession, "filed": filed, "facts": [list(f) for f in facts],
            "totals": [list(t) for t in totals], "labels": labels or {}}


R = "Revenues"
Y1, Y2 = ("2024-01-01", "2024-12-31"), ("2025-01-01", "2025-12-31")


def test_partition_prefers_the_finest_split_that_reconciles():
    values = {"products": 70, "iphone": 50, "mac": 20, "services": 30}
    assert C.partition(values, 100, set()) == ["iphone", "mac", "services"]
    assert C.partition({"a": 10, "b": 20}, 100, set()) is None
    assert C.partition({"a": 60, "b": 40}, None, set()) is None


def test_newest_filing_wins_and_renamed_members_join_one_line():
    old = _filing("0-1", "2025-02-01", [
        (R, "segment", "x_CloudSegmentMember", None, *Y1, 40), (R, "segment", "x_AdsMember", None, *Y1, 60)],
        [(R, *Y1, 100)], {"x_CloudSegmentMember": "Cloud Segment"})
    new = _filing("0-2", "2026-02-01", [
        (R, "segment", "x_CloudMember", None, *Y2, 50), (R, "segment", "x_AdsMember", None, *Y2, 70),
        (R, "segment", "x_CloudMember", None, *Y1, 45), (R, "segment", "x_AdsMember", None, *Y1, 55)],
        [(R, *Y2, 120), (R, *Y1, 100)], {"x_CloudMember": "Cloud", "x_AdsMember": "Ads"})
    out = C.breakdown([old, new])["segment"]["annual"]
    assert [m["label"] for m in out["members"]] == ["Ads", "Cloud"]
    assert out["revenue"]["x_CloudMember"] == [45, 50]  # the recast year, from the newer filing
    assert [p["label"] for p in out["periods"]] == ["FY2024", "FY2025"]


def test_fourth_quarter_is_the_year_less_nine_months_and_unallocated_profit_is_shown():
    nine, q3, fy = ("2025-01-01", "2025-09-30"), ("2025-07-01", "2025-09-30"), Y2
    facts = []
    for member, (n, q, y, op_n, op_y) in {"a": (60, 20, 90, 6, 10), "b": (30, 10, 40, 3, 4)}.items():
        facts += [(R, "segment", member, None, *nine, n), (R, "segment", member, None, *q3, q), (R, "segment", member, None, *fy, y),
                  ("OperatingIncomeLoss", "segment", member, None, *nine, op_n),
                  ("OperatingIncomeLoss", "segment", member, None, *fy, op_y)]
    totals = [(R, *nine, 90), (R, *q3, 30), (R, *fy, 130), ("OperatingIncomeLoss", *fy, 11)]
    out = C.breakdown([_filing("0-1", "2026-02-01", facts, totals)])["segment"]
    quarterly = out["quarterly"]
    assert [p["end"] for p in quarterly["periods"]] == ["2025-09-30", "2025-12-31"]
    assert quarterly["periods"][-1]["derived"] and quarterly["periods"][-1]["reconciled"]
    assert quarterly["revenue"]["a"][-1] == 30 and quarterly["revenue"]["b"][-1] == 10
    assert quarterly["periods"][-1]["label"] == "Q4 FY2025"
    assert out["annual"]["unallocated"] == [11 - 14]


def test_products_inside_segments_fill_in_with_the_segment_itself():
    facts = [(R, "segment", "svc", None, *Y2, 80), (R, "segment", "cloud", None, *Y2, 20),
             (R, "product", "search", "svc", *Y2, 60), (R, "product", "video", "svc", *Y2, 20)]
    out = C.breakdown([_filing("0-1", "2026-02-01", facts, [(R, *Y2, 100)])])
    product = out["product"]["annual"]
    assert {m["key"] for m in product["members"]} == {"search@svc", "video@svc", "cloud"}
    assert product["revenue"]["cloud"] == [20]


def test_unreconciled_segments_are_kept_but_overlapping_products_are_not():
    facts = [(R, "segment", "a", None, *Y2, 50), (R, "segment", "b", None, *Y2, 30),
             (R, "product", "x", None, *Y2, 70), (R, "product", "y", None, *Y2, 70)]
    out = C.breakdown([_filing("0-1", "2026-02-01", facts, [(R, *Y2, 100)])])
    assert out["segment"]["annual"]["periods"][0]["reconciled"] is False
    assert "product" not in out


def test_fallback_label():
    assert C.fallback_label("goog_GoogleCloudMember") == "Google Cloud"
    assert C.fallback_label("country_US") == "US"


def test_filings_are_read_newest_first_across_companies():
    order = P._order({"A": ["a1", "a2", "a3"], "B": ["b1"], "C": ["c1", "c2"]})
    assert order == ["a1", "b1", "c1", "a2", "c2", "a3"]
