"""Yahoo's forward P/E history: parsing, the fiscal-year horizon rule, and what the panel reports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import cache, validate
from market_recap.compute import valuation as V
from market_recap.panels import valuation as panel
from market_recap.sources import forward_pe_history as F


def _answer(type_name, points):
    """A fundamentals-timeseries answer: ``points`` are (asOfDate, value) pairs."""
    return {"timeseries": {"result": [{"meta": {"type": [type_name]}, type_name: [
        {"dataId": 14020, "asOfDate": d, "periodType": "1M", "reportedValue": {"raw": v, "fmt": str(v)}} for d, v in points]}]}}


def _pts(*pairs):
    return [{"date": d, "pe": v} for d, v in pairs]


# --- parsing -----------------------------------------------------------------------------------------------------
def test_parse_series_returns_points_oldest_first():
    payload = _answer("monthlyForwardPeRatio", [("2026-06-30", 17.18), ("2026-05-31", 17.42)])
    assert F.parse_series(payload, "monthlyForwardPeRatio") == _pts(("2026-05-31", 17.42), ("2026-06-30", 17.18))


def test_parse_series_drops_what_is_not_a_multiple():
    """Yahoo publishes nothing on a forecast loss; a zero, negative or missing value is a unit error, not a P/E."""
    payload = {"timeseries": {"result": [{"monthlyForwardPeRatio": [
        {"asOfDate": "2026-01-31", "reportedValue": {"raw": 0.0}},
        {"asOfDate": "2026-02-28", "reportedValue": {"raw": -4.0}},
        {"asOfDate": "2026-03-31", "reportedValue": {"raw": float("nan")}},
        {"asOfDate": "2026-04-30"},
        None,
        {"asOfDate": "2026-05-31", "reportedValue": {"raw": 12.5}},
    ]}]}}
    assert F.parse_series(payload, "monthlyForwardPeRatio") == _pts(("2026-05-31", 12.5))


def test_parse_series_tells_no_history_from_not_a_timeseries():
    assert F.parse_series({"timeseries": {"result": None}}, "annualForwardPeRatio") == []
    assert F.parse_series({"timeseries": {"result": [{"meta": {}}]}}, "annualForwardPeRatio") == []
    assert F.parse_series({"finance": {"error": "Unauthorized"}}, "annualForwardPeRatio") is None


# --- fetching ----------------------------------------------------------------------------------------------------
@pytest.fixture
def served(monkeypatch, tmp_path):
    """Replace Yahoo with a table of answers; return the list of (symbol, type) requests made."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(F, "WORKERS", 1)
    requests = []

    def request(symbol, type_name):
        requests.append((symbol, type_name))
        what = answers[symbol]
        if isinstance(what, Exception):
            raise what
        if isinstance(what, dict) and type_name in what and isinstance(what[type_name], Exception):
            raise what[type_name]
        points = (what or {}).get(type_name, [])
        return json.dumps(_answer(type_name, points))

    answers = {}
    monkeypatch.setattr(F, "_request", request)
    return answers, requests


def test_each_series_is_its_own_request(served):
    """Several types in one call come back truncated to four monthly points (measured on 512 companies)."""
    answers, requests = served
    answers["GS"] = {"monthlyForwardPeRatio": [("2026-06-30", 17.18)], "annualForwardPeRatio": [("2025-12-31", 15.85)]}
    found, failed = F.fetch_series(["GS"], use_cache=False)
    assert sorted(requests) == [("GS", "annualForwardPeRatio"), ("GS", "monthlyForwardPeRatio"), ("GS", "quarterlyForwardPeRatio")]
    assert all("," not in type_name for _, type_name in requests)
    assert failed == {}
    assert found["GS"]["monthly"] == _pts(("2026-06-30", 17.18)) and found["GS"]["quarterly"] == []
    assert "unread" not in found["GS"]


def test_a_company_with_no_history_is_named_not_failed(served):
    answers, _ = served
    answers["CRWV"] = {}
    found, failed = F.fetch_series(["CRWV"], use_cache=False)
    assert found == {} and failed == {"CRWV": F.NO_HISTORY}


