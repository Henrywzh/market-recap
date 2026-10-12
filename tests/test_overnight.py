"""Overnight vs intraday: the split is exact and the dividend is overnight's."""

import types

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import overnight as O
from market_recap.config import load_config
from market_recap.panels import overnight as P
from market_recap.util import BuildLog


def _days(n):
    return pd.bdate_range("2024-01-02", periods=n)


def test_the_two_legs_multiply_to_the_total_return_on_adjusted_closes():
    idx = _days(4)
    price = pd.Series([100.0, 102.0, 101.0, 104.0], idx)
    open_ = pd.Series([99.0, 101.0, 103.0, 102.0], idx)
    daily = O.legs(price, price, open_)          # no dividends: adjusted == price
    assert list(daily.index) == list(idx[1:])
    assert daily.loc[idx[1], "overnight"] == pytest.approx(101 / 100 - 1)
    assert daily.loc[idx[1], "intraday"] == pytest.approx(102 / 101 - 1)
    assert np.allclose(daily["total"], price.pct_change().dropna())


def test_a_dividend_lands_in_the_overnight_leg_not_as_a_loss():
    idx = _days(3)
    price = pd.Series([100.0, 100.0, 99.0], idx)      # ex-date on day 3: the price drops by the 1.00 dividend
    open_ = pd.Series([100.0, 100.0, 99.0], idx)
    adjusted = pd.Series([99.0, 99.0, 99.0], idx)      # adjusted for the dividend: flat
    daily = O.legs(adjusted, price, open_)
    assert daily.loc[idx[2], "overnight"] == pytest.approx(0.0)
    assert daily.loc[idx[2], "intraday"] == pytest.approx(0.0)
    assert daily.loc[idx[2], "total"] == pytest.approx(0.0)


def test_a_session_without_an_open_is_left_out():
    idx = _days(3)
    price = pd.Series([100.0, 101.0, 102.0], idx)
    open_ = pd.Series([100.0, np.nan, 101.5], idx)
    assert list(O.legs(price, price, open_).index) == [idx[2]]


def test_windows_are_compounded_and_annualised_from_a_year_up():
    idx = _days(300)
    daily = pd.DataFrame({"overnight": 0.001, "intraday": -0.0005}, index=idx)
    daily["total"] = (1 + daily["overnight"]) * (1 + daily["intraday"]) - 1
    year = O.window(daily, 252)
    assert year["overnight"] == pytest.approx((1.001 ** 252 - 1) * 100)
    assert year["overnight_ann"] == pytest.approx(year["overnight"])
    assert year["overnight_up"] == 100 and year["intraday_up"] == 0
    assert O.window(daily, 21)["overnight_ann"] is None
    assert O.window(daily, 400) is None                 # not enough history: no row rather than a short one


def test_years_whose_opens_equal_the_previous_close_are_flagged():
    idx = pd.bdate_range("1993-01-04", periods=6)
    close = pd.Series([10.0, 11, 12, 13, 14, 15], idx)
    open_ = pd.Series([10.0, 10, 11, 12.5, 13.5, 14.5], idx)   # two of five opens equal the previous close
    assert O.stale_opens(open_, close).loc[1993] == pytest.approx(40.0)


def test_the_panel_splits_each_fund_and_names_one_without_opens(monkeypatch):
    idx = _days(600)
    rng = np.random.default_rng(0)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0.0004, 0.01, len(idx))), idx)
    open_ = close.shift(1).fillna(100) * (1 + rng.normal(0.0002, 0.003, len(idx)))
    frame = lambda s: pd.DataFrame({"SPY": s, "QQQ": s})
    monkeypatch.setattr(P.yahoo, "fetch_closes", lambda *a, **k: frame(close))
    monkeypatch.setattr(P.yahoo, "fetch_prices", lambda *a, **k: frame(close))
    monkeypatch.setattr(P.yahoo, "fetch_ohlcv_cache", lambda *a, **k: {"open": pd.DataFrame({"SPY": open_})})
    ctx = types.SimpleNamespace(config=load_config(), log=BuildLog(), as_of=str(idx[-1].date()))
    out = P.build(ctx)
    spy, qqq = out["views"][0], out["views"][1]
    assert spy["available"] and not qqq["available"]
    assert spy["sessions"] == len(idx) - 1 and spy["through"] == str(idx[-1].date())
    assert [w["period"] for w in spy["windows"]] == ["1M", "3M", "1Y", "MAX"]
    last = spy["last"][0]
    assert (1 + last["overnight"] / 100) * (1 + last["intraday"] / 100) - 1 == pytest.approx(last["total"] / 100, abs=1e-4)
    assert spy["weekly"]["total"][-1] == pytest.approx(close.iloc[-1] / close.iloc[0], rel=1e-3)
