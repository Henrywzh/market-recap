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
        "universe": {"quote_tickers": ["SPY", "QQQ"], "indices": [{"key": "SPX", "symbol": "^GSPC"}]},
        "watchlist": [{"ticker": "TSM"}],
        "live": {"refresh_seconds": 60, "rates": [{"symbol": "US10Y", "label": "UST 10Y"}],
                 "strip": [{"symbol": "^GSPC", "label": "SPX", "kind": "index"},
                           {"symbol": "^VIX", "label": "VIX", "kind": "macro"}],
                 "strip_names": ["NVDA", "^GSPC"],
                 "index_board": [{"symbol": "^GSPC", "label": "S&P 500"}],
                 "board_refresh_seconds": 300},
    }
    contract = site.live_contract(config)
    # The strip is the config's own list, a name once; the ETFs and the
    # watchlist are not on it.
    assert [(e["symbol"], e["kind"]) for e in contract["strip"]] == [("^GSPC", "index"), ("^VIX", "macro"), ("NVDA", "watch")]
    assert contract["rates"] == [{"symbol": "US10Y", "label": "UST 10Y", "kind": "rate", "source": "cnbc"}]
    assert contract["refresh_seconds"] == 60
    assert contract["boards"]["indices"]["symbols"] == ["^GSPC"] and contract["boards"]["indices"]["series"]
    assert contract["boards"]["indices"]["refresh_seconds"] == 300
    assert "heatmap" not in contract["boards"]          # no heat-map artifact, no heat-map board


def test_the_heat_map_board_is_its_members_heaviest_first():
    config = {"universe": {}, "live": {}}
    contract = site.live_contract(config, weighted_names=["NVDA", "MSFT", "NVDA", "BRK-B"])
    assert contract["boards"]["heatmap"]["symbols"] == ["NVDA", "MSFT", "BRK-B"]
    assert contract["boards"]["heatmap"]["series"] is False


def test_the_refresh_only_boards_come_from_their_own_config():
    config = {"universe": {}, "macro": {"commodities": {"Gold": "GC=F", "Copper": "HG=F"}},
              "live": {"sector_etfs": [{"symbol": "XLK", "sector": "Information Technology"}], "sector_benchmark": "SPY",
                       "yield_board": [{"symbol": "US10Y", "label": "10Y"}]}}
    boards = site.live_contract(config)["boards"]
    assert boards["sector_etfs"]["symbols"] == ["XLK", "SPY"]
    assert boards["sector_etfs"]["labels"] == {"XLK": "Information Technology", "SPY": "benchmark"}
    assert boards["macro"]["symbols"] == ["GC=F", "HG=F"] and boards["macro"]["labels"]["HG=F"] == "Copper"
    assert boards["yields"]["source"] == "cnbc" and boards["yields"]["labels"] == {"US10Y": "10Y"}
    bare = site.live_contract({"universe": {}, "live": {}})["boards"]
    assert set(bare) == {"indices"}


def test_trade_premarket_scan_uses_weighted_members_plus_watchlist_once():
    config = {
        "universe": {"quote_tickers": [], "indices": []},
        "watchlist": [{"ticker": "TSM"}, {"ticker": "AAPL"}],
        "live": {"premarket_top_weight_names": 2, "premarket_movers": ["FALLBACK"]},
    }
    contract = site.live_contract(config, weighted_names=["AAPL", "MSFT", "NVDA"])
    assert [r["symbol"] for r in contract["premarket_movers"]] == ["AAPL", "MSFT", "TSM"]
    fallback = site.live_contract(config)
    assert [r["symbol"] for r in fallback["premarket_movers"]] == ["FALLBACK", "TSM", "AAPL"]


def test_built_site_carries_the_live_contract(tmp_path):
    import json

    site.build(dist=tmp_path / "dist")
    contract = json.loads((tmp_path / "dist" / "live.json").read_text())
    assert contract["strip"] and contract["rates"] and contract["boards"]["indices"]["symbols"]
    assert "/live.json" in (tmp_path / "dist" / "_headers").read_text()
