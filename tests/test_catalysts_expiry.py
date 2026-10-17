"""CATALYSTS: expiry dates, their settlement detail, and the after-a-large-move flag."""

from __future__ import annotations

from datetime import date
import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_recap.compute import catalysts as C
from market_recap.panels import catalysts as panel

SETTINGS = {
    "expiry_watch_funds": ["SPY", "QQQ"], "expiry_watch_sessions": 3, "expiry_shock_lookback_sessions": 5,
    "expiry_shock_window_sessions": 60, "expiry_shock_z": 2.0,
}


def _expiries(start: date, end: date) -> dict[str, dict]:
    return {e["rule"] + ":" + e["date"]: e for e in C.rule_events(start, end)
            if e["rule"] in ("monthly_opex", "quad_witching")}


# --- Event generation -------------------------------------------------------------

def test_a_holiday_friday_moves_the_june_expiry_to_the_thursday_before():
    # Juneteenth 2026 is a Friday: the third Friday's expiry is the Thursday, and it is quad witching.
    assert C.monthly_expiry(2026, 6) == date(2026, 6, 18)
    june = _expiries(date(2026, 6, 1), date(2026, 6, 30))
    assert list(june) == ["quad_witching:2026-06-18"]


def test_quarter_end_months_are_quad_witching_and_the_rest_monthly_opex():
    events = _expiries(date(2026, 1, 1), date(2026, 12, 31))
    quad = sorted(k for k in events if k.startswith("quad_witching"))
    monthly = sorted(k for k in events if k.startswith("monthly_opex"))
    assert quad == ["quad_witching:2026-03-20", "quad_witching:2026-06-18",
                    "quad_witching:2026-09-18", "quad_witching:2026-12-18"]
    assert len(monthly) == 8 and "monthly_opex:2026-01-16" in monthly


def test_settlement_detail_is_on_the_monthly_and_the_quarterly_and_only_the_quarterly_has_the_futures_line():
    quad = _expiries(date(2026, 9, 1), date(2026, 9, 30))["quad_witching:2026-09-18"]
    assert "settle on the OPENING prices that morning (SET, AM-settled)" in quad["detail"]
    assert "SPXW and most ETF/equity options settle at the close" in quad["detail"]
    assert "Index futures (ES/NQ) settle on the opening quotation" in quad["detail"]
    assert quad["url"] == C.SPX_OPTIONS_URL

    october = _expiries(date(2026, 10, 1), date(2026, 10, 31))["monthly_opex:2026-10-16"]
    assert "SPX standard options settle on the OPENING prices" in october["detail"]
    assert "ES/NQ" not in october["detail"]
    assert october["url"] == C.SPX_OPTIONS_URL


# --- The after-a-large-move flag -------------------------------------------------

def _closes(returns: list[float], session: date, symbols=("SPY", "QQQ")) -> pd.DataFrame:
    """Closes for ``returns`` that end on ``session``; a base close precedes the first return."""
    index = pd.bdate_range(end=pd.Timestamp(session), periods=len(returns) + 1)
    frame = {}
    for symbol in symbols:
        path = 100 * np.cumprod(np.r_[1.0, 1.0 + np.asarray(returns)])
        frame[symbol] = path
    return pd.DataFrame(frame, index=index)


CALM = [0.005, -0.005] * 40                              # 80 sessions, sigma about 0.5%


def test_a_move_beyond_two_sigma_in_the_last_five_sessions_fires_with_its_own_reading():
    session = date(2026, 9, 15)
    closes = _closes(CALM + [0.0, 0.0, 0.0, 0.0, -0.04], session)
    shock = C.recent_shock(closes, session, funds=["SPY", "QQQ"], lookback=5, window=60, z_limit=2.0)
    assert shock["fund"] == "SPY" and shock["date"] == "2026-09-15" and shock["return_pct"] == -4.0
    # Sigma is the 60 sessions before the move, so the move does not count itself.
    prior_sigma = pd.Series((CALM + [0.0] * 4)[-60:]).std()
    assert shock["z"] == pytest.approx(-0.04 / prior_sigma, abs=0.01)


def test_a_smaller_move_does_not_fire():
    session = date(2026, 9, 15)
    closes = _closes(CALM + [0.0, 0.0, 0.0, 0.0, -0.006], session)      # about 1.2 sigma
    assert C.recent_shock(closes, session, funds=["SPY", "QQQ"], lookback=5, window=60, z_limit=2.0) is None


