"""INDICES: what moved an index needs its basket's weights; without them the card is left out, not the panel."""

import pandas as pd

from market_recap.panels import markets as P


def test_contributions_need_the_basket_weights():
    panel = pd.DataFrame({"AAA": [100.0, 102.0], "BBB": [50.0, 49.0]}, index=pd.bdate_range("2026-10-26", periods=2))
    members = pd.DataFrame({"yahoo_symbol": ["AAA", "BBB"], "weight": [60.0, 40.0], "sector": ["Tech", "Energy"]})
    c = P._contributions(panel, members)
    assert round(c["total_pp"], 3) == round(0.6 * 2.0 + 0.4 * -2.0, 3)
    assert [x["ticker"] for x in c["leaders"]] == ["AAA"] and [x["ticker"] for x in c["laggards"]] == ["BBB"]
    assert P._contributions(panel, members.drop(columns=["weight"])) is None
    assert P._contributions(panel, pd.DataFrame()) is None
