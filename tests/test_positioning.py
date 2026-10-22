"""POSITIONING: the trend-follower proxy and the FINRA helpers."""

from datetime import date
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import positioning as P
from market_recap.panels import positioning as panel
from market_recap.sources import finra


def _close(values):
    return pd.Series(values, index=pd.bdate_range("2024-01-01", periods=len(values)), dtype=float)


def test_score_is_the_mean_vote_of_the_lookbacks():
    rising = _close(range(100, 400))
    assert P.trend_score(rising).iloc[-1] == 1.0
    falling = _close(range(400, 100, -1))
    assert P.trend_score(falling).iloc[-1] == -1.0
    assert P.label(1.0) == "LONG" and P.label(-0.5) == "SHORT" and P.label(0.0) == "MIXED"


def test_flip_level_is_the_close_tomorrow_is_compared_with():
    close = _close(range(100, 400))
    flips = {f["lookback"]: f for f in P.flip_levels(close)}
    # Tomorrow's 21-session return compares with the close 20 sessions before today.
    assert flips["1M"]["flip_level"] == float(close.iloc[-21])
    assert flips["1M"]["signal"] == 1
    assert round(flips["1M"]["return_pct"], 6) == round((close.iloc[-1] / close.iloc[-22] - 1) * 100, 6)
    assert flips["1M"]["distance_pct"] < 0


def test_moving_average_levels():
    close = _close([100.0] * 199 + [120.0])
    levels = {m["window"]: m for m in P.ma_levels(close)}
    assert levels[200]["above"] is True
    assert round(levels[200]["level"], 6) == 100.1


def test_finra_symbols_run_the_share_class_on():
    assert finra.finra_symbol("BRK-B") == "BRKB"
    assert finra.finra_symbol("BF.B") == "BFB"
    assert finra.finra_symbol("NVDA") == "NVDA"


def test_candidate_settlement_dates_are_mid_month_and_month_end_newest_first():
    assert finra.candidate_dates(date(2026, 9, 29), 4) == [
        date(2026, 9, 15), date(2026, 8, 31), date(2026, 8, 15), date(2026, 7, 31)]
    assert finra.candidate_dates(date(2026, 1, 10), 2) == [date(2025, 12, 31), date(2025, 12, 15)]


def test_an_unpublished_round_is_not_cached(tmp_path, monkeypatch):
    from market_recap import cache

    monkeypatch.setattr(cache, "path_for", lambda ns, name, suffix: tmp_path / f"{ns}-{name}{suffix}")
    answers = {"2026-09-30": None, "2026-09-29": None}
    monkeypatch.setattr(finra, "_query", lambda day, symbols: answers.get(day.isoformat()))
    assert finra.fetch_round(date(2026, 9, 30), ["NVDA"], max_back=1).empty
    assert not list(tmp_path.iterdir())
    answers["2026-09-30"] = [{"symbolCode": "NVDA", "settlementDate": "2026-09-30", "currentShortPositionQuantity": 5,
                              "previousShortPositionQuantity": 4, "averageDailyVolumeQuantity": 10,
                              "daysToCoverQuantity": 0.5, "changePercent": 25.0, "revisionFlag": None}]
    frame = finra.fetch_round(date(2026, 9, 30), ["NVDA"], max_back=1)
    assert frame["shares_short"].tolist() == [5] and frame["settlement_date"].iloc[0] == pd.Timestamp("2026-09-30")


# --- buyback blackout and the insider scan -----------------------------------

def _ctx(members, as_of="2026-09-28", closes=None):
    frame = pd.DataFrame(members)
    spec = SimpleNamespace(key="SPX", symbol="^GSPC", label="S&P 500", primary=True)
    sessions = pd.bdate_range("2026-06-01", as_of)
    return SimpleNamespace(
        as_of=as_of, primary=spec, indices=[spec], priced=lambda key: frame,
        index_closes=pd.DataFrame({"^GSPC": range(len(sessions))}, index=sessions), log=None,
    )