def test_a_large_move_older_than_the_lookback_does_not_fire():
    session = date(2026, 9, 15)
    closes = _closes(CALM + [-0.04, 0.0, 0.0, 0.0, 0.0, 0.0], session)  # the move is six sessions back
    assert C.recent_shock(closes, session, funds=["SPY", "QQQ"], lookback=5, window=60, z_limit=2.0) is None


def test_either_fund_counts_and_a_gap_in_the_window_is_not_used():
    session = date(2026, 9, 15)
    spy = _closes(CALM + [0.0, 0.0, 0.0, 0.0, 0.0], session, symbols=("SPY",))["SPY"]
    qqq_returns = CALM + [0.0, 0.0, 0.0, 0.0, 0.05]
    closes = pd.concat([spy, _closes(qqq_returns, session, symbols=("QQQ",))["QQQ"]], axis=1)
    shock = C.recent_shock(closes, session, funds=["SPY", "QQQ"], lookback=5, window=60, z_limit=2.0)
    assert shock["fund"] == "QQQ" and shock["return_pct"] == 5.0
    # A missing close inside the window leaves too few returns to measure sigma: no flag.
    gapped = closes.copy()
    gapped.iloc[-30, gapped.columns.get_loc("QQQ")] = np.nan
    assert C.recent_shock(gapped, session, funds=["QQQ"], lookback=5, window=60, z_limit=2.0) is None


def test_the_flag_goes_on_the_expiries_within_three_sessions_only():
    session = date(2026, 9, 15)                              # next sessions: 16, 17, 18 September
    closes = _closes(CALM + [0.0, 0.0, 0.0, 0.0, -0.04], session)
    events = [
        {"rule": "quad_witching", "date": "2026-09-18", "title": "quad"},      # third session ahead: flagged
        {"rule": "monthly_opex", "date": "2026-09-21", "title": "later"},      # fourth: not
        {"rule": "vix_expiry", "date": "2026-09-16", "title": "vix"},          # not a monthly or quarterly expiry
        {"rule": None, "date": "2026-09-16", "title": "CPI"},
    ]
    C.expiry_watch(events, closes, session, SETTINGS)
    watch = events[0]["expiry_watch"]
    assert (watch["fund"], watch["date"], watch["return_pct"]) == ("SPY", "2026-09-15", -4.0)
    assert watch["z"] == pytest.approx(-0.04 / pd.Series((CALM + [0.0] * 4)[-60:]).std(), abs=0.01)
    assert all("expiry_watch" not in e for e in events[1:])


def test_no_large_move_means_no_flag_on_any_expiry():
    session = date(2026, 9, 15)
    closes = _closes(CALM + [0.0] * 5, session)
    events = [{"rule": "quad_witching", "date": "2026-09-18"}]
    C.expiry_watch(events, closes, session, SETTINGS)
    assert "expiry_watch" not in events[0]


def test_the_shipped_thresholds_are_under_catalysts_and_match_the_rule_settings():
    config = tomllib.loads((ROOT / "config" / "dashboard.toml").read_text())["catalysts"]
    assert {k: config[k] for k in SETTINGS} == SETTINGS


# --- The panel carries the rule and the importance ----------------------------------

def test_quad_witching_is_high_importance_and_the_monthly_and_vix_stay_as_configured(monkeypatch):
    config = tomllib.loads((ROOT / "config" / "dashboard.toml").read_text())["catalysts"]
    for name in ("fetch_bls", "fetch_bea", "fetch_census", "fetch_fed", "fetch_treasury"):
        monkeypatch.setattr(panel.calendars, name, lambda **kw: [])
    monkeypatch.setattr(panel, "_prints", lambda specs, use_cache, cache: [])
    ctx = type("C", (), {"as_of": "2026-09-15", "log": type("L", (), {"add": lambda self, record: None})()})()
    events, _, _ = panel._macro(ctx, config, date(2026, 9, 15), date(2026, 10, 20), True)
    by = {(e["rule"], e["date"]): e for e in events if e.get("rule")}
    quad = by[("quad_witching", "2026-09-18")]
    assert quad["importance"] == "high" and "OPENING prices" in quad["detail"]
    assert by[("monthly_opex", "2026-10-16")]["importance"] == "medium"
    vix = [e for e in events if e.get("rule") == "vix_expiry"]
    assert vix and all(e["importance"] == "low" for e in vix)


def test_next_expiries_reach_past_the_calendar_window():
    from datetime import date
    from market_recap.compute import catalysts as C
    out = {e["rule"]: e["date"] for e in C.next_expiries(date(2026, 10, 16))}
    assert out["monthly_opex"] == "2026-11-20"
    assert out["quad_witching"] == "2026-12-18"
    assert out["vix_expiry"] == "2026-10-21"
