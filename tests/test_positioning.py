"""POSITIONING: the trend-follower proxy and the FINRA helpers."""

from datetime import date
from types import SimpleNamespace

import pandas as pd

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
