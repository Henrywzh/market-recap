from market_recap import site


def test_code_version_moves_with_the_scripts(tmp_path):
    js = tmp_path / "js" / "tabs"
    js.mkdir(parents=True)
    (js / "a.js").write_text("export default 1;\n")
    first = site.code_version(tmp_path)
    assert first == site.code_version(tmp_path)
    (js / "a.js").write_text("export default 2;\n")
    assert site.code_version(tmp_path) != first


def test_built_index_carries_the_code_version(tmp_path):
    site.build(dist=tmp_path / "dist")
    index = (tmp_path / "dist" / "index.html").read_text()
    assert site.CODE_VERSION_PLACEHOLDER not in index
    assert site.code_version() in index


def test_built_index_maps_every_script_to_a_hashed_url(tmp_path):
    import json
    import re

    site.build(dist=tmp_path / "dist")
    index = (tmp_path / "dist" / "index.html").read_text()
    assert site.IMPORTMAP_PLACEHOLDER not in index
    imports = json.loads(re.search(r'<script type="importmap">(.*?)</script>', index).group(1))["imports"]
    assert imports["./js/fmt.js"].startswith("./js/fmt.js?h=")
    assert "./js/tabs/monitor.js" in imports


def test_live_contract_is_the_dashboard_universe_and_nothing_else():
    config = {
        "universe": {
            "quote_tickers": ["SPY", "QQQ"],
            "indices": [{"key": "SPX", "symbol": "^GSPC"}, {"key": "NDX", "symbol": "^NDX"}],
        },
        "watchlist": [{"ticker": "TSM"}, {"ticker": "SPY"}],
        "live": {"refresh_seconds": 60, "rates": [{"symbol": "US10Y", "label": "UST 10Y"}]},
    }
    contract = site.live_contract(config)
    assert [e["symbol"] for e in contract["equities"]] == ["SPY", "QQQ", "^GSPC", "^NDX", "TSM"]
    assert [e["label"] for e in contract["equities"] if e["kind"] == "index"] == ["SPX", "NDX"]
    assert contract["rates"] == [{"symbol": "US10Y", "label": "UST 10Y", "kind": "rate"}]
    assert contract["refresh_seconds"] == 60


def test_built_site_carries_the_live_contract(tmp_path):
    import json

    site.build(dist=tmp_path / "dist")
    contract = json.loads((tmp_path / "dist" / "live.json").read_text())
    assert contract["equities"] and contract["rates"]
    assert "/live.json" in (tmp_path / "dist" / "_headers").read_text()
