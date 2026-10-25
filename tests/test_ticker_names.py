from types import SimpleNamespace

import pandas as pd

from market_recap.panels.technicals import ticker_names, ticker_rank


def test_names_come_from_the_baskets_the_config_and_the_sector_funds_only():
    members = {
        "SPX": pd.DataFrame({"yahoo_symbol": ["GOOGL", "GOOG", "AMZN"],
                             "name": ["ALPHABET INC CL A", "ALPHABET INC CL C", "Amazon.com Inc"]}),
        "NDX": pd.DataFrame({"yahoo_symbol": ["AMZN"], "name": ["AMAZON COM INC"]}),
    }
    ctx = SimpleNamespace(
        members=members, sector_etfs={"Information Technology": "XLK"},
        config={"financials": {"extra_names": [{"ticker": "TOL", "name": "Toll Brothers"}]}},
    )
    names = ticker_names(ctx, ["GOOGL", "GOOG", "AMZN", "TOL", "XLK", "SPY"])
    assert names["AMZN"] == "Amazon.com Inc"          # the first basket's spelling wins
    assert names["TOL"] == "Toll Brothers"
    assert names["XLK"] == "Information Technology sector fund"
    assert "SPY" not in names                          # unnamed: left out, not guessed
    assert set(names) == {"GOOGL", "GOOG", "AMZN", "TOL", "XLK"}


def test_rank_is_by_the_largest_weight_in_any_basket():
    members = {
        "SPX": pd.DataFrame({"yahoo_symbol": ["A", "AAPL", "AMZN"], "weight": [0.05, 6.5, 3.9]}),
        "NDX": pd.DataFrame({"yahoo_symbol": ["AMZN", "QQQ"], "weight": [7.2, None]}),
    }
    ctx = SimpleNamespace(members=members)
    assert ticker_rank(ctx, ["A", "AAPL", "AMZN", "QQQ", "SPY"]) == ["AMZN", "AAPL", "A"]
