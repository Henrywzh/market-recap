"""DRAMeXchange homepage parser. Synthetic prices only; the live page is not stored."""

from datetime import date

from market_recap.sources.dramexchange import archive, parse_tables


PAGE = """
<html><body>
<div>DRAM Spot Price</div>
<span class="tab_time">Last Update: Oct.04 2026 18:10 (GMT+8)</span>
<table><tr><td>wrapper</td><td>
<table>
<tr><th>Item</th><th>Session High</th><th>Session Low</th><th>Session Average</th><th>Session Change</th><th>History</th></tr>
<tr><td>DDR5 16Gb</td><td>10.00</td><td>8.00</td><td>9.500</td><td>1.25 %</td><td></td></tr>
<tr><td>DDR4 16Gb</td><td>4</td><td>3</td><td>3.5</td><td>-0.50 %</td><td></td></tr>
</table>
</td></tr></table>
<div>Module Spot Price</div>
<span class="tab_time">Last Update: Sep.28 2026 14:40 (GMT+8)</span>
<table>
<tr><th>Item</th><th>Session Average</th><th>Average Change</th></tr>
<tr><td>DDR5 UDIMM 16GB</td><td>200</td><td>0.00 %</td></tr>
</table>
</body></html>
"""


def test_homepage_tables_keep_the_session_average_and_its_date():
    tables = parse_tables(PAGE)
    assert [table["section"] for table in tables] == ["DRAM spot", "Module spot"]
    assert tables[0]["updated"] == "Oct.04 2026 18:10 (GMT+8)"
    assert tables[0]["rows"][0]["session_average"] == 9.5
    assert tables[0]["rows"][0]["session_change_pct"] == 1.25
    assert tables[0]["rows"][1]["session_change_pct"] == -0.5
    assert tables[1]["rows"][0]["item"] == "DDR5 UDIMM 16GB"


def test_archive_writes_a_day_file(tmp_path, monkeypatch):
    monkeypatch.setattr("market_recap.sources.dramexchange.ARCHIVE_DIR", tmp_path)
    path = archive(PAGE, date(2026, 10, 4))
    assert path.name == "2026-10-04.json"
    assert (tmp_path / "latest.json").read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_ssd_and_sibling_nested_tables_keep_their_own_dates():
    page = PAGE.replace("</body>", """
    <div>SSD Street Price</div><span>LastUpdate:Sep.24 2026 11:30, (GMT+8)</span>
    <table><tr><th>Brand</th><th>Interface</th><th>Series</th><th>Capacity</th><th>High</th><th>Low</th><th>Avg.</th><th>Change</th></tr>
    <tr><td>Example</td><td>PCIe</td><td>Model</td><td>1TB</td><td>12</td><td>8</td><td>10</td><td>-1.5%</td></tr></table>
    </body>""")
    tables = parse_tables(page)
    assert len(tables) == 3
    assert tables[-1]["section"] == "SSD street"
    assert tables[-1]["updated"] == "Sep.24 2026 11:30, (GMT+8)"
    assert tables[-1]["rows"][0]["item"] == "Example · PCIe · Model · 1TB"
    assert tables[-1]["rows"][0]["average"] == 10
    assert tables[-1]["rows"][0]["change_pct"] == -1.5
