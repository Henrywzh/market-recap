"""ETF X-RAY: look-through computed from issuers' holdings files."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import xray as X
from market_recap.panels import xray as panel


def test_class_share_tickers_match_across_issuers():
    assert X.ticker_key("BRK.B") == X.ticker_key("BRKB") == X.ticker_key("BRK-B")
    assert X.resolve_symbols(pd.Series(["BRKB", "AAPL", "ZZZ"]), ["BRK-B", "AAPL"]).tolist() == ["BRK-B", "AAPL", "ZZZ"]


@pytest.mark.parametrize("exchange, us", [
    ("NYSE", True), ("NASDAQ", True), ("New York Stock Exchange Inc.", True), ("Nyse Mkt Llc", True),
    ("Nyse Euronext - Euronext Paris", False), ("Nasdaq Omx Nordic", False), ("London Stock Exchange", False),
])
def test_us_exchanges_are_matched_by_whole_name(exchange, us):
    assert bool(X.US_EXCHANGES.match(exchange)) is us


def test_a_foreign_listing_is_never_priced_as_its_us_namesake():
    """EFA's DG is Vinci in Paris, not Dollar General."""
    frame = pd.DataFrame({
        "ticker": ["DG", "PDD", ""], "name": ["VINCI", "PDD HOLDINGS", "AIR LIQUIDE"],
        "asset_class": ["Equity"] * 3, "weight": [0.02, 0.01, 0.01],
        "exchange": ["Nyse Euronext - Euronext Paris", "NASDAQ", "Nyse Euronext - Euronext Paris"],
        "isin": [None, None, "FR0000120073"],
    })
    lines = panel._equity_lines(frame, "ishares", "International")
    assert lines["us_listed"].tolist() == [False, True, False]
    assert lines["key"].tolist() == ["XUS:DG", "US:PDD", "XUS:FR0000120073"]  # a blank ticker keeps its own identity


def test_overlap_is_the_sum_of_the_smaller_weights():
    a = pd.Series({"X": 0.5, "Y": 0.5})
    assert X.overlap(a, a) == pytest.approx(1.0)
    assert X.overlap(a, pd.Series({"Z": 1.0})) == 0.0
    assert X.overlap(a, pd.Series({"X": 0.2, "Z": 0.8})) == pytest.approx(0.2)


def test_effective_n_counts_equal_holdings():
    assert X.effective_n(pd.Series([0.25] * 4)) == pytest.approx(4.0)
    assert X.effective_n(pd.Series([0.9, 0.1])) == pytest.approx(1 / (0.81 + 0.01))


def test_attribution_covers_only_priced_holdings_and_says_how_much():
    weights = pd.Series({"A": 0.6, "B": 0.3, "C": 0.1})
    out = X.attribution(weights, pd.Series({"A": 1.0, "B": -2.0}))
    assert out["covered"] == pytest.approx(0.9) and out["priced"] == 2
    assert out["sum"] == pytest.approx(0.6 - 0.6)


def test_bond_profile_weights_duration_and_buckets_maturities():
    frame = pd.DataFrame({
        "weight": [0.5, 0.4, 0.1],
        "duration": [2.0, 10.0, 0.1],
        "ytm": [4.0, 5.0, 3.0],
        "coupon": [3.0, 4.0, 0.0],
        "maturity": pd.to_datetime(["2028-09-21", "2040-09-21", None]),
    })
    profile = X.bond_profile(frame, "2026-09-21")
    assert profile["duration"] == pytest.approx(0.5 * 2 + 0.4 * 10 + 0.1 * 0.1)
    buckets = {b["label"]: b["weight"] for b in profile["maturity_buckets"]}
    assert buckets["1-3y"] == 0.5 and buckets["10-20y"] == 0.4 and buckets[X.CASH_LABEL] == 0.1
