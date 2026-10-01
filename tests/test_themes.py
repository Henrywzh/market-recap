"""THEMES: the new sources' parsers, capex quarters, and the theme helpers."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

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


# --- earnings dates for foreign and heavy filers ---------------------------------------

def test_six_k_results_are_recognised_by_document_name():
    from market_recap.compute import evidence as V
    recent = {"form": ["6-K", "6-K", "6-K", "8-K"],
              "primaryDocument": ["tsm-revenue20260910.htm", "tsm-20260716x6k.htm", "tsm-fsx20260814x6k.htm", "x.htm"],
              "filingDate": ["2026-09-10", "2026-07-16", "2026-08-14", "2026-07-01"]}
    out = V.six_k_announcements(recent, r"^tsm-\d{8}x6k\.htm$", "bmo")
    assert out == [{"date": "2026-07-16", "time": None, "timing": "bmo"}]


def test_older_submission_pages_are_read_until_enough(monkeypatch, tmp_path):
    import json
    from market_recap import cache
    from market_recap.sources import sec
    monkeypatch.setattr(cache, "path_for", lambda ns, name, suffix: tmp_path / f"{ns.replace('/', '_')}-{name}{suffix}")
    main = {"filings": {"recent": {"form": ["8-K"], "items": ["2.02"], "filingDate": ["2026-07-14"]},
                        "files": [{"name": "p1.json", "filingFrom": "2026-01-01", "filingTo": "2026-06-30"},
                                  {"name": "p2.json", "filingFrom": "2025-01-01", "filingTo": "2025-12-31"}]}}
    pages = {"p1.json": {"form": ["8-K", "424B2"], "items": ["2.02", ""], "filingDate": ["2026-04-14", "2026-04-10"]},
             "p2.json": {"form": ["8-K"], "items": ["2.02"], "filingDate": ["2025-10-14"]}}
    asked = []

    def fake_get(url, timeout):
        asked.append(url)
        name = url.rsplit("/", 1)[-1]
        return json.dumps(pages[name] if name in pages else main)
    monkeypatch.setattr(sec, "_get", fake_get)
    block = sec.submissions_until(1, lambda b: b["items"].count("2.02") >= 2, since="2024-01-01")
    assert block["filingDate"] == ["2026-07-14", "2026-04-14", "2026-04-10"]      # stopped after the first page
    assert not any(u.endswith("p2.json") for u in asked)


DART_HTML = """<table><tbody>
<tr><td>1</td><td>유 SK하이닉스</td><td>연결재무제표기준영업(잠정)실적(공정공시)</td><td>SK하이닉스</td><td>2026.07.29</td>
<td><a href="/dsaf001/main.do?rcpNo=20260729800013">v</a></td></tr>
<tr><td>2</td><td>유 SK하이닉스</td><td>[기재정정] 연결재무제표기준영업(잠정)실적(공정공시)</td><td>SK하이닉스</td><td>2026.07.29</td>
<td><a href="/dsaf001/main.do?rcpNo=20260729800099">v</a></td></tr>
</tbody></table>"""


def test_dart_results_drop_corrections():
    from market_recap.sources import dart
    rows = dart.parse(DART_HTML)
    assert [(r["date"], r["rcp"]) for r in rows] == [("2026-07-29", "20260729800013")]


def test_motie_release_figures():
    from market_recap.sources import motie
    text = ("보도시점 2026. 9. 1.(화) 11:00\n- 반도체 수출 467억 달러로 역대 최대 기록 경신\n"
            "* 8월 수출 982.5억 달러(+68.7%), 수입 635.1억 달러(+22.5%)\n"
            "(IT) 반도체 수출(466.5억 달러, +209.0%)은 구글·아마존 등")
    out = motie.parse_text(text)
    assert out == {"released": "2026-09-01", "released_time": "11:00", "semis_bn": 46.65, "semis_yoy_pct": 209.0,
                   "total_bn": 98.25, "total_yoy_pct": 68.7}
    assert motie.parse_text("반도체 수출(80.2억 달러, △12.5%)")["semis_yoy_pct"] == -12.5
    # The other wordings; the exact figure beats the rounded item list, and a
    # half-year or annual figure larger than the month's exports is skipped.
    late_2025 = ("* 수출 증가 품목(억 달러, %) : 반도체1,734(+22.2)\n12월 수출은 전년 대비 13.4% 증가한 696억 달러\n"
                 "* 수출 증가 품목(억 달러, %) : 반도체208(+43.2)\n우리 최대 수출품목인 반도체 수출은 43.2% 증가한 208억 달러를 기록")
    assert motie.parse_text(late_2025) == {"total_bn": 69.6, "total_yoy_pct": 13.4, "semis_bn": 20.8, "semis_yoy_pct": 43.2}
    assert motie.parse_text("* 증가품목 수출액·증감률(억 달러, %) : 반도체 151.0(+27.1), 자동차 55.0(+8.6)")["semis_bn"] == 15.1
    assert motie.parse_text("반도체 수출은 3.0% 감소한 96억 달러로")["semis_yoy_pct"] == -3.0
    html = ('<a onclick="article.view(\'172145\'); return false;">2026년 8월 수출입동향</a>'
            '<a onclick="article.view(\'172196\'); return false;">2026년 8월 정보통신산업(ICT) 수출입 동향</a>'
            '<a onclick="article.view(\'171986\'); return false;">2026년 6월 및 상반기 수출입 동향</a>'
            '<a onclick="article.view(\'171403\'); return false;">2025년 연간 및 12월 수출입 동향</a>')
    assert motie.releases(html) == [("2026-08", "172145"), ("2026-06", "171986"), ("2025-12", "171403")]


def test_release_guidance_quotes_forward_capex_sentences_only():
    from market_recap.sources import releases
    text = ("Revenue was $47.5 billion. We anticipate 2026 capital expenditures, including principal payments on "
            "finance leases, to be in the range of $130-145 billion, narrowed from our prior outlook of $125-145 billion. "
            "We believe this supplemental presentation of capital expenditures is useful because it is used when forecasting expected capital expenditures. "
            "Less: purchases of property and equipment (23,953) (27,851) (35,674) (44,924).")
    assert releases.guidance(text) == ["We anticipate 2026 capital expenditures, including principal payments on finance "
                                        "leases, to be in the range of $130-145 billion, narrowed from our prior outlook of $125-145 billion."]
    assert releases.first(r"Data Center revenue of \$([\d.]+) billion[^.]*?up ([\d,]+)% from a year ago",
                          "• Data Center revenue of $89.0 billion, up 117% from a year ago") == ("89.0", "117")


def test_heatmap_sums_index_weight_by_sector_and_day():
    from market_recap.panels import themes as panel
    catalysts = {"events": [
        {"event_type": "earnings", "date": "2026-10-13", "sector": "Financials", "symbol": "JPM", "index_weights": {"SPX": 1.4}},
        {"event_type": "earnings", "date": "2026-10-13", "sector": "Financials", "symbol": "GS", "index_weights": {"SPX": 0.4}},
        {"event_type": "earnings", "date": "2026-10-14", "sector": "Health Care", "symbol": "JNJ", "index_weights": {"SPX": 1.0}},
        {"event_type": "earnings", "date": "2026-12-01", "sector": "Health Care", "symbol": "X", "index_weights": {"SPX": 1.0}},
    ]}
    out = panel._heatmap(catalysts, date(2026, 9, 29), 21)
    assert out["dates"] == ["2026-10-13", "2026-10-14"]
    fin = next(r for r in out["rows"] if r["sector"] == "Financials")
    assert fin["cells"][0] == {"w": 1.8, "top": ["JPM", "GS"], "n": 2} and fin["cells"][1] is None
    assert out["day_totals"] == [1.8, 1.0]


# --- ENERGY & HOUSING -----------------------------------------------------------------

EIA_PAGE = """<table><tr><td class="B6">2026-Aug </td><td class="B5">08/28</td><td class="B3">420,100</td>
<td class="B5"></td><td class="B3"></td></tr>
<tr><td class="B6">2026-Sep </td><td class="B5">09/04</td><td class="B3">424,069</td><td class="B5">09/11</td><td class="B3">423,429</td></tr></table>"""


def test_eia_history_page_parses_week_ending_dates():
    from market_recap.sources import eia

    s = eia.parse(EIA_PAGE)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-08-28", "2026-09-04", "2026-09-11"]
    assert s.iloc[-1] == 423429.0


def test_eia_seasonal_compares_the_same_week_over_five_prior_years():
    from market_recap.sources import eia

    weeks = pd.date_range("2018-01-05", "2026-09-25", freq="W-FRI")
    s = pd.Series([100.0 + (d.year - 2018) * 10 for d in weeks], index=weeks)
    f = eia.seasonal(s)
    last = f.iloc[-1]
    assert last["avg5"] == pytest.approx(sum(100.0 + (y - 2018) * 10 for y in range(2021, 2026)) / 5)
    assert last["change"] == 0.0
    assert pd.isna(f.loc["2021-03-05", "avg5"])          # only three prior years: no average
    assert eia.next_release(date(2026, 9, 30), 2) == date(2026, 10, 7)   # Wednesday after a Wednesday


def test_sensitivity_and_crack():
    driver = pd.Series(np.random.default_rng(0).normal(0, 1, 300), index=pd.bdate_range("2025-01-01", periods=300))
    excess = 0.5 * driver + 0.01
    got = T.sensitivity(excess, driver)
    assert got["beta"] == pytest.approx(0.5) and got["corr"] == pytest.approx(1.0) and got["n"] == 252
    assert T.sensitivity(excess.iloc[:100], driver.iloc[:100]) is None
    idx = pd.bdate_range("2026-01-01", periods=2)
    crack = T.crack_321(pd.Series([90.0, 92.0], idx), pd.Series([3.0, 3.1], idx), pd.Series([4.0, 4.2], idx))
    assert crack.iloc[0] == pytest.approx((2 * 3.0 * 42 + 4.0 * 42 - 270) / 3)


def test_fred_release_lags_date_each_observation():
    from market_recap.panels import themes as P
    # H.8: the week ending Wednesday 9/16 is published Friday 9/25.
    assert P._available(pd.Timestamp("2026-09-16"), ("days", 9)) == "2026-09-25"
    # Consumer credit for July: about the 8th, two months on; December rolls the year.
    assert P._available(pd.Timestamp("2026-07-01"), ("months", 2, 8)) == "2026-09-08"
    assert P._available(pd.Timestamp("2026-12-01"), ("months", 1, 16)) == "2027-01-16"
    # Sentiment's final reading is the same month.
    assert P._available(pd.Timestamp("2026-08-01"), ("months", 0, 28)) == "2026-08-28"


def test_series_driver_turns_levels_into_year_on_year_and_thins_daily():
    from market_recap.panels import themes as P
    weekly = {"id": "TOTLL", "label": "Loans ($bn)", "unit": "bn", "freq": "weekly",
              "dates": [f"w{i}" for i in range(60)], "available": [f"a{i}" for i in range(60)],
              "values": [100.0] * 4 + [110.0] * 56}
    d = P._series_driver(weekly, ["banks"], "yoy")
    assert d["label"] == "Loans, y/y" and d["unit"] == "pct"
    assert d["points"][-1]["value"] == 0.0 and d["points"][0]["value"] == 10.0   # first with a base: w52 vs w0
    daily = {"id": "T10Y2Y", "label": "2s10s", "unit": "rate", "freq": "daily",
             "dates": [f"d{i:02d}" for i in range(12)], "available": [f"d{i:02d}" for i in range(12)],
             "values": [float(i) for i in range(12)]}
    d = P._series_driver(daily, ["banks"], "pp")
    assert [p["value"] for p in d["points"]] == [1.0, 6.0, 11.0]                # every fifth session, ending on the last


def test_release_study_scores_the_session_of_each_release_against_trend():
    sessions = pd.bdate_range("2024-01-01", periods=400)
    excess = pd.Series(0.1, index=sessions)
    days = sessions[20::20][:18]
    values = [100.0]
    for i in range(18):
        values.append(values[-1] * (1.02 if i % 2 else 1.0))          # alternating +2% and flat prints
    releases = pd.DataFrame({"date": days - pd.Timedelta(days=30), "released": days, "value": values[1:], "prior": values[:-1]})
    for day, v, p in zip(days, values[1:], values[:-1]):
        excess[day] = 1.0 if v > p else -1.0                           # the proxy follows the print
    out = T.release_study(releases, excess, headline="pct")
    assert out["n"] == 18 and out["scored"] == 18 - 6
    assert out["attention"] == 10.0                                    # |1.0| on release days against |0.1|
    assert out["up_above"] == 100 and out["up_below"] == 0
    assert out["corr"] > 0.9                                          # ranks: the flat prints tie
    assert out["recent"][0]["released"] == days[-1].strftime("%Y-%m-%d") and len(out["recent"]) == 8


def test_alfred_releases_take_the_prior_as_known_on_the_day():
    from market_recap.sources import alfred
    t = pd.Timestamp
    frame = pd.DataFrame([
        # March first printed 100 on 4/15, revised to 102 on 5/15.
        {"date": t("2026-03-01"), "value": 100.0, "realtime_start": t("2026-04-15"), "realtime_end": t("2026-05-14")},
        {"date": t("2026-03-01"), "value": 102.0, "realtime_start": t("2026-05-15"), "realtime_end": t("2262-04-01")},
        {"date": t("2026-04-01"), "value": 103.0, "realtime_start": t("2026-05-15"), "realtime_end": t("2262-04-01")},
    ])
    out = alfred.releases(frame)
    april = out[out["date"] == t("2026-04-01")].iloc[0]
    assert april["released"] == t("2026-05-15") and april["prior"] == 102.0     # the revised March, as the release said
    march = out[out["date"] == t("2026-03-01")].iloc[0]
    assert march["value"] == 100.0 and pd.isna(march["prior"])


def test_loan_officer_survey_expected_the_monday_after_the_quarter_closing_fomc():
    from market_recap.panels import themes as P
    events = {"events": [{"date": "2026-09-16", "title": "FOMC decision (statement)"},
                         {"date": "2026-10-28", "title": "FOMC press conference"},
                         {"date": "2026-10-28", "title": "FOMC decision (statement)"}]}
    assert P.sloos_expected(events, date(2026, 10, 1)) == "2026-11-02"
    assert P.sloos_expected(events, date(2026, 11, 2)) is None


def test_as_published_reads_the_year_earlier_value_as_known_on_release_day():
    from market_recap.sources import alfred
    t = pd.Timestamp
    end = t("2262-04-01")
    frame = pd.DataFrame([
        {"date": t("2025-08-01"), "value": 100.0, "realtime_start": t("2025-09-16"), "realtime_end": t("2026-09-27")},
        {"date": t("2025-08-01"), "value": 95.0, "realtime_start": t("2026-09-28"), "realtime_end": end},   # annual revision
        {"date": t("2026-08-01"), "value": 106.0, "realtime_start": t("2026-09-16"), "realtime_end": t("2026-09-27")},
        {"date": t("2026-08-01"), "value": 101.0, "realtime_start": t("2026-09-28"), "realtime_end": end},
    ])
    row = alfred.as_published(frame, "monthly").set_index("date").loc[t("2026-08-01")]
    assert row["released"] == t("2026-09-16") and row["value"] == 106.0 and row["year_ago"] == 100.0


def test_pcpartpicker_is_skipped_not_failed_on_the_cloud_build(monkeypatch):
    from market_recap.panels import themes as P
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(P.pcpartpicker, "fetch", lambda kind: pytest.fail("the cloud build must not ask PCPartPicker"))
    assert P._pcpp() == {"skipped": P.PCPP_SKIP_REASON}


def test_tv_surprises_take_actual_less_forecast_on_the_new_york_day():
    rows = [{"title": "Retail Sales MoM", "date": "2026-09-16T12:30:00.000Z", "actual": 1.2, "forecast": 0.8},
            {"title": "Retail Sales Ex Autos MoM", "date": "2026-09-16T12:30:00.000Z", "actual": 1.0, "forecast": 0.5},
            {"title": "Housing Starts", "date": "2016-10-19T12:30:00.000Z", "actual": 1047, "forecast": 1175},
            {"title": "Retail Sales MoM", "date": "2026-08-14T12:30:00.000Z", "actual": 0.5, "forecast": None}]
    retail = T.tv_surprises(rows, r"^Retail Sales MoM$", "diff")
    assert len(retail) == 1 and retail["surprise"].iloc[0] == pytest.approx(0.4)
    assert retail["released"].iloc[0] == pd.Timestamp("2026-09-16")
    starts = T.tv_surprises(rows, r"^Housing Starts$", "pct")
    assert starts["surprise"].iloc[0] == pytest.approx((1047 / 1175 - 1) * 100)


def test_release_study_scores_on_forecasts_when_they_cover_most_releases():
    sessions = pd.bdate_range("2024-01-01", periods=400)
    excess = pd.Series(0.0, index=sessions)
    days = sessions[20::20][:18]
    releases = pd.DataFrame({"date": days - pd.Timedelta(days=30), "released": days,
                             "value": [101.0] * 18, "prior": [100.0] * 18})        # a flat +1% every month: no trend signal
    beats = [1.0 if i % 2 else -1.0 for i in range(18)]
    for day, b in zip(days, beats):
        excess[day] = b                                                            # the proxy follows the beat
    forecasts = pd.DataFrame({"released": days, "actual": 0.0, "forecast": 0.0, "surprise": beats})
    out = T.release_study(releases, excess, headline="pct", forecasts=forecasts)
    assert out["basis"] == "forecast" and out["with_forecast"] == 18
    assert out["up_above"] == 100 and out["up_below"] == 0
    assert out["recent"][0]["vs_forecast"] == beats[-1]
    sparse = forecasts.iloc[:5]
    assert T.release_study(releases, excess, headline="pct", forecasts=sparse)["basis"] == "trend"
