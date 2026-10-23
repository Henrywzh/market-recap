"""FLOWS section B: CFTC futures positioning by trader type. No network: synthetic reports and closes."""

from datetime import date
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import cot as C
from market_recap.panels import flows_cot as panel
from market_recap.sources import cftc
from market_recap.util import BuildLog


def _weekly(values, end="2026-10-13", periods=None):
    """Tuesday-indexed weekly series ending on ``end``."""
    periods = periods or len(values)
    index = pd.date_range(end=end, periods=periods, freq="7D")
    return pd.Series(values, index=index, dtype=float)


# --- source: one row per report date and code, every category, from Socrata ----------------

def _socrata_row(code="13874A", report="2026-10-13", **overrides):
    row = {
        "report_date_as_yyyy_mm_dd": f"{report}T00:00:00.000",
        "cftc_contract_market_code": code,
        "open_interest_all": "1000000",
        "dealer_positions_long_all": "100", "dealer_positions_short_all": "300",
        "asset_mgr_positions_long": "500", "asset_mgr_positions_short": "200",
        "lev_money_positions_long": "120", "lev_money_positions_short": "400",
        "other_rept_positions_long": "30", "other_rept_positions_short": "50",
        "nonrept_positions_long_all": "60", "nonrept_positions_short_all": "10",
        "traders_tot_all": "444", "traders_lev_money_long_all": "62", "traders_lev_money_short_all": "79",
    }
    row.update(overrides)
    return row


def test_categories_are_parsed_as_numbers_with_net_left_to_the_caller(monkeypatch):
    captured = {}

    def fake_get_text(url, **kwargs):
        captured["url"] = url
        return json.dumps([_socrata_row(), _socrata_row(report="2026-10-06", lev_money_positions_short="390")])

    monkeypatch.setattr(cftc, "get_text", fake_get_text)
    monkeypatch.setattr(cftc.cache, "fetch_text", lambda ns, name, fetch, **kw: fetch())
    frame = cftc.fetch_tff_categories(["13874A", "209742"], start="2024-01-01")

    assert list(frame.columns) == cftc.CATEGORY_COLUMNS
    assert frame["date"].tolist() == [pd.Timestamp("2026-10-06"), pd.Timestamp("2026-10-13")]
    assert frame["lev_money_short"].tolist() == [390.0, 400.0]
    assert pd.api.types.is_numeric_dtype(frame["open_interest"])
    # Futures only, both contracts, the report's own date filter, and a bounded row count.
    assert "FutOnly" in captured["url"]
    assert "13874A" in captured["url"] and "209742" in captured["url"]


def test_missing_trader_count_is_nan_not_zero(monkeypatch):
    row = _socrata_row()
    row.pop("traders_lev_money_long_all")
    monkeypatch.setattr(cftc, "get_text", lambda url, **kw: json.dumps([row]))
    monkeypatch.setattr(cftc.cache, "fetch_text", lambda ns, name, fetch, **kw: fetch())
    frame = cftc.fetch_tff_categories(["13874A"])
    assert np.isnan(frame["traders_lev_money_long"].iloc[0])
    assert frame["traders_total"].iloc[0] == 444


def test_empty_response_keeps_the_columns(monkeypatch):
    monkeypatch.setattr(cftc, "get_text", lambda url, **kw: "[]")
    monkeypatch.setattr(cftc.cache, "fetch_text", lambda ns, name, fetch, **kw: fetch())
    frame = cftc.fetch_tff_categories(["13874A"])
    assert frame.empty and list(frame.columns) == cftc.CATEGORY_COLUMNS


def test_the_existing_fetch_tff_keeps_its_columns_and_cache_key():
    # panels/risk.py depends on these; the new function must not change them.
    import inspect
    source = inspect.getsource(cftc.fetch_tff)
    assert 'NAMESPACE, "tff-" + "-".join(sorted(codes))' in source
    assert '"lev_money_positions_long"' in source
    assert '["date", "code", "open_interest", "long", "short", "net", "net_pct_oi"]' in source