def test_blackout_counts_weight_inside_the_window_and_projects_missing_dates():
    ctx = _ctx([{"yahoo_symbol": "AAA", "weight": 60.0, "name": "A"},
                {"yahoo_symbol": "BBB", "weight": 40.0, "name": "B"}])
    catalysts = {"events": [{"event_type": "earnings", "symbol": "AAA", "date": "2026-10-20"}]}
    # BBB reported every ~91 days; its next report is projected, not calendared.
    evidence = {"names": {"BBB": {"reactions": [{"date": "2026-01-15"}, {"date": "2026-04-16"}, {"date": "2026-07-16"}]}}}
    out = panel._blackout(ctx, {"blackout_history_days": 30, "blackout_days_ahead": 60}, catalysts, evidence)
    assert out["scheduled"] == 1 and out["projected"] == 1 and out["missing"] == 0
    # On 2026-09-28 AAA (report 10-20) is inside its 30-day window; BBB's
    # projected 10-15 report puts it inside too.
    assert out["now_pct"] == 100.0
    day = out["dates"].index("2026-10-25")                       # both windows closed by then
    assert out["share_pct"][day] == 0.0
    assert out["dates"][0] == "2026-08-29" and out["dates"][-1] == "2026-11-27"


def test_blackout_without_any_index_weight_keeps_values_missing():
    ctx = _ctx([{"yahoo_symbol": "AAA", "weight": 0.0, "name": "A"}])
    out = panel._blackout(ctx, {"blackout_history_days": 15, "blackout_days_ahead": 7,
                              "blackout_change_calendar_days": [1, 7]}, None, None)
    assert out["now_pct"] is None
    assert out["peak_pct"] is None and out["peak_date"] is None
    assert out["weight_covered_pct"] is None
    assert out["momentum"]["windows"][0]["now_delta_pp"] is None


def test_insider_scan_reads_new_filings_within_budget_and_reports_coverage(tmp_path, monkeypatch):
    from market_recap import cache
    from market_recap.sources import sec

    monkeypatch.setattr(cache, "path_for", lambda ns, name, suffix: tmp_path / f"{ns.replace('/', '_')}-{name}{suffix}")
    monkeypatch.setattr(sec, "fetch_ticker_cik_map", lambda: {"AAA": 1})
    index = {"2026-09-28": [{"form": "4", "name": "AAA", "cik": 1, "filed": "2026-09-28", "path": "edgar/data/1/0000000001-26-000002.txt"},
                            {"form": "4", "name": "OTHER", "cik": 9, "filed": "2026-09-28", "path": "edgar/data/9/x.txt"}],
             "2026-09-25": [{"form": "4", "name": "AAA", "cik": 1, "filed": "2026-09-25", "path": "edgar/data/1/0000000001-26-000001.txt"}]}
    monkeypatch.setattr(sec, "daily_form_index", lambda day, **k: index.get(day.isoformat()))
    fetched = []

    def xml(path):
        fetched.append(path)
        return "doc"

    monkeypatch.setattr(sec, "ownership_xml", xml)
    owner = iter(["1", "2"])
    monkeypatch.setattr(panel.V, "strict_form4_buys", lambda xml, issuer_cik, filed, filing_url: [
        {"date": filed, "filed": filed, "owner_id": next(owner), "owner": "X", "value": 200_000.0, "filing_url": filing_url}])
    ctx = _ctx([{"yahoo_symbol": "AAA", "weight": 1.0, "name": "A", "sector": "Tech"}])
    settings = {"insider_window_days": 5, "insider_max_new_filings": 1}
    first = panel._insiders(ctx, settings)
    assert len(fetched) == 1 and not first["coverage"]["complete"]      # budget: one new filing
    assert first["coverage"]["read_through"] == "2026-09-28"
    second = panel._insiders(ctx, settings)
    assert len(fetched) == 2 and second["coverage"]["complete"]          # the parse of the first was kept
    assert second["clusters"][0]["ticker"] == "AAA" and second["clusters"][0]["count"] == 2
    assert "OTHER" not in str(second)                                    # not an index member


# --- vol-scaled model position, scenarios and the trend check --------------------

def _noisy_uptrend(sessions=400, daily_sd=0.01, drift=0.0008, seed=3):
    rng = np.random.default_rng(seed)
    return _close(100 * np.exp(np.cumsum(drift + daily_sd * rng.standard_normal(sessions))))


def test_model_position_is_bounded_and_signed_by_the_trend():
    up = P.model_position(_noisy_uptrend())
    assert up.iloc[-1] > 0 and up.abs().max() <= 100
    down = P.model_position(_noisy_uptrend(drift=-0.0008))
    assert down.iloc[-1] < 0 and down.abs().max() <= 100
    exposure = P.vol_control_exposure(_noisy_uptrend())
    assert exposure.min() >= 0 and exposure.max() <= 100


