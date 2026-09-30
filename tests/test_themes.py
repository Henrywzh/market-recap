"""THEMES: the new sources' parsers, capex quarters, and the theme helpers."""

from datetime import date

import numpy as np
import pandas as pd

from market_recap.compute import capex as X
from market_recap.compute import png
from market_recap.compute import themes as T
from market_recap.sources import adata, korea_customs, mops, pcpartpicker


# --- sources ---------------------------------------------------------------------

def test_mops_parse_keeps_revenue_and_drops_the_cannot_compute_sentinel():
    payload = {"code": 200, "result": {"yymm": "11508", "data": [
        ["本月", "514,805,337"], ["去年同期", "335,771,691"], ["增減金額", "179,033,646"], ["增減百分比", "53.32"],
        ["本年累計", "3,386,869,575"], ["去年累計", "2,431,982,931"], ["增減金額", "954,886,644"], ["增減百分比", "999999.99"],
        ["備註/營收變化原因說明", "因先進製程產品需求增加所致。"]]}}
    out = mops.parse(payload)
    assert out["month"] == "2026-08" and out["revenue_k"] == 514805337.0 and out["yoy_pct"] == 53.32
    assert out["ytd_yoy_pct"] is None                      # 999999.99 = MOPS could not compute it
    assert mops.months_back(date(2026, 1, 15), 2) == ["2025-12", "2025-11"]


def test_mops_unpublished_month_raises_rather_than_parsing_empty():
    try:
        mops.parse({"code": 406, "message": "查無相符資料", "result": None})
    except mops.NotPublished:
        return
    raise AssertionError("expected NotPublished")


def test_korea_parse_sums_months_and_drops_the_total_row():
    items = [{"priodTitle": "총계", "expUsdAmt": "99"},
             {"priodTitle": "2026.07", "expUsdAmt": "32,724,293"},
             {"priodTitle": "2026.08", "expUsdAmt": "38,235,698"}]
    assert korea_customs.parse(items) == {"2026-07": 32724293.0, "2026-08": 38235698.0}


ADATA_HTML = """<html><head><meta name="description" content="Server DDR5 contract prices +270%, NAND tight."></head>
<body><nav>DRAM Modules</nav><div>SUPPLY TREND
2026-2027 NAND Price Trend & Sufficiency Ratio
Flash Sufficiency: remains tight in 2026.
Price Trend: contract prices peak around late-2026.
2026-2027 DDR5 Price Trend & Sufficiency Ratio
DRAM Sufficiency: structurally tight.
Price Trend: DDR5 prices continue rising. .
e-Catalog</div></body></html>"""


def test_adata_parse_reads_the_headline_and_both_sections():
    out = adata.parse(ADATA_HTML)
    assert out["figures"] == ["+270%"]
    assert out["nand_sufficiency"] == "remains tight in 2026"
    assert out["nand_price"] == "contract prices peak around late-2026"
    assert out["dram_sufficiency"] == "structurally tight"
    assert out["dram_price"] == "DDR5 prices continue rising"


def _chart(heights_by_x: dict[int, int]) -> np.ndarray:
    """A synthetic PCPartPicker chart: background, the gridlines, a black line."""
    img = np.full((484, 1176, 3), 247, dtype=np.uint8)
    for y in pcpartpicker.GRID_ROWS:
        img[y, pcpartpicker.LEFT:pcpartpicker.RIGHT + 1] = pcpartpicker.GRID
    for k in range(17):                                   # month gridlines, 61 px apart, ending Sep 1
        x = 1091 - 61 * k
        if x > pcpartpicker.LEFT:
            img[pcpartpicker.TOP:pcpartpicker.ZERO, x] = pcpartpicker.GRID
    for x, h in heights_by_x.items():
        y = pcpartpicker.ZERO - h
        img[y - 1:y + 2, x] = 0
    return img


def test_pcpartpicker_line_reads_heights_and_dates_from_the_gridlines():
    img = _chart({x: 100 if x < 1091 else 200 for x in range(60, 1149)})
    series = pcpartpicker.read_line(img, date(2026, 9, 30))
    by_day = dict(series)
    assert by_day["2026-09-10"] == 200.0 and by_day["2026-08-01"] == 100.0
    assert series[-1][0] <= "2026-09-30"
    summary = pcpartpicker.summary(series, date(2026, 9, 30))
    assert summary["chg_3m"] == 100.0                     # 100 px -> 200 px