# --- compute: shares of open interest, three-year percentile, z, week change, dollars -------

def test_percentile_and_z_use_only_the_trailing_156_weekly_reports():
    values = list(range(100))  # 0..99, latest 99
    pct = _weekly(values)
    assert C.percentile_3y(pct) is None  # 100 < 156: no three-year sample
    long = _weekly(list(range(200)))
    assert C.percentile_3y(long) == pytest.approx(100.0)  # latest is the window's maximum
    assert C.z_3y(long) == pytest.approx((199 - np.mean(range(44, 200))) / np.std(range(44, 200), ddof=1))


def test_percentile_counts_ties_at_or_below_the_latest():
    values = [1.0] * 155 + [1.0]
    assert C.percentile_3y(_weekly(values)) == pytest.approx(100.0)
    values = [2.0] * 155 + [1.0]
    assert C.percentile_3y(_weekly(values)) == pytest.approx(100 / 156)


def test_z_is_none_for_a_flat_window():
    assert C.z_3y(_weekly([5.0] * 200)) is None


def test_change_1w_needs_consecutive_weekly_reports():
    net = _weekly([10.0, 15.0])
    assert C.change_1w(net) == 5.0
    gap = pd.Series([10.0, 15.0], index=pd.to_datetime(["2026-09-22", "2026-10-13"]))
    assert C.change_1w(gap) is None
    assert C.change_1w(_weekly([10.0])) is None


def test_net_percent_of_open_interest_is_missing_without_open_interest():
    pct = C.net_pct_oi(pd.Series([50.0, 50.0]), pd.Series([1000.0, 0.0]))
    assert pct.iloc[0] == pytest.approx(5.0)
    assert np.isnan(pct.iloc[1])


def test_dollar_value_is_contracts_times_multiplier_times_close_in_billions():
    # 10,000 contracts of E-mini S&P 500 at $50 a point and a 5,000 close: $2.5bn.
    assert C.dollar_net_bn(10_000, 50, 5_000) == pytest.approx(2.5)
    assert C.dollar_net_bn(-2_000, 1000, 17.5) == pytest.approx(-0.035)
    assert C.dollar_net_bn(None, 50, 5_000) is None
    assert C.dollar_net_bn(10_000, 50, None) is None


def test_price_is_the_last_close_on_or_before_the_report_date():
    close = pd.Series([100.0, 110.0, 120.0], index=pd.to_datetime(["2026-10-09", "2026-10-12", "2026-10-16"]))
    assert C.price_on(close, pd.Timestamp("2026-10-13")) == (pd.Timestamp("2026-10-12"), 110.0)
    assert C.price_on(close, pd.Timestamp("2026-10-01")) is None


# --- trend check: levels and four-week changes, matched on the report date ---------------------

def test_trend_check_matches_the_model_on_or_before_each_report():
    # A daily model path; the report series is a linear transform of it on the report Tuesdays,
    # so both correlations must be exactly one. Only the matching day or the day before is used.
    daily = pd.bdate_range(end="2026-10-13", periods=900)
    position = pd.Series(np.cumsum(np.sin(np.arange(900))), index=daily)
    lev = 2 * position.reindex(pd.date_range(end="2026-10-13", periods=156, freq="7D")).ffill() + 3
    check = C.trend_check(lev, position)
    assert check["n"] == 156
    assert check["corr_levels"] == pytest.approx(1.0, abs=1e-9)
    assert check["corr_changes_4w"] == pytest.approx(1.0, abs=1e-9)


def test_trend_check_drops_readings_older_than_a_week():
    lev = _weekly(np.arange(80, dtype=float))
    stale = pd.Series(np.arange(60, dtype=float), index=pd.date_range(end="2025-01-07", periods=60, freq="7D"))
    check = C.trend_check(lev, stale)
    assert check["n"] == 0 and check["corr_levels"] is None


