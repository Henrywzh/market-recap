"""Public memory stand-ins: Korea HS breakouts, BLS indexes, PCPartPicker feed."""

from datetime import date

import pandas as pd
import pytest
import runpy

from market_recap.compute import themes as T
from market_recap.sources import korea_customs, pcpartpicker
from market_recap.panels import themes
from market_recap.config import REPO_ROOT
from market_recap.sources.http import FetchError


def test_customs_zero_is_real_and_partial_exports_are_missing():
    rows = korea_customs.parse_rows([
        {"priodTitle": "2026.07", "expUsdAmt": 0, "expTtwg": 1},
        {"priodTitle": "2026.08", "expUsdAmt": 100, "expTtwg": 1},
        {"priodTitle": "2026.08", "expUsdAmt": "-", "expTtwg": 1},
    ])
    assert rows[0]["exports_k"] == 0 and rows[0]["usd_per_kg"] == 0
    assert rows[1]["exports_k"] is None and rows[1]["usd_per_kg"] is None


def test_chip_prices_use_full_history_for_yoy_and_keep_missing_months(monkeypatch):
    frame = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=80, freq="MS"), "value": 100.0})
    frame.loc[frame.date == "2025-05-01", "value"] = float("nan")
    monkeypatch.setattr(themes.fred, "fetch_series", lambda sid: (frame, "https://example.test"))
    out = themes._chip_prices({"chip_prices": [{"id": "TEST", "label": "Test"}]}, date(2026, 7, 1))
    months = out["series"][0]["months"]
    assert len(months) == 60 and months[0]["yoy_pct"] == 0.0
    assert months[-1]["month"] == "2026-07"
    assert next(row for row in months if row["month"] == "2025-05")["value"] is None
    assert next(row for row in months if row["month"] == "2026-05")["yoy_pct"] is None


def test_pcpartpicker_family_indexes_align_calendar_days():
    out = pcpartpicker._aggregate("memory", [
        {"title": "DDR5 A", "image_date": "2026-09-28", "series": [("2026-09-14", 10), ("2026-09-21", 20), ("2026-09-28", 30)]},
        {"title": "DDR5 B", "image_date": "2026-09-28", "series": [("2026-09-14", 10), ("2026-09-28", 10)]},
    ])
    assert out["families"]["DDR5"]["index"] == {
        "dates": ["2026-09-14", "2026-09-21", "2026-09-28"], "values": [100.0, 200.0, 200.0]}
    assert out["rows"][1]["index"]["values"][1] is None


def test_customs_query_uses_honest_http_session_and_rejects_repeated_pages(monkeypatch):
    from market_recap.sources import http
    from market_recap.config import USER_AGENT
    import httpx
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200)
        return httpx.Response(200, json={"items": [{"priodTitle": "2026.08"}] * korea_customs.PAGE_ROWS})
    original = http.httpx.Client
    monkeypatch.setattr(http.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(RuntimeError, match="repeated a page"):
        korea_customs._query("2026-08", "2026-08", "854232")
    assert all(request.headers["User-Agent"] == USER_AGENT for request in requests)


def test_forced_pcpartpicker_refresh_does_not_reuse_a_failed_fetch(monkeypatch, tmp_path):
    cached = tmp_path / "memory.html"
    cached.write_text("old chart page", encoding="utf-8")
    monkeypatch.setattr(pcpartpicker.cache, "path_for", lambda *args, **kwargs: cached)
    def failed(*args, **kwargs):
        raise FetchError("HTTP 403")
    monkeypatch.setattr(pcpartpicker, "get_text", failed)
    with pytest.raises(FetchError, match="403"):
        pcpartpicker._page("memory", False)


def test_refresh_script_preserves_the_feed_when_a_chart_failed(monkeypatch, tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text("previous feed", encoding="utf-8")
    monkeypatch.setattr(pcpartpicker, "FEED_PATH", feed)
    monkeypatch.setattr(pcpartpicker, "snapshot", lambda **kwargs: {
        "failed": ["DDR5 unreadable"], "memory": {"rows": [{}]}, "cpu": {"rows": [{}]}})
    main = runpy.run_path(str(REPO_ROOT / "scripts" / "refresh_pcpartpicker.py"))["main"]
    assert main() == 1
    assert feed.read_text(encoding="utf-8") == "previous feed"


def test_korea_breakout_keeps_weight_and_drops_a_partial_one():
    items = [{"priodTitle": "total", "expUsdAmt": "9", "expTtwg": "1"},
             {"priodTitle": "2026.07", "expUsdAmt": "1,000", "expTtwg": "10.0"},
             {"priodTitle": "2026.07", "expUsdAmt": "500", "expTtwg": "5"},
             {"priodTitle": "2026.08", "expUsdAmt": "2,000"}]
    rows = korea_customs.parse_rows(items)
    assert korea_customs.parse(items) == {"2026-07": 1500.0, "2026-08": 2000.0}
    assert rows[0]["weight_t"] == 15 and rows[0]["usd_per_kg"] == 100
    assert rows[1]["weight_t"] is None and rows[1]["usd_per_kg"] is None


def test_hs_column_follows_the_code_width():
    assert korea_customs.group_column("8542") == "HS4_SGN"
    assert korea_customs.group_column("854232") == "HS6_SGN"
    assert korea_customs.group_column("8542321010") == "HS10_SGN"
    with pytest.raises(ValueError):
        korea_customs.group_column("85423")


def test_fill_months_keeps_a_gap_so_yoy_is_twelve_months():
    rows = T.fill_months({"2024-11": 10.0, "2025-01": 12.0, "2025-11": 15.0})
    assert [row["month"] for row in rows][1] == "2024-12"
    assert rows[1]["value"] is None
    grown = T.yoy_monthly(rows, "value")
    november = grown[-1]
    assert november["month"] == "2025-11" and november["yoy_pct"] == 50.0


def test_a_second_yoy_pass_does_not_replace_the_first():
    rows = [{"month": "2025-01", "exports_k": 100.0, "usd_per_kg": 2.0},
            {"month": "2026-01", "exports_k": 150.0, "usd_per_kg": 3.0}]
    out = T.yoy_monthly(T.yoy_monthly(rows, "exports_k"), "usd_per_kg", key="unit_yoy_pct")
    assert out[1]["yoy_pct"] == 50.0 and out[1]["unit_yoy_pct"] == 50.0


def test_pcpartpicker_feed_marks_a_stale_chart(tmp_path):
    path = tmp_path / "feed.json"
    pcpartpicker.write_feed({
        "fetched_at": "2026-09-01T00:00:00Z",
        "failed": [],
        "memory": {"rows": [{"image_date": "2026-09-01", "title": "DDR5"}], "families": {}},
        "cpu": {"rows": [{"image_date": "2026-09-20", "title": "AMD"}], "families": {}},
    }, path)
    out = pcpartpicker.load_feed(date(2026, 10, 4), path)
    assert out["from_feed"] is True and "2026-09-01" in out["stale"]
    assert pcpartpicker.load_feed(date(2026, 10, 4), tmp_path / "missing.json")["skipped"] == pcpartpicker.SKIPPED
