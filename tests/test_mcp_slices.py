"""MCP slices: what the writer keeps from each artifact, and what it records about them."""

import hashlib
import json

from market_recap import mcp_slices


def _artifacts(tmp_path, omit=()):
    """A small build: three panels, events, themes, sectors, the market panels, macro.

    Artifacts named in ``omit`` are not written, as when a panel is not published.
    """
    root = tmp_path / "artifacts"
    files = {
        "manifest": {"as_of": "2026-10-15", "generated_at": "2026-10-16T14:00:00Z"},
        "valuation": {"as_of": "2026-10-14", "note": "valuation note", "rows": [
            {"ticker": "NVDA", "name": "NVIDIA", "sector": "Information Technology", "price": 226, "pe": 28, "cik": "1"},
            {"ticker": "AMD", "name": "AMD", "sector": "Information Technology", "price": 150, "pe": 60, "cik": "2"},
        ]},
        "monitor": {"as_of": "2026-10-14", "rows": [
            {"ticker": "NVDA", "price_state": "weak", "history": [1, 2, 3]},
            {"ticker": "AMD", "price_state": "steady", "history": [4]},
        ]},
        "moves": {
            "as_of": "2026-10-15", "note": "moves note", "settings": {"threshold_sigma": 2}, "sector_selloff": {"active": False},
            "rows": [
                {"ticker": "NVDA", "name": "NVIDIA", "z_own": -2.5, "ret_pct": -3, "range": {"bands": [1, 2]}, "range_raw": {"bands": [3]}, "direction": "down", "tags": {"gap_led": True}},
                {"ticker": "AMD", "name": "AMD", "z_own": 2.2, "ret_pct": 1, "range": None, "direction": "up", "tags": None},
            ],
            "move_states": {"rows": [{"direction": "down", "match": {}, "stats": {"h1": {"mean": 0.1}}}], "definitions": "long text"},
        },
        "themes": {"as_of": "2026-10-14", "groups": [
            {"key": "cloud", "label": "CLOUD", "proxy": "MSFT, META", "board": {"state": {"key": "s"}}, "bellwethers": [{"symbol": "MSFT"}]},
            {"key": "semis", "label": "SEMIS", "proxy": "SOXX", "board": {}},
        ], "drivers": [
            {"key": "capex", "label": "Capex", "themes": ["cloud"], "points": [{"period": "2026-06", "value": 1}, {"period": "2026-09", "value": 2}]},
            {"key": "dram", "label": "DRAM", "themes": ["semis"], "points": [{"period": "2026-09", "value": 3}]},
        ], "cloud": {"guidance": {"companies": []}, "other": "big"}, "semis": {"adata": {"notes": []}, "big": "x"}},
        "sectors": {"as_of": "2026-10-12", "benchmark": {"label": "S&P 500"},
                    "sectors": [{"key": "XLK", "label": "Technology", "weight": 30, "quadrant": "leading", "returns": {"1M": 2}, "vs_index": {"1M": 1}, "above_200d": 70, "best": {"ticker": "NVDA"}}],
                    "sub_industries": [{"key": "XLK-S", "label": "Semis", "sector": "Technology", "sector_key": "XLK"}],
                    "members": [{"ticker": "NVDA"}] * 50, "notes": ["n1", "n2", "n3"]},
        "catalysts": {"as_of": "2026-10-14", "events": [
            {"event_key": "e1", "title": "CPI", "date": "2026-10-21", "event_type": "economic_release", "symbol": None, "detail": "long", "prints": []},
        ], "recent": {"session": "2026-10-14", "macro": []}},
        "overview": {"as_of": "2026-10-15", "stocks": [{"key": "SPX", "label": "S&P 500"}]},
        "market_state": {"as_of": "2026-10-15", "states": []},
        "risk": {"as_of": "2026-10-15", "sentiment": {"score": 40}, "charts": {"big": 1}, "sections": [
            {"key": "vol", "label": "VOL", "horizon": "tactical", "tiles": [{"key": "vix", "label": "VIX", "value": 14.8, "core": True, "breach": False, "history": [1, 2, 3], "spark": [1]}]},
        ]},
        "positioning": {"as_of": "2026-10-14", "trend": [1, 2, 3], "blackout": {"as_of": "2026-10-14"}, "index_put_call": {"series": []}},
        "macro": {"as_of": "2026-10-16", "note": "macro note", "cpi": {"status": "ok", "components": []}, "ppi": {"status": "ok"}, "commodities": {"rows": []}},
    }
    root.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        if name not in omit:
            (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    (root / "events").mkdir(exist_ok=True)
    (root / "events" / "NVDA.json").write_text(json.dumps({"name": "Nvidia", "history": [{"date": "2026-08-26", "guide": {"quote": "q"}}]}), encoding="utf-8")
    (root / "events" / "ZZZ.json").write_text(json.dumps({"name": "Only in events"}), encoding="utf-8")
    (root / "events" / "LIST.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    return root


def _read(root, rel):
    return json.loads((root / "mcp" / f"{rel}.json").read_text(encoding="utf-8"))


def test_ticker_slice_holds_only_its_symbols_rows_and_keeps_as_of(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    nvda = _read(root, "ticker/NVDA")["artifacts"]
    assert [r["ticker"] for r in nvda["valuation"]["rows"]] == ["NVDA"]
    assert nvda["valuation"]["as_of"] == "2026-10-14" and nvda["valuation"]["note"] == "valuation note"
    assert nvda["valuation"]["rows"][0]["pe"] == 28
    assert [r["ticker"] for r in nvda["monitor"]["rows"]] == ["NVDA"]
    assert nvda["monitor"]["rows"][0]["price_state"] == "weak"
    assert nvda["moves"]["settings"] == {"threshold_sigma": 2}
    assert nvda["moves"]["note"] == "moves note"
    assert nvda["moves"]["move_states"] == {"rows": [{"direction": "down", "match": {}, "stats": {"h1": {"mean": 0.1}}}]}
    assert [r["ticker"] for r in nvda["moves"]["rows"]] == ["NVDA"]


def test_ticker_index_lists_panel_symbols_and_only_object_event_files(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    assert _read(root, "ticker/index") == {"rows": ["AMD", "NVDA"], "events": ["NVDA", "ZZZ"]}


def test_a_symbol_with_only_an_events_file_gets_a_slice_with_no_rows(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    zzz = _read(root, "ticker/ZZZ")["artifacts"]
    assert zzz["valuation"]["rows"] == [] and zzz["monitor"]["rows"] == [] and zzz["moves"]["rows"] == []


def test_theme_slice_holds_one_group_its_drivers_last_point_and_only_its_own_blobs(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    cloud = _read(root, "theme/cloud")["artifacts"]["themes"]
    assert [g["key"] for g in cloud["groups"]] == ["cloud"]
    assert [d["key"] for d in cloud["drivers"]] == ["capex"]
    assert cloud["drivers"][0]["points"] == [{"period": "2026-09", "value": 2}]
    assert cloud["cloud"] == {"guidance": {"companies": []}}
    assert "semis" not in cloud
    semis = _read(root, "theme/semis")["artifacts"]["themes"]
    assert semis["semis"] == {"adata": {"notes": []}}
    assert "cloud" not in semis and [d["key"] for d in semis["drivers"]] == ["dram"]


def test_theme_index_lists_each_key_and_label(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    assert _read(root, "theme/index") == {"groups": [{"key": "cloud", "label": "CLOUD"}, {"key": "semis", "label": "SEMIS"}]}


def test_search_index_keeps_the_fields_search_reads(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    search = _read(root, "search_index")["artifacts"]
    assert set(search["valuation"]["rows"][0]) == {"ticker", "name", "sector"}
    assert set(search["sectors"]["sub_industries"][0]) == {"key", "label", "sector"}
    assert set(search["themes"]["groups"][0]) == {"key", "label", "proxy"}
    assert set(search["catalysts"]["events"][0]) == {"event_key", "title", "date", "event_type", "symbol"}
    assert "recent" not in search["catalysts"] and "members" not in search["sectors"]


def test_snapshot_risk_and_positioning_keep_only_what_the_adapter_reads(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    snap = _read(root, "snapshot")["artifacts"]
    tile = snap["risk"]["sections"][0]["tiles"][0]
    assert set(tile) <= set(mcp_slices.RISK_TILE_KEYS) and tile["value"] == 14.8 and tile["core"] is True
    assert snap["risk"]["sentiment"] == {"score": 40}
    assert "charts" not in snap["risk"]
    assert "trend" not in snap["positioning"] and snap["positioning"]["blackout"] == {"as_of": "2026-10-14"}


def test_unusual_rows_keep_their_read_fields_and_the_settings(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    moves = _read(root, "unusual")["artifacts"]["moves"]
    assert moves["settings"] == {"threshold_sigma": 2}
    assert all(set(row) <= set(mcp_slices.UNUSUAL_ROW_KEYS) for row in moves["rows"])
    assert [row["z_own"] for row in moves["rows"]] == [-2.5, 2.2]


def test_sector_hub_drops_the_member_list_and_keeps_the_rest(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    hub = _read(root, "sector_hub")["artifacts"]["sectors"]
    assert "members" not in hub
    assert hub["sectors"][0]["key"] == "XLK" and hub["sub_industries"][0]["key"] == "XLK-S" and hub["notes"] == ["n1", "n2", "n3"]


def test_macro_slices_hold_one_kind_each(tmp_path):
    root = _artifacts(tmp_path)
    mcp_slices.write(root)
    assert set(_read(root, "macro/cpi")["artifacts"]["macro"]) == {"as_of", "note", "cpi"}
    assert set(_read(root, "macro/commodities")["artifacts"]["macro"]) == {"as_of", "note", "commodities"}


def test_index_records_the_sha256_of_each_source_and_null_for_a_missing_one(tmp_path):
    root = _artifacts(tmp_path, omit=("overview",))
    mcp_slices.write(root)
    index = _read(root, "index")
    assert index["schema"] == mcp_slices.SCHEMA
    assert index["as_of"] == "2026-10-15" and index["generated_at"] == "2026-10-16T14:00:00Z"
    assert index["sources"]["valuation"] == hashlib.sha256((root / "valuation.json").read_bytes()).hexdigest()
    assert index["sources"]["manifest"] == hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    assert index["sources"]["overview"] is None
    assert index["slices"]["ticker"] == 3


def test_without_themes_there_is_no_theme_slice_or_index_and_the_search_index_says_so(tmp_path):
    root = _artifacts(tmp_path, omit=("themes",))
    mcp_slices.write(root)
    assert not (root / "mcp" / "theme" / "index.json").exists()
    assert not (root / "mcp" / "theme" / "cloud.json").exists()
    assert _read(root, "search_index")["artifacts"]["themes"] is None


def test_a_symbol_that_is_not_a_safe_file_name_gets_no_slice(tmp_path):
    root = _artifacts(tmp_path)
    (root / "valuation.json").write_text(json.dumps({"as_of": "2026-10-14", "rows": [{"ticker": "A/B", "name": "bad"}, {"ticker": "OK", "name": "fine"}]}), encoding="utf-8")
    mcp_slices.write(root)
    assert not (root / "mcp" / "ticker" / "A").exists()
    assert _read(root, "ticker/OK")["artifacts"]["valuation"]["rows"][0]["name"] == "fine"


def test_values_are_copied_not_rounded(tmp_path):
    root = _artifacts(tmp_path)
    (root / "valuation.json").write_text(json.dumps({"as_of": "2026-10-14", "rows": [{"ticker": "NVDA", "pe": 28.123456789012345, "price": 1e-9}]}), encoding="utf-8")
    mcp_slices.write(root)
    row = _read(root, "ticker/NVDA")["artifacts"]["valuation"]["rows"][0]
    assert row["pe"] == 28.123456789012345 and row["price"] == 1e-9
