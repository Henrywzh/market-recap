"""MONITOR v1: exact-session calculations and prospective ledger behavior."""

from __future__ import annotations

from types import SimpleNamespace
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import monitor as M
from market_recap.panels import monitor


AS_OF = "2026-09-22"


def _dates(as_of=AS_OF, count=270):
    return pd.DatetimeIndex(M.exchange_sessions_ending(as_of, count))


def _config():
    return {
        "monitor": {
            "index": "SPX",
            "drawdown_period": "1Y",
            "threshold_pct": 20.0,
            "relative_period": "1M",
            "ma_sessions": 20,
            "earnings_days": 30,
        },
        "universe": {
            "market_proxy": "MKT",
            "sectors": {"Technology": "XLTECH"},
            "indices": [{"key": "SPX", "label": "S&P 500"}],
        },
    }


def _ctx(
    *,
    as_of=AS_OF,
    members=("AAA", "BBB"),
    close_dates=None,
    close_values=None,
    price_dates=None,
    valuation=None,
    catalysts=None,
):
    dates = close_dates if close_dates is not None else _dates(as_of)
    close_values = close_values or {}
    closes = pd.DataFrame(index=dates)
    for ticker in members:
        values = close_values.get(ticker)
        closes[ticker] = np.asarray(values if values is not None else np.linspace(100, 80, len(dates)))

    benchmark = pd.DataFrame(index=dates)
    benchmark["MKT"] = np.linspace(100, 110, len(dates))
    benchmark["XLTECH"] = np.linspace(100, 105, len(dates))
    prices = closes[list(members)].copy()
    if price_dates is not None:
        prices = prices.loc[prices.index.isin(price_dates)]
    frame = pd.DataFrame({
        "yahoo_symbol": list(members),
        "name": [f"{ticker} Corp" for ticker in members],
        "sector": ["Technology" for _ in members],
    })
    return SimpleNamespace(
        as_of=as_of,
        config=_config(),
        indices=[SimpleNamespace(key="SPX", label="S&P 500")],
        members={"SPX": frame},
        holdings_dates={"SPX": "2026-09-21"},
        closes=closes,
        prices=prices,
        etf_closes=benchmark,
        index_closes=pd.DataFrame(index=dates),
        valuation=valuation,
        catalysts=catalysts,
    )


def _row(payload, ticker):
    return next(row for row in payload["rows"] if row["ticker"] == ticker)


def test_drawdown_requires_252_exchange_sessions_and_uses_adjusted_closes():
    dates = _dates(count=252)
    adjusted = np.full(252, 100.0)
    adjusted[-1] = 80.0
    ctx = _ctx(members=("AAA",), close_dates=dates, close_values={"AAA": adjusted})
    payload = monitor.build(ctx)
    row = _row(payload, "AAA")
    assert row["drawdown_pct"] == pytest.approx(-20.0)
    assert row["price_as_of"] == AS_OF
    assert row["history"] == [[AS_OF, -20.0]]

    # ``prices`` is intentionally a different split-only quote.  Drawdown is
    # based on adjusted closes, not the display quote.
    ctx.prices.loc[pd.Timestamp(AS_OF), "AAA"] = 40.0
    assert _row(monitor.build(ctx), "AAA")["drawdown_pct"] == pytest.approx(-20.0)

    near_boundary = adjusted.copy()
    near_boundary[-1] = 80.0008
    precise = _row(monitor.build(_ctx(members=("AAA",), close_dates=dates,
                                 close_values={"AAA": near_boundary})), "AAA")
    assert precise["drawdown_pct"] > -20.0
    assert precise["history"][-1][1] == precise["drawdown_pct"]
    assert precise["drawdown_pct"] == pytest.approx(-19.9992, abs=1e-10)

    short = _ctx(members=("AAA",), close_dates=dates[:-1], close_values={"AAA": adjusted[:-1]})
    short_row = _row(monitor.build(short), "AAA")
    assert short_row["drawdown_pct"] is None
    assert any("252 exchange sessions" in gap for gap in short_row["gaps"])


def test_exchange_calendar_does_not_compress_a_missing_session():
    dates = _dates(count=252)
    adjusted = np.full(252, 100.0)
    adjusted[-1] = 80.0
    missing = dates[100]
    sparse = pd.DataFrame({"AAA": adjusted}, index=dates).drop(index=missing)
    values, reason = M.drawdown(sparse["AAA"], AS_OF, 252)
    assert values is None
    assert str(missing.date()) in reason