def test_pcpartpicker_rejects_a_chart_whose_gridlines_moved():
    img = _chart({})
    img[94] = 247                                         # one price gridline gone
    try:
        pcpartpicker.read_line(img, date(2026, 9, 30))
    except pcpartpicker.ChartLayoutChanged:
        return
    raise AssertionError("expected ChartLayoutChanged")


def test_pcpartpicker_images_come_with_their_date_and_title():
    html = 'var images = [{ src: "//cdna.pcpartpicker.com/static/forever/images/trends/2026.09.30.gbp.ram.ddr5.6000.2x16384.abc.png", thumb: "x", heading: "PCPartPicker Price Trends", title: "DDR5\\u002D6000 2x16GB" }];'
    [item] = pcpartpicker.images(html)
    assert item["title"] == "DDR5-6000 2x16GB" and item["image_date"] == "2026-09-30"


def test_png_decoder_reads_an_rgb_image():
    import struct
    import zlib
    rows = b"".join(b"\x00" + bytes([10, 20, 30] * 2) for _ in range(2))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    data = png.SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    assert png.decode(data).tolist() == [[[10, 20, 30]] * 2] * 2


# --- capex ------------------------------------------------------------------------

def _facts(rows):
    return {"facts": {"us-gaap": {"PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": rows}}}}}


def test_capex_quarters_come_from_year_to_date_differences():
    rows = [
        {"start": "2025-07-01", "end": "2025-09-30", "val": 19.0, "form": "10-Q", "filed": "2025-10-29"},
        {"start": "2025-07-01", "end": "2025-12-31", "val": 49.0, "form": "10-Q", "filed": "2026-01-28"},
        {"start": "2025-07-01", "end": "2026-03-31", "val": 80.0, "form": "10-Q", "filed": "2026-04-29"},
        {"start": "2025-07-01", "end": "2026-06-30", "val": 116.0, "form": "10-K", "filed": "2026-07-29"},
    ]
    series = X.quarterly(_facts(rows), "PaymentsToAcquirePropertyPlantAndEquipment")
    assert [(r["end"], r["value"], r["derived"]) for r in series] == [
        ("2025-09-30", 19.0, False), ("2025-12-31", 30.0, True), ("2026-03-31", 31.0, True), ("2026-06-30", 36.0, True)]


def test_capex_growth_is_against_the_quarter_a_year_earlier():
    series = [{"end": "2025-06-30", "value": 10.0}, {"end": "2026-06-30", "value": 21.0}]
    assert X.with_growth(series)[-1]["yoy_pct"] == 110.0


# --- theme helpers ------------------------------------------------------------------

def test_next_report_is_projected_from_the_company_rhythm():
    past = [date(2025, 10, 29), date(2026, 1, 28), date(2026, 4, 29), date(2026, 7, 29)]
    assert T.project_next(past, date(2026, 9, 29)) == date(2026, 10, 28)    # median gap 91 days
    assert T.project_next([date(2026, 7, 29)], date(2026, 9, 29)) is None


def test_monthly_due_dates_and_lateness():
    assert T.monthly_due("2026-08", 10, date(2026, 9, 30)) == {"month": "2026-09", "due": "2026-10-10", "late": False}
    assert T.monthly_due("2026-11", 15, date(2027, 1, 20))["late"] is True    # December due 15 January


def test_basket_leaves_the_bellwether_out():
    frame = pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0], "C": [5.0, 6.0]})
    assert T.basket_excess(frame, ["A", "B", "C"], leave_out="A").tolist() == [4.0, 5.0]


def test_monthly_yoy_fills_only_where_the_source_gave_none():
    rows = [{"month": "2025-08", "v": 10.0}, {"month": "2026-08", "v": 30.0}, {"month": "2026-07", "v": 5.0, "yoy_pct": 7.0}]
    out = {r["month"]: r["yoy_pct"] for r in T.yoy_monthly(rows, "v")}
    assert out == {"2025-08": None, "2026-08": 200.0, "2026-07": 7.0}