def test_flat_prices_for_five_sessions_lift_position_and_vol_control_when_volatility_falls():
    # A rising, noisy series: the trend is long and the volatility is below the cap.
    close = _noisy_uptrend()
    rows = {(r["sessions"], r["move_sd"]): r for r in P.scenario_flows(close)}
    flat = rows[(5, 0)]
    assert flat["move_pct"] == 0 and flat["close"] == float(close.iloc[-1])
    # Five unchanged closes add zero returns, which pull the trailing volatility down.
    assert flat["position_change"] > 0 and flat["vc_change"] > 0


def test_scenario_flows_gives_ten_rows_and_a_zero_move_is_no_price_change():
    rows = P.scenario_flows(_noisy_uptrend())
    assert len(rows) == 10
    assert {r["sessions"] for r in rows} == {1, 5}
    assert {r["move_sd"] for r in rows} == {-2, -1, 0, 1, 2}
    assert all(r["move_pct"] == 0 for r in rows if r["move_sd"] == 0)
    two_up = next(r for r in rows if r["sessions"] == 5 and r["move_sd"] == 2)
    assert two_up["move_pct"] > 0 and two_up["close"] > float(_noisy_uptrend().iloc[-1])


def test_room_and_dollar_flows_follow_the_assumed_notional():
    assert P.room(62.0) == {"to_max_long": 38.0, "to_max_short": 162.0}
    assert P.room(None) == {"to_max_long": None, "to_max_short": None}
    low, high = P.flow_range_bn(6.0, "^GSPC")
    assert round(low, 2) == 4.8 and round(high, 2) == 9.6
    assert P.flow_range_bn(-40.0, "^GSPC") == (-32.0, -64.0)
    assert P.flow_range_bn(6.0, "UNKNOWN") == (None, None)


def test_implied_equity_beta_recovers_a_known_loading_on_synthetic_returns():
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2020-01-01", periods=300)
    factors = pd.DataFrame({"SPY": 0.01 * rng.standard_normal(300), "IEF": 0.004 * rng.standard_normal(300)},
                           index=index)
    etf = 0.5 * factors["SPY"] - 0.2 * factors["IEF"] + 0.0005 * rng.standard_normal(300)
    beta = P.implied_equity_beta(etf, factors, window=63)
    assert len(beta) == 300 - 62
    assert abs(beta.iloc[-1] - 0.5) < 0.02


def test_implied_equity_beta_leaves_a_window_missing_when_too_few_rows_are_complete():
    index = pd.bdate_range("2020-01-01", periods=80)
    factors = pd.DataFrame({"SPY": np.linspace(-0.01, 0.01, 80)}, index=index)
    etf = factors["SPY"] * 0.5
    etf.iloc[:20] = np.nan                       # the first window has 43 complete rows, under 90% of 63
    beta = P.implied_equity_beta(etf, factors, window=63)
    assert beta.index[0] == index[76]            # the first window with 57 complete rows


def test_change_correlation_needs_enough_monthly_changes():
    index = pd.bdate_range("2020-01-01", periods=21 * 30)
    a = pd.Series(np.sin(np.arange(len(index)) / 10.0), index=index)
    assert P.change_correlation(a, a) == pytest.approx(1.0)
    assert P.change_correlation(a.iloc[:200], a.iloc[:200]) is None


def _trend_ctx(close, *, log=None):
    spec = SimpleNamespace(key="SPX", symbol="^GSPC", label="S&P 500", primary=True)
    return spec, SimpleNamespace(index_closes=pd.DataFrame({"^GSPC": close}), as_of="2026-10-16",
                                 primary=spec, log=log or SimpleNamespace(add=lambda record: None))


def test_trend_payload_with_the_model_is_json_clean():
    close = _noisy_uptrend(sessions=600)
    spec, ctx = _trend_ctx(close)
    payload = panel._trend(ctx, spec, {"history_years": 3})
    model = payload["model"]
    assert model["flow_assumption_bn"] == [80, 160]
    assert len(model["scenarios"]) == 10
    assert model["room"]["to_max_long"] == round(100 - model["position"], 1)
    assert set(model["history"]) == {"position", "vol_control"}
    json.dumps(payload, allow_nan=False)