def test_a_series_that_cannot_be_read_is_named_and_the_rest_is_kept(served):
    answers, _ = served
    answers["JPM"] = {"annualForwardPeRatio": RuntimeError("HTTP 429"), "monthlyForwardPeRatio": [("2026-06-30", 14.88)]}
    found, failed = F.fetch_series(["JPM"], use_cache=False)
    assert failed == {}
    assert found["JPM"]["unread"] == ["annual"] and found["JPM"]["annual"] == []
    assert found["JPM"]["monthly"][0]["pe"] == 14.88


def test_a_company_with_nothing_readable_fails_with_the_reason(served):
    answers, _ = served
    answers["X"] = RuntimeError("HTTP 429")
    found, failed = F.fetch_series(["X"], use_cache=False)
    assert found == {} and "monthly: HTTP 429" in failed["X"] and failed["X"] != F.NO_HISTORY


def test_yahoo_refusing_in_a_row_stops_the_sweep(served, monkeypatch):
    answers, requests = served
    monkeypatch.setattr(F, "GIVE_UP_AFTER", 2)
    for symbol in "ABCD":
        answers[symbol] = RuntimeError("HTTP 429")
    _, failed = F.fetch_series(list("ABCD"), use_cache=False)
    assert failed["C"].startswith("not asked") and failed["D"].startswith("not asked")
    assert {symbol for symbol, _ in requests} == {"A", "B"}


# --- the fiscal-year horizon rule --------------------------------------------------------------------------------
@pytest.mark.parametrize("date,year_end,horizon", [
    ("2026-01-31", 12, 11), ("2026-08-31", 12, 4), ("2025-09-30", 12, 15), ("2025-12-31", 12, 12),   # Goldman: December year
    ("2026-02-28", 6, 4), ("2026-03-31", 6, 15), ("2026-06-30", 6, 12),                              # Microsoft: June year
    ("2025-10-31", 1, 15), ("2026-01-31", 1, 12), ("2026-05-31", 1, 8),                              # Nvidia, Walmart: January year
])
def test_horizon_runs_four_to_fifteen_months_and_resets_at_the_roll(date, year_end, horizon):
    assert V.forward_horizon_months(date, year_end) == horizon


def test_the_roll_month_is_three_months_before_the_year_ends():
    rolled = [m for m in range(1, 13) if V.is_roll_month(f"2026-{m:02d}-28", 12)]
    assert rolled == [9]
    assert [m for m in range(1, 13) if V.is_roll_month(f"2026-{m:02d}-28", 6)] == [3]


def test_the_implied_eps_steps_up_at_the_roll_month_in_yahoos_own_goldman_series():
    """The rule was read off this data: close / P/E (the EPS behind each point) jumps at September, not around it.
    Goldman Sachs, Yahoo's monthly forward P/E and the month-end close (2026-10-09 pull)."""
    series = [("2025-06-30", 15.9744, 707.75), ("2025-07-31", 16.58, 723.59), ("2025-08-31", 17.09, 745.25),
              ("2025-09-30", 15.2207, 796.35), ("2025-10-31", 14.24, 789.37), ("2025-11-30", 14.93, 826.04),
              ("2025-12-31", 15.85, 879.00), ("2026-01-31", 16.23, 935.41), ("2026-02-28", 14.93, 859.57)]
    eps = [(d, close / pe) for d, pe, close in series]
    changes = {d: eps[i][1] / eps[i - 1][1] - 1 for i, (d, _) in enumerate(eps) if i}
    assert changes["2025-09-30"] > 0.15 and V.is_roll_month("2025-09-30", 12)
    assert all(abs(change) < 0.06 for d, change in changes.items() if not V.is_roll_month(d, 12))


def test_fiscal_year_end_month_is_the_commonest_month_of_the_annual_points():
    assert V.fiscal_year_end_month(_pts(("2022-12-31", 9.1), ("2023-12-31", 11.1), ("2024-12-31", 13.9))) == 12
    assert V.fiscal_year_end_month(_pts(("2023-01-31", 45.5), ("2024-01-31", 30.4), ("2025-01-31", 28.1))) == 1
    # A 52-week year that crossed a month boundary once still has one commonest month.
    assert V.fiscal_year_end_month(_pts(("2022-01-29", 1), ("2023-01-28", 1), ("2024-02-03", 1), ("2025-02-01", 1), ("2026-01-31", 1))) == 1
    assert V.fiscal_year_end_month([]) is None


