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