def test_relative_returns_are_basic_percentage_point_subtractions_and_rs_is_independent():
    dates = _dates(count=252)
    stock = np.full(252, 100.0)
    # The preceding 1M ratio is negative (100 -> 90); the current 1M ratio is
    # positive (90 -> 99), so the improvement flag is true.
    stock[-43:-21] = np.linspace(100.0, 90.0, 22)
    stock[-22:] = np.linspace(90.0, 99.0, 22)
    # Relative strength is measured against the other sector members (here a
    # flat BBB), never against a basket that contains the company itself.
    ctx = _ctx(members=("AAA", "BBB"), close_dates=dates,
               close_values={"AAA": stock, "BBB": np.full(252, 100.0)})
    ctx.etf_closes.loc[dates[-22:], "MKT"] = np.linspace(100.0, 110.0, 22)
    ctx.etf_closes.loc[dates[-22:], "XLTECH"] = np.linspace(100.0, 105.0, 22)
    payload = monitor.build(ctx)
    row = _row(payload, "AAA")
    assert row["market_benchmark"] == "MKT"
    assert row["sector_benchmark"] == "XLTECH"
    # The stock's latest 1M return is 10%; these are percentage points, not a
    # regression residual or a multiplicative ratio.
    assert row["market_excess_pct"] == pytest.approx(0.0, abs=0.15)
    assert row["sector_excess_pct"] == pytest.approx(5.0, abs=0.15)
    assert row["rs_improving"] is True
    assert row["peer_count"] == 1
    assert row["peer_excess_pct"] == pytest.approx(10.0, abs=0.15)
    # BBB's only peer is AAA, which fell then recovered: BBB lost ground over
    # the latest month, so its relative strength did not improve.
    assert _row(payload, "BBB")["rs_improving"] is False


def test_metric_coverage_is_individual_and_never_uses_a_stale_last_value():
    dates = _dates(count=252)
    values = np.linspace(100, 80, 252)
    values[100] = np.nan  # outside the short relative/MA windows
    ctx = _ctx(members=("AAA", "BBB"), close_dates=dates,
               close_values={"AAA": values, "BBB": np.full(252, 100.0)})
    # BBB's current adjusted close is absent, while both benchmarks are full.
    ctx.closes.loc[pd.Timestamp(AS_OF), "BBB"] = np.nan
    ctx.prices = ctx.prices.drop(index=pd.Timestamp(AS_OF))
    payload = monitor.build(ctx)
    row = _row(payload, "BBB")
    assert row["drawdown_pct"] is None
    assert row["market_benchmark"] == "MKT"
    assert row["sector_benchmark"] == "XLTECH"
    assert row["market_excess_pct"] is None
    assert row["sector_excess_pct"] is None
    assert row["above_ma"] is None
    assert row["price_as_of"] is None

    # AAA's old missing print does not affect its current 20-session MA or
    # 1M return, but it does invalidate the full drawdown window.
    aaa = _row(payload, "AAA")
    assert aaa["drawdown_pct"] is None
    assert aaa["above_ma"] is not None
    assert aaa["market_benchmark"] is not None


def test_valuation_and_catalysts_are_same_session_and_price_validated():
    dates = _dates(count=252)
    values = np.full(252, 100.0)
    values[-1] = 80.0
    valuation = {
        "as_of": AS_OF,
        "rows": [
            {"ticker": "AAA", "price": 40.0, "pe": 10.0, "pe_history_current": 10.0,
             "pe_percentile": 60.0, "pe_vs_median": 5.0, "fcf_yield": 2.0,
             "revenue_growth": 8.0, "filed": "2026-08-01", "period_end": "2026-06-30"},
            {"ticker": "BBB", "price": 999.0, "pe": 12.0, "fcf": -1.0,
             "revenue_growth": -3.0, "filed": "2026-08-01", "period_end": "2026-06-30"},
        ],
        "weight_check": {"flagged": []},
        "pe_history": {"disagree": ["BBB"]},
    }
    catalysts = {
        "as_of": AS_OF,
        "events": [
            {"lane": "single_name", "event_type": "earnings", "symbol": "AAA",
             "date": "2026-09-30", "timing": "amc"},
        ],
        "failed_sources": {},
    }
    ctx = _ctx(members=("AAA", "BBB"), close_dates=dates,
               close_values={"AAA": values, "BBB": values})
    # The adjusted close is 80 while the split-only valuation quote is 40.
    # The validation must use the latter, while price_as_of still follows the
    # current adjusted close date.
    ctx.prices["AAA"] = ctx.prices["AAA"] / 2.0
    payload = monitor.build(ctx, valuation=valuation, catalysts=catalysts)
    aaa, bbb = _row(payload, "AAA"), _row(payload, "BBB")
    assert aaa["pe"] == 10.0 and aaa["fcf_positive"] is True
    assert aaa["revenue_growth_pct"] == 8.0
    assert aaa["earnings_date"] == "2026-09-30"
    assert aaa["earnings_status"] == "after_close"
    assert aaa["estimate_revision"] is None
    assert bbb["pe"] is None and bbb["pe_percentile"] is None
    assert bbb["fcf_positive"] is False  # direct FCF remains a fundamental fact
    assert any("stale" in gap for gap in bbb["gaps"])
    assert any("P/E" in gap for gap in bbb["gaps"])

    unavailable = monitor.build(ctx, valuation={"as_of": "2026-09-21", "rows": []}, catalysts=None)
    missing = _row(unavailable, "AAA")
    assert missing["pe"] is None and missing["earnings_date"] is None
    assert any("as_of mismatch" in gap for gap in missing["gaps"])
    assert any("optional panel was not supplied" in gap for gap in missing["gaps"])

    failed_calendar = monitor.build(
        ctx,
        catalysts={"as_of": AS_OF, "events": [], "failed_sources": {"nasdaq": "refused"}},
    )
    failed_row = _row(failed_calendar, "AAA")
    assert failed_row["earnings_date"] is None and failed_row["earnings_status"] is None
    assert any("Nasdaq calendar failed" in gap for gap in failed_row["gaps"])