# --- merging and gaps --------------------------------------------------------------------------------------------
def test_quarterly_adds_the_fiscal_quarter_ends_monthly_lacks_and_never_overrides_it():
    monthly = _pts(("2026-05-31", 20.0), ("2026-06-30", 21.0), ("2026-08-31", 22.0))
    quarterly = _pts(("2026-06-30", 21.0), ("2026-07-31", 21.5))
    merged = V.merge_points(monthly, quarterly)
    assert [(p["date"], p["series"]) for p in merged] == [("2026-05-31", "monthly"), ("2026-06-30", "monthly"),
                                                           ("2026-07-31", "quarterly"), ("2026-08-31", "monthly")]


def test_missing_months_names_the_calendar_months_no_point_covers():
    assert V.missing_months(["2026-05-31", "2026-06-30", "2026-08-31"]) == ["2026-07"]
    assert V.missing_months(["2025-12-31", "2026-02-28"]) == ["2026-01"]
    assert V.missing_months(["2026-06-30"]) == []


# --- one company's history ---------------------------------------------------------------------------------------
def _found(monthly=(), quarterly=(), annual=(), unread=None):
    out = {"monthly": _pts(*monthly), "quarterly": _pts(*quarterly), "annual": _pts(*annual)}
    return out | ({"unread": unread} if unread else {})


def test_an_extreme_multiple_is_kept_as_published_not_removed():
    """Boeing's 3,333x and a growth company's 120x look alike in one number; the true range is kept."""
    out = V.fiscal_forward(_found(monthly=[("2026-06-30", 833.0), ("2026-08-31", 3333.0), ("2026-05-31", 14.0)],
                                   annual=[("2025-12-31", 150.0)]))
    assert [p["pe"] for p in out["points"]] == [14.0, 833.0, 3333.0] and out["annual"][0]["pe"] == 150.0
    assert all("withheld" not in p for p in out["points"])


def test_each_point_carries_its_horizon_and_the_roll_month_is_flagged():
    out = V.fiscal_forward(_found(monthly=[("2025-08-31", 17.09), ("2025-09-30", 15.22), ("2025-12-31", 15.85)],
                                   annual=[("2024-12-31", 13.89), ("2025-12-31", 15.85)]))
    assert out["year_end_month"] == 12
    assert [(p["horizon"], p["rolled"]) for p in out["points"]] == [(4, False), (15, True), (12, False)]


def test_year_ago_compares_the_same_month_so_the_horizon_is_the_same():
    out = V.fiscal_forward(_found(monthly=[("2025-06-30", 15.97), ("2025-08-31", 17.09), ("2026-06-30", 17.18), ("2026-08-31", 15.87)],
                                   annual=[("2025-12-31", 15.85)]))
    assert out["latest"]["date"] == "2026-08-31"
    assert out["year_ago"]["date"] == "2025-08-31"
    assert out["year_ago"]["change_pct"] == pytest.approx((15.87 / 17.09 - 1) * 100)


def test_year_ago_is_blank_when_the_month_a_year_back_is_missing():
    assert V.fiscal_forward(_found(monthly=[("2025-07-31", 15.0), ("2026-08-31", 16.0)], annual=[("2025-12-31", 15.0)]))["year_ago"] is None


def test_no_points_at_all_is_none_and_unread_series_are_passed_on():
    assert V.fiscal_forward(None) is None and V.fiscal_forward(_found()) is None
    out = V.fiscal_forward(_found(monthly=[("2026-06-30", 14.0)], unread=["annual"]))
    assert out["unread"] == ["annual"] and out["year_end_month"] is None
    assert out["points"][0]["horizon"] is None and out["points"][0]["rolled"] is False   # no year end, no horizon: not guessed


# --- the panel's fields and report -------------------------------------------------------------------------------
def test_row_fields_are_blank_without_a_history_and_come_from_the_latest_point_with_one():
    assert panel._fiscal_fields(None) == {"pe_forward_fy": None, "pe_forward_fy_date": None,
                                          "pe_forward_fy_horizon": None, "pe_forward_fy_yoy": None}
    out = V.fiscal_forward(_found(monthly=[("2025-08-31", 17.09), ("2026-08-31", 15.87)], annual=[("2025-12-31", 15.85)]))
    fields = panel._fiscal_fields(out)
    assert fields["pe_forward_fy"] == 15.87 and fields["pe_forward_fy_date"] == "2026-08-31"
    assert fields["pe_forward_fy_horizon"] == 4 and fields["pe_forward_fy_yoy"] == pytest.approx(-7.1)


