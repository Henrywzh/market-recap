"""A technology-only sell-off session: fires on a sector fall the market does not explain."""

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import sector_selloff as S

KW = dict(beta_sessions=252, vol_sessions=60, fund_z_max=-2.0, market_z_floor=-2.0)
CONFIG = {"fund": "XLK", "sector": "Information Technology", "fund_z_max": -2.0, "market_z_floor": -2.0,
          "loser_share": 0.2, "history": {"days": 78}}


def _series(last_market, last_fund_own, n=400):
    """A fund that follows the market with a little noise of its own, and a final session."""
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2024-01-01", periods=n)
    market = pd.Series(rng.normal(0, 0.01, n), index=index)
    fund = 1.0 * market + rng.normal(0, 0.004, n)
    market.iloc[-1], fund.iloc[-1] = last_market, last_market + last_fund_own
    return fund, market


def test_a_technology_only_day_fires():
    fund, market = _series(0.0, -0.03)
    out = S.selloff_session(fund, market, **KW)
    assert out["active"] and out["z"] < -5 and abs(out["spy_z"]) < 1


def test_a_market_wide_day_does_not():
    fund, market = _series(-0.05, 0.0)  # the sector fell with the market: its own part is ordinary
    assert not S.selloff_session(fund, market, **KW)["active"]
    both, market = _series(-0.05, -0.03)  # SPY itself at -2σ or worse: not a technology-only day
    out = S.selloff_session(both, market, **KW)
    assert out["z"] < -2 and out["spy_z"] <= -2 and not out["active"]


def test_the_session_is_measured_with_the_sessions_before_it():
    fund, market = _series(0.0, -0.03)
    expected = S.selloff_session(fund, market, **KW)["z"]
    fund.iloc[-1] = -0.9  # nothing about the last day may change the beta or sigma the day is judged by
    assert S.selloff_session(fund, market, **KW)["z"] != expected
    short = S.selloff_session(fund.iloc[:30], market.iloc[:30], **KW)
    assert short is None


def _row(ticker, ret, beta, gap, session, reported, sector="Information Technology"):
    return {"ticker": ticker, "name": ticker, "sector": sector, "sub_sector": "x", "ret_pct": ret,
            "own_pct": ret, "z_own": ret / 2, "beta_sector": beta, "gap_pct": gap, "intraday_pct": session,
            "reported": reported}


def test_losers_are_the_bottom_fifth_and_fit_only_when_all_three_hold():
    rows = [_row(f"T{i}", -0.1 * i, 1.0, -0.1, -0.2, False) for i in range(10)]  # T0..T9, T9 the worst
    rows[9] = _row("T9", -9.0, 1.5, -1.0, -8.0, False)   # high beta, made in the session, no report: fits
    rows[8] = _row("T8", -8.0, 1.6, -7.0, -1.0, False)   # gap-led: does not fit
    rows += [_row("OUT", -20.0, 2.0, -1.0, -19.0, False, sector="Energy")]  # another sector is ignored
    names, median = S.losers(rows, sector="Information Technology", share=0.2)
    assert [n["ticker"] for n in names] == ["T9", "T8"] and median == 1.0
    assert names[0]["fits_profile"] and names[0]["high_beta"] and names[0]["session_led"] is True
    assert not names[1]["fits_profile"] and names[1]["session_led"] is False
    unknown = S.losers([_row("A", -5.0, 2.0, -1.0, -4.0, None), _row("B", -1.0, 1.0, 0.0, 0.0, False)],
                       sector="Information Technology", share=0.5)[0]
    assert unknown[0]["reported"] is None and not unknown[0]["fits_profile"]  # an unknown report is not "none"


def test_losers_with_a_fit_come_first():
    rows = [_row("BAD", -9.0, 0.5, -8.0, -1.0, True), _row("GOOD", -8.0, 2.0, -1.0, -7.0, False),
            _row("MID", 0.0, 1.0, 0.0, 0.0, False), _row("UP", 1.0, 1.0, 0.0, 1.0, False)]
    names, _ = S.losers(rows, sector="Information Technology", share=0.5)
    assert [n["ticker"] for n in names] == ["GOOD", "BAD"]


def test_build_carries_the_losers_only_when_active_and_the_fund_traded_this_session():
    fund, market = _series(0.0, -0.03)
    funds = pd.DataFrame({"XLK": 100 * (1 + fund).cumprod(), "SPY": 100 * (1 + market).cumprod()})
    as_of = funds.index[-1].strftime("%Y-%m-%d")
    rows = [_row("A", -5.0, 2.0, -1.0, -4.0, False), _row("B", 1.0, 1.0, 0.0, 1.0, False)]
    kw = dict(market="SPY", beta_sessions=252, vol_sessions=60)
    out = S.build(funds, rows, CONFIG, as_of=as_of, **kw)
    assert out["active"] and out["fund"] == "XLK" and out["z"] < -5 and out["history"] == {"days": 78}
    assert [n["ticker"] for n in out["losers"]] == ["A"] and out["members"] == 2
    stale = S.build(funds.iloc[:-1], rows, CONFIG, as_of=as_of, **kw)  # no close for this session
    assert not stale["active"] and stale["losers"] == [] and stale["z"] is None
    quiet_fund, quiet_market = _series(0.0, 0.0)
    quiet = pd.DataFrame({"XLK": 100 * (1 + quiet_fund).cumprod(), "SPY": 100 * (1 + quiet_market).cumprod()})
    assert not S.build(quiet, rows, CONFIG, as_of=as_of, **kw)["active"]
    assert S.build(funds, rows, None, as_of=as_of, **kw) is None  # no config table: no payload
    assert not S.build(funds.drop(columns="XLK"), rows, CONFIG, as_of=as_of, **kw)["active"]