def test_first_observation_rerun_rollback_and_removed_rows_preserve_only_ledger_state():
    dates = _dates(count=252)
    first_values = np.full(252, 100.0)
    first_values[-1] = 80.0
    first_ctx = _ctx(close_dates=dates, close_values={"AAA": first_values, "BBB": first_values})
    first = monitor.build(first_ctx)
    assert first["tracking_started"] == AS_OF
    assert len(_row(first, "AAA")["history"]) == 1

    # A same-session rerun replaces, rather than duplicates, its observation.
    rerun_values = first_values.copy()
    rerun_values[-1] = 70.0
    rerun_ctx = _ctx(close_dates=dates, close_values={"AAA": rerun_values, "BBB": first_values})
    rerun = monitor.build(rerun_ctx, previous=first)
    assert _row(rerun, "AAA")["history"] == [[AS_OF, -30.0]]
    assert len(_row(rerun, "AAA")["history"]) == 1

    later = "2026-09-23"
    later_dates = _dates(later, 252)
    later_values = np.full(252, 100.0)
    later_values[-1] = 75.0
    later_ctx = _ctx(as_of=later, members=("AAA",), close_dates=later_dates,
                     close_values={"AAA": later_values})
    advanced = monitor.build(later_ctx, previous=first)
    assert [point[0] for point in _row(advanced, "AAA")["history"]] == [AS_OF, later]
    removed = _row(advanced, "BBB")
    assert removed["in_universe"] is False
    assert removed["name"] == "BBB Corp"
    assert removed["history"] == [[AS_OF, -20.0], [later, None]]
    assert removed["drawdown_pct"] is None and removed["pe"] is None
    assert removed["price_as_of"] is None
    assert removed["gaps"] == ["outside universe"]

    with pytest.raises(ValueError, match="rollback rejected"):
        monitor.build(first_ctx, previous=advanced)


def test_book_multiples_are_carried_for_financials_only():
    dates = _dates(count=252)
    values = np.full(252, 100.0)
    valuation = {
        "as_of": AS_OF,
        "rows": [{"ticker": t, "price": 100.0, "pe": 12.0, "pe_history_current": 12.0, "ptbv": 1.86,
                  "ptbv_percentile": 84.9, "rotce": 15.74} for t in ("AAA", "BBB")],
        "weight_check": {"flagged": []}, "pe_history": {"disagree": []},
    }
    ctx = _ctx(members=("AAA", "BBB"), close_dates=dates, close_values={"AAA": values, "BBB": values})
    ctx.members["SPX"].loc[ctx.members["SPX"]["yahoo_symbol"] == "AAA", "sector"] = "Financials"
    payload = monitor.build(ctx, valuation=valuation, catalysts=None)
    bank, other = _row(payload, "AAA"), _row(payload, "BBB")
    assert (bank["ptbv"], bank["ptbv_percentile"], bank["rotce"]) == (1.86, 84.9, 15.7)
    # A non-financial's tangible book is not what it earns on.
    assert (other["ptbv"], other["ptbv_percentile"], other["rotce"]) == (None, None, None)