def test_report_separates_no_history_from_failures_and_counts_full_years_and_gaps():
    full = V.fiscal_forward(_found(monthly=[(f"2025-{m:02d}-28", 10.0 + m) for m in range(1, 13)], annual=[("2024-12-31", 12.0)]))
    short = V.fiscal_forward(_found(monthly=[("2026-06-30", 14.0), ("2026-08-31", 400.0)], annual=[("2025-12-31", 1.0)], unread=["quarterly"]))
    report = panel._fiscal_report(5, {"A": full, "B": short}, {"NEW": F.NO_HISTORY, "BAD": "monthly: HTTP 429"})
    assert report["companies"] == 2 and report["full_monthly"] == 1 and report["full_monthly_points"] == panel.FULL_MONTHLY_POINTS
    assert report["none"] == ["NEW"] and report["failed"] == {"BAD": "monthly: HTTP 429"}
    assert report["unread"] == {"B": ["quarterly"]} and report["extreme"] == ["B"]
    assert report["missing_months"] == {"2026-07": 1}
    assert report["roll_months"] == V.FY_ROLL_MONTHS and report["extreme_above"] == V.EXTREME_FORWARD_PE


# --- validation --------------------------------------------------------------------------------------------------
def _report(**kw):
    return {"universe": 100, "companies": 90, "full_monthly": 85, "full_monthly_points": 12, "failed": {}, "unread": {}} | kw


def test_a_healthy_history_raises_nothing_and_an_absent_one_is_not_this_checks_business():
    assert validate._check_fiscal_forward(_report()) == [] and validate._check_fiscal_forward(None) == []


def test_truncated_answers_and_unread_names_are_warned():
    truncated = validate._check_fiscal_forward(_report(full_monthly=20))
    assert len(truncated) == 1 and "truncated" in truncated[0].detail
    many = validate._check_fiscal_forward(_report(failed={str(i): "x" for i in range(6)}))
    assert len(many) == 1 and "6 of 100" in many[0].detail
    assert validate._check_fiscal_forward(_report(companies=0))[0].severity == "warning"


# --- the ticker artifact -----------------------------------------------------------------------------------------
def _artifact(monkeypatch, tmp_path, fiscal):
    import types

    import pandas as pd

    from market_recap.sources import sec
    from test_valuation import _annual_bank_facts

    monkeypatch.setattr(panel, "VALUATION_ARTIFACT_DIR", tmp_path)
    # Three annual filings leave 408 sessions with a live EPS (an EPS with no successor expires); the
    # ranking floor is about P/E percentiles, which this test is not about.
    monkeypatch.setattr(V, "MIN_HISTORY_SESSIONS", 100)
    data = types.SimpleNamespace(eps_history=sec.eps_history(_annual_bank_facts()))
    prices = pd.Series(30.0, index=pd.bdate_range("2024-01-02", "2028-12-29"))
    assert panel._history("BNK", data, prices, None, "Financials", None, fiscal) is not None
    return json.loads((tmp_path / "BNK.json").read_text())


def test_the_ticker_artifact_carries_the_yahoo_series_beside_the_recorded_ntm_one(monkeypatch, tmp_path):
    fiscal = V.fiscal_forward(_found(monthly=[("2025-08-31", 17.09), ("2025-09-30", 15.22), ("2026-08-31", 15.87)],
                                      annual=[("2024-12-31", 13.89), ("2025-12-31", 15.85)]))
    artifact = _artifact(monkeypatch, tmp_path, fiscal)
    assert artifact["forward"] is None                                    # the NTM history is a separate field
    carried = artifact["fiscal_forward"]
    assert carried["year_end_month"] == 12 and [p["horizon"] for p in carried["points"]] == [4, 15, 4]
    assert carried["year_ago"]["date"] == "2025-08-31" and carried["annual"][-1]["pe"] == 15.85


def test_an_artifact_without_a_yahoo_history_says_so_with_null(monkeypatch, tmp_path):
    assert _artifact(monkeypatch, tmp_path, None)["fiscal_forward"] is None