def test_trend_check_needs_a_year_of_pairs():
    lev = _weekly(np.arange(40, dtype=float))
    daily = pd.bdate_range(end="2026-10-13", periods=200)
    check = C.trend_check(lev, pd.Series(np.arange(200, dtype=float), index=daily))
    assert check["n"] < C.MIN_PAIRS and check["corr_levels"] is None and check["corr_changes_4w"] is None


# --- panel: one payload per session, only reports known by then, nulls for missing closes -----

def _report_frame(end="2026-10-13", weeks=200):
    rows = []
    dates = pd.date_range(end=end, periods=weeks, freq="7D")
    rng = np.random.default_rng(7)
    for code in [s["code"] for s in C.CONTRACTS]:
        for i, day in enumerate(dates):
            lev_long = 100_000 + 1000 * i + rng.integers(0, 500)
            rows.append({
                "date": day, "code": code, "open_interest": 400_000.0 + 100 * i,
                "dealer_long": 90_000.0, "dealer_short": 80_000.0 + i,
                "asset_mgr_long": 300_000.0, "asset_mgr_short": 100_000.0 + 50 * i,
                "lev_money_long": float(lev_long), "lev_money_short": 150_000.0 - 200 * i,
                "other_long": 20_000.0, "other_short": 25_000.0,
                "nonrept_long": 30_000.0, "nonrept_short": 10_000.0,
                "traders_total": 300.0,
                "traders_dealer_long": 20.0, "traders_dealer_short": np.nan,
                "traders_asset_mgr_long": 60.0, "traders_asset_mgr_short": 40.0,
                "traders_lev_money_long": 40.0, "traders_lev_money_short": 70.0,
                "traders_other_long": 8.0, "traders_other_short": 9.0,
            })
    frame = pd.DataFrame(rows)
    for key in cftc.CATEGORY_FIELDS:
        if key not in frame.columns:
            frame[key] = np.nan
    return frame[cftc.CATEGORY_COLUMNS]


def _index_closes(end="2026-10-23"):
    days = pd.bdate_range(end=end, periods=600)
    return pd.DataFrame({
        "^GSPC": np.linspace(4000, 6000, len(days)),
        "^NDX": np.linspace(12000, 20000, len(days)),
        "^VIX": np.linspace(30, 16, len(days)),
    }, index=days)


def _ctx(as_of="2026-10-23", closes=None):
    return SimpleNamespace(as_of=as_of, log=BuildLog(), index_closes=closes if closes is not None else _index_closes(),
                           etf_closes=pd.DataFrame(), closes=pd.DataFrame())


def _positioning(end="2026-10-23"):
    days = pd.bdate_range(end=end, periods=900)  # enough history for 156 Tuesdays
    position = {"dates": [d.strftime("%Y-%m-%d") for d in days], "values": list(np.linspace(-80, 80, len(days)))}
    return {"trend": [{"key": "SPX", "model": {"history": {"position": position}}}]}


@pytest.fixture
def stub_reports(monkeypatch):
    monkeypatch.setattr(panel.cftc, "fetch_tff_categories", lambda codes, start: _report_frame())
    monkeypatch.setattr(panel.yahoo, "fetch_closes", lambda symbols, period: pd.DataFrame())


def test_payload_is_json_safe_with_contract_fields_and_lag(stub_reports):
    out = panel.build(_ctx(), {"positioning": _positioning()})
    json.dumps(out, allow_nan=False)
    assert out["report_date"] == "2026-10-13" and out["released"] == "2026-10-16"
    assert [c["key"] for c in out["contracts"]] == ["es", "nq", "rty", "vx"]
    es = out["contracts"][0]
    assert es["code"] == "13874A" and es["multiplier"] == 50 and es["approximate"] is False
    assert [c["key"] for c in es["categories"]] == ["dealer", "asset_mgr", "lev_money", "other", "nonrept"]
    lev = next(c for c in es["categories"] if c["key"] == "lev_money")
    assert lev["net"] == lev["long"] - lev["short"]
    assert lev["net_pct_oi"] == pytest.approx(100 * lev["net"] / es["open_interest"], abs=0.01)
    assert lev["traders"] == {"long": 40.0, "short": 70.0}
    assert out["contracts"][3]["approximate"] is True