def test_trend_model_has_no_dollar_assumption_for_an_unknown_index():
    close = _noisy_uptrend(sessions=600)
    spec = SimpleNamespace(key="X", symbol="^XYZ", label="Other", primary=False)
    ctx = SimpleNamespace(index_closes=pd.DataFrame({"^XYZ": close}), as_of="2026-10-16", log=None)
    payload = panel._trend(ctx, spec, {"history_years": 3})
    assert payload["model"]["flow_assumption_bn"] is None
    assert all(row["flow_bn_low"] is None for row in payload["model"]["scenarios"])
    json.dumps(payload, allow_nan=False)


def test_trend_check_reads_the_listed_etf_beta_and_logs_its_prices(monkeypatch):
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2021-01-04", periods=400)
    spy = 0.01 * rng.standard_normal(400)
    prices = pd.DataFrame({
        "SPY": 100 * np.exp(np.cumsum(spy)),
        "IEF": 100 * np.exp(np.cumsum(0.002 * rng.standard_normal(400))),
        "UUP": 100 * np.exp(np.cumsum(0.003 * rng.standard_normal(400))),
        "GLD": 100 * np.exp(np.cumsum(0.008 * rng.standard_normal(400))),
        "USO": 100 * np.exp(np.cumsum(0.015 * rng.standard_normal(400))),
    }, index=index)
    dbmf = 100 * np.exp(np.cumsum(0.5 * spy + 0.0002 * rng.standard_normal(400)))
    prices["DBMF"] = dbmf
    calls = []

    def fake_fetch(symbols, *, period):
        calls.append((tuple(symbols), period))
        return prices[list(symbols)]

    monkeypatch.setattr(panel.yahoo, "fetch_closes", fake_fetch)
    close = pd.Series(100 * np.exp(np.cumsum(0.001 + 0.01 * rng.standard_normal(400))), index=index)
    logged = []
    ctx = SimpleNamespace(index_closes=pd.DataFrame({"^GSPC": close}), primary=SimpleNamespace(symbol="^GSPC", label="S&P 500"),
                          log=SimpleNamespace(add=logged.append))
    out = panel._trend_check(ctx, {"history_years": 2})
    assert calls == [(("DBMF", "SPY", "IEF", "UUP", "GLD", "USO"), "2y")]
    assert abs(out["beta_now"] - 0.5) < 0.05
    assert out["etf"] == "DBMF" and out["window"] == 63
    assert len(out["beta"]) == len(out["dates"]) == len(out["position"])
    assert logged[0].source_id == "trend_check_prices" and logged[0].status == "ok"
    json.dumps(out, allow_nan=False)


def test_trend_check_is_unavailable_with_a_reason_when_prices_fail(monkeypatch):
    def failing(symbols, *, period):
        raise RuntimeError("Yahoo returned 502")

    monkeypatch.setattr(panel.yahoo, "fetch_closes", failing)
    logged = []
    ctx = SimpleNamespace(index_closes=pd.DataFrame(), primary=SimpleNamespace(symbol="^GSPC", label="S&P 500"),
                          log=SimpleNamespace(add=logged.append))
    out = panel._trend_check(ctx, {})
    assert out == {"unavailable": "Yahoo returned 502"}
    assert logged[0].status == "error"


def test_model_position_moves_smoothly_through_a_flip_level():
    rng = np.random.default_rng(7)
    close = _close(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 340))))
    flips = {f["lookback"]: f["flip_level"] for f in P.flip_levels(close)}
    level = flips["1M"]
    below = P.model_position(pd.concat([close, pd.Series([level * 0.999], index=[close.index[-1] + pd.offsets.BDay()])]))
    above = P.model_position(pd.concat([close, pd.Series([level * 1.001], index=[close.index[-1] + pd.offsets.BDay()])]))
    # A sign vote would jump 25 x scale points here; the continuous signal barely moves.
    assert abs(float(above.iloc[-1]) - float(below.iloc[-1])) < 3


def test_level_correlation_needs_a_year_of_overlap():
    a = _close(np.linspace(1, 2, 300))
    assert P.level_correlation(a, a * 3) == pytest.approx(1.0)
    assert P.level_correlation(a.iloc[:100], a.iloc[:100]) is None
