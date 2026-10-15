"""Each index map: one tile per priced member, sized by its own fund's weight."""

import pandas as pd

from market_recap.panels import heatmaps as H


def test_constituents_are_heaviest_first_with_their_own_weights():
    dates = pd.bdate_range("2026-01-02", periods=30)
    closes = pd.DataFrame({"AAA": range(100, 130), "BBB": [50.0] * 29 + [None]}, index=dates, dtype=float)
    priced = pd.DataFrame([
        {"yahoo_symbol": "AAA", "name": "AAA INC", "sector": "Information Technology", "sub_sector": "Software", "weight": 1.5},
        {"yahoo_symbol": "BBB", "name": "BBB CORP", "sector": "Utilities", "sub_sector": "Electric Utilities", "weight": 9.25},
    ])
    nodes = H._constituents(priced, closes, ["1D", "1W"])
    assert [n["ticker"] for n in nodes] == ["BBB", "AAA"]
    assert nodes[0]["weight"] == 9.25 and nodes[0]["price"] == 50.0  # last close, not the missing session
    assert nodes[1]["returns"]["1D"] == round((129 / 128 - 1) * 100, 2)
    assert H._constituents(priced.iloc[0:0], closes, ["1D"]) == []


class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)


class _Spec:
    def __init__(self, key):
        self.key, self.primary = key, key == "SPX"


def _fund_ctx(members):
    class Ctx:
        indices = [_Spec("SPX"), _Spec("NDX")]
        log = _Log()

        def priced(self, key):
            return members[key]
    return Ctx()


def test_a_fund_map_takes_labels_from_covered_indices_and_lists_the_rest(monkeypatch):
    dates = pd.bdate_range("2026-01-02", periods=10)
    closes = pd.DataFrame({"GS": range(10), "BRK-B": range(10)}, index=dates, dtype=float) + 100
    member = lambda s, sector: {"yahoo_symbol": s, "name": s, "sector": sector, "sub_sector": "x", "weight": 1.0}
    ctx = _fund_ctx({"SPX": pd.DataFrame([member("GS", "Financials"), member("BRK-B", "Financials")]),
                     "NDX": pd.DataFrame([member("GS", "Financials")])})
    holdings = pd.DataFrame({"ticker": ["GS", "BRK.B", "ZZZZ"], "weight": [10.0, 5.0, 1.0]})
    monkeypatch.setattr(H.ssga, "fetch_holdings", lambda fund: (holdings, "2026-01-15", "url"))
    out = H._fund_map(ctx, {"key": "DJI", "label": "Dow Jones", "holdings_etf": "DIA"}, closes, ["1D"])
    assert [(n["ticker"], n["weight"], n["sector"]) for n in out["constituents"]] == [("GS", 10.0, "Financials"), ("BRK-B", 5.0, "Financials")]
    assert out["missing"] == ["ZZZZ"] and out["holdings_as_of"] == "2026-01-15"
    assert ctx.log.records[-1].status == "partial"


def test_a_failed_fund_file_leaves_an_empty_map_not_a_failed_page(monkeypatch):
    ctx = _fund_ctx({"SPX": pd.DataFrame(), "NDX": pd.DataFrame()})
    def boom(fund):
        raise RuntimeError("HTTP 503")
    monkeypatch.setattr(H.ssga, "fetch_holdings", boom)
    out = H._fund_map(ctx, {"key": "DJI", "label": "Dow Jones", "holdings_etf": "DIA"}, pd.DataFrame(), ["1D"])
    assert out["constituents"] == [] and "503" in ctx.log.records[-1].error