def test_dollar_value_uses_the_close_on_the_report_date(stub_reports):
    out = panel.build(_ctx(), {"positioning": _positioning()})
    es = out["contracts"][0]
    closes = _index_closes()["^GSPC"]
    expected_close = closes[closes.index <= pd.Timestamp("2026-10-13")].iloc[-1]
    lev = next(c for c in es["categories"] if c["key"] == "lev_money")
    assert es["price"] == {"symbol": "^GSPC", "date": "2026-10-13", "close": pytest.approx(round(expected_close, 2), abs=0.01)}
    assert lev["net_usd_bn"] == pytest.approx(lev["net"] * 50 * expected_close / 1e9, abs=0.01)


def test_reports_not_yet_known_at_the_session_are_excluded(monkeypatch):
    # Reports dated after the session's Tuesday-plus-three cut are not published yet.
    frame = _report_frame(end="2026-10-27")
    monkeypatch.setattr(panel.cftc, "fetch_tff_categories", lambda codes, start: frame)
    monkeypatch.setattr(panel.yahoo, "fetch_closes", lambda symbols, period: pd.DataFrame())
    # 2026-10-27 is known on 2026-10-30, after the session; 2026-10-20 is known on 2026-10-23 and stays.
    out = panel.build(_ctx(as_of="2026-10-23"), {"positioning": _positioning()})
    assert out["report_date"] == "2026-10-20"
    assert out["contracts"][0]["report_date"] == "2026-10-20"


def test_missing_closes_leave_dollars_null_and_say_so(monkeypatch):
    closes = _index_closes().drop(columns=["^NDX", "^VIX"])
    monkeypatch.setattr(panel.cftc, "fetch_tff_categories", lambda codes, start: _report_frame())

    def boom(symbols, period):
        raise RuntimeError("no price feed")

    monkeypatch.setattr(panel.yahoo, "fetch_closes", boom)
    ctx = _ctx(closes=closes)
    out = panel.build(ctx, {"positioning": _positioning()})
    json.dumps(out, allow_nan=False)
    nq = out["contracts"][1]
    assert nq["price"]["close"] is None
    assert all(c["net_usd_bn"] is None for c in nq["categories"])
    assert out["contracts"][0]["categories"][0]["net_usd_bn"] is not None
    assert any(r.source_id == "cftc_prices" and r.status == "partial" for r in ctx.log.sources)


def test_trend_check_is_a_correlation_block_or_says_why_it_is_missing(stub_reports):
    out = panel.build(_ctx(), {"positioning": _positioning()})
    check = out["trend_check"]
    assert [c["key"] for c in check["categories"]] == ["asset_mgr", "lev_money"]
    assert all(c["n"] == C.WINDOW and c["corr_levels"] is not None for c in check["categories"])
    assert check["position_as_of"] == "2026-10-23"
    assert "not a validation" in out["trend_check_note"]

    none = panel.build(_ctx(), {})
    assert none["trend_check"] == {"unavailable": "positioning panel not built this session"}


def test_a_failed_report_fetch_is_an_unavailable_section_with_an_error_record(monkeypatch):
    def fail(codes, start):
        raise ConnectionError("CFTC returned a challenge page")

    monkeypatch.setattr(panel.cftc, "fetch_tff_categories", fail)
    ctx = _ctx()
    out = panel.build(ctx, {})
    assert out["unavailable"].startswith("ConnectionError")
    record = ctx.log.sources[-1]
    assert record.source_id == "cftc_tff_categories" and record.status == "error"
