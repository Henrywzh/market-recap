"""An issuer share count that stops moving is not a measured zero flow."""

import pandas as pd
import pytest

from market_recap.panels import heatmaps as H


def test_windows_inside_an_unchanged_stretch_are_unknown():
    dates = pd.bdate_range("2026-01-02", periods=120)
    shares = pd.Series(range(1000, 1120), index=dates, dtype=float)
    shares.iloc[80:] = shares.iloc[80]  # issuer stops updating after session 80
    last, unchanged = H._unchanged_run(shares)
    assert last == dates[80] and unchanged == 39
    flows = {"1D": 0.0, "1W": 0.0, "1M": 0.0, "3M": 5.0, "YTD": 5.0}
    masked = H._mask_unchanged(flows, list(flows), last, unchanged, dates[-1])
    assert masked == {"1D": None, "1W": None, "1M": None, "3M": 5.0, "YTD": 5.0}


def test_a_normally_updating_count_is_left_alone():
    dates = pd.bdate_range("2026-01-02", periods=40)
    shares = pd.Series(1000.0, index=dates)
    shares.iloc[-5:] = 1010.0
    last, unchanged = H._unchanged_run(shares)
    assert unchanged == 4
    flows = {"1D": 0.0, "1W": 10.0}
    assert H._mask_unchanged(flows, list(flows), last, unchanged, dates[-1]) == flows


def test_vanguard_money_strings():
    from market_recap.sources import vanguard

    assert vanguard.parse_money("$1.0 trillion") == 1e12
    assert vanguard.parse_money("$690.1 billion") == pytest.approx(6.901e11)
    assert vanguard.parse_money("$12,345") == 12345.0
    assert vanguard.parse_money("n/a") is None
