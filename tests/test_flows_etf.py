"""ETF flows: daily creations less redemptions, split and gap exclusion, windows, the 1-week percentile, aggregates, and the section payload."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import etf_flows as F
from market_recap.sources.http import FetchError
from market_recap.panels import flows_etf as P
from market_recap.util import BuildLog


def _bdays(n, start="2023-01-02"):
    return pd.bdate_range(start, periods=n)


def _frame(shares, nav, dates=None):
    dates = _bdays(len(shares)) if dates is None else dates
    return pd.Series(shares, index=dates, dtype=float), pd.Series(nav, index=dates, dtype=float)


# --- daily flow ----------------------------------------------------------------

def test_flow_is_change_in_units_at_that_days_nav():
    shares, nav = _frame([100.0, 110.0, 105.0], [10.0, 11.0, 12.0])
    flow = F.daily_flow(shares, nav)
    assert np.isnan(flow.iloc[0])
    assert flow.iloc[1] == pytest.approx((110 - 100) * 11.0)
    assert flow.iloc[2] == pytest.approx((105 - 110) * 12.0)


def test_missing_count_is_missing_flow_never_forward_filled():
    shares, nav = _frame([100.0, np.nan, 110.0, 111.0], [10.0, 10.0, 10.0, 10.0])
    flow = F.daily_flow(shares, nav)
    assert np.isnan(flow.iloc[1])  # no count that day
    assert np.isnan(flow.iloc[2])  # no count to difference against
    assert flow.iloc[3] == pytest.approx(10.0)


def test_two_for_one_split_is_withheld_and_listed():
    shares, nav = _frame([100.0, 100.0, 200.0, 201.0], [40.0, 40.0, 20.0, 20.0])
    flow = F.daily_flow(shares, nav)
    assert np.isnan(flow.iloc[2])
    assert flow.iloc[3] == pytest.approx(20.0)
    days = F.excluded_days(shares, nav)
    assert [d for d, _ in days] == [shares.index[2]]
    assert "split" in days[0][1]


def test_split_with_a_market_move_on_the_day_is_still_a_split():
    # XLY on 2025-12-05 moved 1.9499x units against a 0.5027x NAV: a 2:1 split on a down day.
    shares, nav = _frame([100.0, 194.99], [50.0, 25.135])
    assert bool(F.split_mask(shares, nav).iloc[1])


def test_reverse_split_is_withheld():
    shares, nav = _frame([1000.0, 100.0], [5.0, 50.0])
    assert bool(F.split_mask(shares, nav).iloc[1])


def test_a_creation_that_doubles_units_at_flat_nav_is_money_not_a_split():
    shares, nav = _frame([100.0, 200.0], [50.0, 50.0])
    assert not bool(F.split_mask(shares, nav).iloc[1])
    assert F.daily_flow(shares, nav).iloc[1] == pytest.approx(100 * 50.0)


def test_a_missing_session_is_a_gap_and_a_holiday_is_not():
    dates = pd.DatetimeIndex(["2024-05-23", "2024-05-24", "2024-05-28", "2024-05-29"])  # 27th: Memorial day
    shares, nav = _frame([100.0, 101.0, 102.0, 103.0], [10.0, 10.0, 10.0, 10.0], dates=dates)
    sessions = pd.DatetimeIndex(["2024-05-23", "2024-05-24", "2024-05-28", "2024-05-29"])
    assert F.daily_flow(shares, nav, sessions=sessions).notna().iloc[1:].all()

    # Drop 2024-05-28 from the record while the calendar still has it: the next flow spans two sessions.
    gapped = shares.drop(dates[2])
    gapped_nav = nav.drop(dates[2])
    flow = F.daily_flow(gapped, gapped_nav, sessions=sessions)
    assert np.isnan(flow.iloc[-1])
    assert F.excluded_days(gapped, gapped_nav, sessions=sessions)[0][1].startswith("gap")


def test_without_a_calendar_a_week_long_hole_is_a_gap():
    dates = pd.DatetimeIndex(["2024-05-22", "2024-05-23", "2024-05-31"])
    shares, nav = _frame([100.0, 101.0, 105.0], [10.0, 10.0, 10.0], dates=dates)
    flow = F.daily_flow(shares, nav)
    assert np.isnan(flow.iloc[2])
    assert flow.iloc[1] == pytest.approx(10.0)


# --- windows and the percentile ---------------------------------------------------

def test_window_sum_is_none_when_history_is_short_or_a_day_is_withheld():
    flow = pd.Series([np.nan, 1.0, 2.0, 3.0, 4.0, 5.0])
    assert F.window_sum(flow, 5) == 15.0
    assert F.window_sum(flow, 6) is None
    holed = flow.copy()
    holed.iloc[-2] = np.nan
    assert F.window_sum(holed, 3) is None


def test_percentile_is_share_of_rolling_five_day_sums_at_or_below_latest():
    dates = _bdays(400)
    flow = pd.Series(np.arange(400, dtype=float), index=dates)  # every 5-day sum rises: latest is the largest
    assert F.percentile_1w(flow) == 100.0
    flow.iloc[-1] = -1e9  # latest 5-day sum is now the smallest
    assert F.percentile_1w(flow) == 0.0


def test_percentile_is_none_without_a_year_of_history():
    flow = pd.Series(np.ones(200), index=_bdays(200))
    assert F.percentile_1w(flow) is None


def test_fund_summary_scales_one_month_by_assets():
    flow = pd.Series(np.full(70, 2.0), index=_bdays(70))
    summary = F.fund_summary(flow, aum=1000.0)
    assert summary["flow_1m"] == 42.0
    assert summary["flow_1m_pct_aum"] == pytest.approx(0.042)
    assert summary["flow_3m"] == 126.0
    assert F.fund_summary(flow, aum=None)["flow_1m_pct_aum"] is None


# --- aggregates ---------------------------------------------------------------

def test_aggregate_sums_only_funds_with_a_value_that_day():
    dates = _bdays(300)
    a = pd.Series(1.0, index=dates)
    b = pd.Series(10.0, index=dates)
    b.iloc[-3] = np.nan
    total = F.aggregate({"A": a, "B": b})
    assert total["funds"] == ["A", "B"] and total["excluded"] == []
    assert total["count"][-3] == 1 and total["flow"][-3] == 1.0
    assert total["count"][-1] == 2 and total["flow"][-1] == 11.0
    assert len(total["dates"]) == F.AGGREGATE_WINDOW
    # The last 20 totals: nineteen of 11.0 and the one day B was missing, which counts only A.
    assert total["rolling_20"][-1] == pytest.approx(19 * 11.0 + 1.0)


def test_aggregate_leaves_out_a_fund_whose_history_starts_inside_the_window():
    dates = _bdays(300)
    full = pd.Series(1.0, index=dates)
    young = pd.Series(50.0, index=dates[-100:])  # a fund recorded for 100 sessions
    total = F.aggregate({"FULL": full, "YOUNG": young})
    assert total["funds"] == ["FULL"]
    assert total["excluded"] == ["YOUNG"]
    assert all(c == 1 for c in total["count"])


def test_aggregate_latest_week_and_rank():
    dates = _bdays(400)
    flow = pd.Series(np.arange(400, dtype=float), index=dates)
    total = F.aggregate({"A": flow})
    assert total["latest"]["flow_1w"] == pytest.approx(sum(range(395, 400)))
    assert total["latest"]["pct_rank_1w"] == 100.0


def test_empty_aggregate_is_empty_not_an_error():
    total = F.aggregate({})
    assert total["funds"] == [] and total["dates"] == [] and total["latest"] == {}


# --- section payload, with providers patched out -----------------------------

def _provider(frames):
    def fetch(ticker, *, use_cache=True):
        if ticker not in frames:
            raise FetchError(f"{ticker}: not covered", not_found=True)
        return frames[ticker], f"https://issuer.example/{ticker}.xlsx"
    return fetch


def _history(n, *, start="2023-01-02", shares0=1000.0, growth=0.001, nav=50.0, tna=True, stale_from=None):
    dates = _bdays(n, start)
    shares = shares0 * (1 + growth) ** np.arange(n)
    if stale_from is not None:
        shares[stale_from:] = shares[stale_from]
    frame = pd.DataFrame({"date": dates, "nav": nav, "shares_outstanding": shares})
    if tna:
        frame["total_net_assets"] = frame["nav"] * frame["shares_outstanding"]
    return frame


def _ctx(sessions):
    closes = pd.DataFrame(1.0, index=sessions, columns=["SPY"])
    return SimpleNamespace(as_of=str(sessions[-1].date()), etf_closes=closes, log=BuildLog())


def test_build_payload_is_json_clean_and_lists_every_fund(monkeypatch):
    frames = {
        "SPY": _history(600), "IVV": _history(600, shares0=500.0),
        "XLK": _history(600), "QQQ": _history(10, start="2026-10-01", tna=False),
        "SHY": _history(600, tna=False), "IEF": _history(600, tna=False), "TLT": _history(600, tna=False),
        "LQD": _history(600, tna=False), "HYG": _history(600, tna=False),
        "GLD": _history(600),
    }
    providers = (
        ("ssga_nav_history", "State Street", _provider({k: v for k, v in frames.items() if k in ("SPY", "XLK", "GLD")}), "https://www.ssga.com"),
        ("ishares_nav_history", "iShares", _provider({k: v for k, v in frames.items() if k in ("IVV", "SHY", "IEF", "TLT", "LQD", "HYG")}), "https://www.ishares.com"),
        ("invesco_recorded", "Invesco recorded", _provider({"QQQ": frames["QQQ"]}), "https://www.invesco.com"),
    )
    monkeypatch.setattr(P.H, "FLOW_PROVIDERS", providers)
    # The uncovered funds' assets: VOO from the heat map, the other Vanguard funds from
    # Vanguard's month-end figure, Schwab's from Yahoo -- all stubbed, no network.
    monkeypatch.setattr(P.vanguard, "fetch_share_class_assets", lambda t, **k: (1e11, "2026-09-30"))
    monkeypatch.setattr(P.yahoo, "fetch_fund_snapshot",
                        lambda tickers: pd.DataFrame({"ticker": list(tickers), "aum": [5e10] * len(tickers)}))
    sessions = _bdays(600)
    ctx = _ctx(sessions)
    heat = {"etfs": [{"ticker": "VOO", "aum": 1e12, "aum_source": "vanguard_share_class"}]}
    out = P.build(ctx, {"heatmaps": heat})
    text = json.dumps(out, allow_nan=False)  # would raise on NaN or inf
    assert "NaN" not in text

    tickers = [r["ticker"] for r in out["funds"]]
    assert tickers == [t for t, _, _ in F.FUNDS]
    assert [n["ticker"] for n in out["not_covered"]] == [t for t, _, _, _ in F.NOT_COVERED]
    voo = next(n for n in out["not_covered"] if n["ticker"] == "VOO")
    assert voo["aum"] == 1e12 and voo["aum_basis"] == "vanguard_share_class"
    assert next(n for n in out["not_covered"] if n["ticker"] == "SCHB")["aum_basis"] == "yahoo_total_assets"

    # The S&P 500 group measures SPY and IVV against those plus VOO: its coverage says so.
    sp = next(a for a in out["aggregates"] if a["name"] == "S&P 500")
    assert set(sp["latest_funds"]) == {"SPY", "IVV"}
    # SPYM has no file in this test, so it is missing beside VOO; with no assets known it adds nothing.
    assert sp["coverage"]["missing"] == ["SPYM", "VOO"]
    assert sp["coverage"]["pct"] == pytest.approx(
        100 * sp["coverage"]["covered_aum"] / (sp["coverage"]["covered_aum"] + 1e12), abs=1)
    # QQQ's ten recorded sessions are in the Nasdaq-100 week, though not in a rank.
    ndx = next(a for a in out["aggregates"] if a["name"] == "Nasdaq-100")
    assert ndx["latest_funds"] == ["QQQ"] and ndx["latest"]["flow_1w"] is not None
    assert ndx["latest"]["pct_rank_1w"] is None

    spy = next(r for r in out["funds"] if r["ticker"] == "SPY")
    assert spy["source_id"] == "ssga_nav_history" and spy["flow_1d"] is not None
    assert spy["pct_rank_1w"] is not None  # 600 sessions: a year of history
    assert spy["flow_1m_pct_aum"] == pytest.approx(spy["flow_1m"] / spy["aum"], rel=1e-3)

    qqq = next(r for r in out["funds"] if r["ticker"] == "QQQ")
    assert qqq["pct_rank_1w"] is None and "recorded nightly" in qqq["note"]
    assert out["invesco_recorded_since"] == "2026-10-01"

    us = next(a for a in out["aggregates"] if a["name"] == "US equity")
    assert "QQQ" not in us["funds"] and "SPY" in us["funds"] and "QQQ" in us["excluded"]
    assert out["headline"]["date"] == us["latest_date"]
    assert len(out["headline"]["top_in"]) == 3  # every fund here is growing its units
    assert ctx.log.sources  # one record per issuer provider


def test_build_reports_a_provider_error_and_carries_on(monkeypatch):
    def challenged(ticker, *, use_cache=True):
        raise RuntimeError("HTTP 403 challenge page")

    monkeypatch.setattr(P.H, "FLOW_PROVIDERS", (
        ("ssga_nav_history", "State Street", challenged, "https://www.ssga.com"),
        ("ishares_nav_history", "iShares", _provider({"SPY": _history(300)}), "https://www.ishares.com"),
    ))
    ctx = _ctx(_bdays(300))
    out = P.build(ctx, {})
    assert "unavailable" not in out
    errors = [s for s in ctx.log.sources if s.source_id == "flows_etf_errors"]
    assert errors and errors[0].status == "partial" and "403" in errors[0].error


def test_build_is_unavailable_when_no_fund_reads(monkeypatch):
    monkeypatch.setattr(P.H, "FLOW_PROVIDERS", (
        ("ssga_nav_history", "State Street", _provider({}), "https://www.ssga.com"),
    ))
    ctx = _ctx(_bdays(50))
    out = P.build(ctx, {})
    assert set(out) == {"unavailable"}
    assert ctx.log.sources[-1].status == "error"


def test_a_frozen_issuer_count_blanks_the_windows_it_covers(monkeypatch):
    frozen = _history(300, stale_from=200)
    monkeypatch.setattr(P.H, "FLOW_PROVIDERS", (
        ("ssga_nav_history", "State Street", _provider({"SPY": frozen}), "https://www.ssga.com"),
    ))
    out = P.build(_ctx(_bdays(300)), {})
    spy = next(r for r in out["funds"] if r["ticker"] == "SPY")
    assert spy["stale"] is True
    assert spy["flow_1m"] is None
    assert spy["shares_unchanged_since"] is not None
    assert spy["flow_3m"] is None  # the 63-session window lies wholly inside the 99 frozen sessions


def test_a_recent_fund_counts_in_the_latest_week_but_not_in_the_line_or_its_rank():
    long = pd.Series(1e8, index=_bdays(400))
    recent = pd.Series(5e8, index=_bdays(400)[-30:])
    out = F.aggregate({"OLD": long, "NEW": recent})
    assert out["funds"] == ["OLD"] and out["excluded"] == ["NEW"]
    assert out["latest_funds"] == ["OLD", "NEW"]
    assert out["latest"]["flow_1w"] == pytest.approx(5 * (1e8 + 5e8))
    assert out["flow"][-1] == pytest.approx(1e8)  # the day-by-day line keeps to OLD


def test_a_fund_whose_record_stopped_is_not_in_the_latest_week():
    days = _bdays(400)
    out = F.aggregate({"LIVE": pd.Series(1e8, index=days), "STOPPED": pd.Series(5e8, index=days[:-10])})
    assert out["latest_funds"] == ["LIVE"]
    assert out["latest"]["flow_1w"] == pytest.approx(5e8)
