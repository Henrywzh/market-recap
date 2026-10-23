"""FLOWS section C: Fed Z.1 equity purchases by sector. Synthetic FRED frames, no network."""

from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import z1 as Z
from market_recap.panels import flows_z1 as panel
from market_recap.sources import fred
from market_recap.sources.http import FetchError
from market_recap.util import BuildLog


def _quarters(start="1946-01-01", end="2026-04-01"):
    return pd.date_range(start, end, freq="QS")


def _frame(values, index):
    return pd.DataFrame({"date": index, "value": values, "series_id": "x"})


def _fake_fred(monkeypatch, *, drop=None, html=None, last_quarter=None):
    """Replace fred.fetch_series with synthetic Z.1 lines that sum to the total."""
    index = _quarters(end=last_quarter or "2026-04-01")
    rng = np.random.default_rng(7)
    lines = {key: rng.normal(0, 100_000, len(index)) for key in panel.SERIES if key != "total"}
    lines["total"] = sum(lines[k] for k in lines if k not in ("financial_issues", "foreign_issues"))
    calls = []

    def fetch(series_id, *, use_cache=True):
        calls.append(series_id)
        if html and series_id == html:
            raise FetchError(f"FRED served no CSV for {series_id} (a maintenance page?)")
        key = next(k for k, (sid, _) in panel.SERIES.items() if sid == series_id)
        values = lines[key].copy()
        if drop == key:
            values = values[:-1]
            return _frame(values, index[:-1]), "url"
        return _frame(values, index), "url"

    monkeypatch.setattr(fred, "fetch_series", fetch)
    monkeypatch.setattr(panel.time, "sleep", lambda s: None)
    return calls


def _ctx():
    return SimpleNamespace(as_of="2026-10-23", log=BuildLog())


# --- compute -------------------------------------------------------------

def test_nsa_is_millions_to_billions_and_saar_is_divided_by_four_first():
    values = pd.Series([1_000_000.0, -400_000.0])
    assert list(Z.to_quarter_bn(values, "NSA")) == [1000.0, -400.0]
    assert list(Z.to_quarter_bn(values, "SAAR")) == [250.0, -100.0]
    with pytest.raises(KeyError):
        Z.to_quarter_bn(values, "SA")


def test_groups_sum_to_the_total_with_other_as_the_residual():
    index = pd.date_range("2020-01-01", periods=5, freq="QS")
    lines = pd.DataFrame({"a": [1.0, 2, 3, 4, 5], "b": [1.0, 1, 1, 1, 1], "c": [10.0, 10, 10, 10, 10]}, index=index)
    total = lines["a"] + lines["b"] + lines["c"]
    out = Z.decompose(lines, total, [("ab", ("a", "b"))])
    assert list(out["ab"]) == [2.0, 3, 4, 5, 6]
    assert list(out["other"]) == [10.0] * 5
    assert np.allclose(out["ab"] + out["other"], total)


def test_a_group_with_a_missing_line_is_missing_not_smaller():
    index = pd.date_range("2020-01-01", periods=5, freq="QS")
    lines = pd.DataFrame({"a": [1.0] * 5, "b": [np.nan, 1, 1, 1, 1]}, index=index)
    total = pd.Series([2.0] * 5, index=index)
    out = Z.decompose(lines, total, [("ab", ("a", "b"))])
    assert pd.isna(out["ab"].iloc[0])
    assert pd.isna(out["other"].iloc[0])


def test_quarter_label_and_end_follow_the_observation_date():
    assert Z.quarter_label(pd.Timestamp("2026-04-01")) == "2026Q2"
    assert Z.quarter_label(pd.Timestamp("2025-01-01")) == "2025Q1"
    assert Z.quarter_end(pd.Timestamp("2026-04-01")) == pd.Timestamp("2026-06-30")


def test_percentile_needs_enough_windows_and_counts_at_or_below():
    history = pd.Series(np.arange(1.0, 41.0))
    assert Z.percentile_of(40.0, history) == 100.0
    assert Z.percentile_of(10.0, history) == 25.0
    assert Z.percentile_of(10.0, history.iloc[:5]) is None
    assert Z.percentile_of(None, history) is None
    assert Z.percentile_of(float("nan"), history) is None


def test_trailing_sum_is_missing_until_four_quarters_exist():
    quarterly = pd.Series([1.0, 2, 3, 4, 5])
    sums = Z.trailing_sum(quarterly)
    assert sums.iloc[:3].isna().all()
    assert sums.iloc[3] == 10.0 and sums.iloc[4] == 14.0


# --- panel ---------------------------------------------------------------

def test_a_full_build_is_json_clean_and_logs_its_source(monkeypatch):
    _fake_fred(monkeypatch)
    ctx = _ctx()
    payload = panel.build(ctx, {})
    assert "unavailable" not in payload
    json.dumps(payload, allow_nan=False)
    assert payload["latest_quarter"] == "2026Q2"
    assert payload["latest_quarter_end"] == "2026-06-30"
    assert payload["next_release"] == "2026-12-10"
    assert payload["basis"] == "NSA" and payload["units"] == "$bn per quarter"
    assert len(payload["history"]["dates"]) == Z.CHART_QUARTERS
    for values in payload["history"]["groups"].values():
        assert len(values) == Z.CHART_QUARTERS
    keys = [g["key"] for g in payload["groups"]]
    assert keys == ["households", "mutual_funds", "etfs", "pensions", "insurers", "rest_of_world", "broker_dealers", "other"]
    assert [r["key"] for r in payload["latest"]][-1] == "total"
    assert [r["key"] for r in payload["issuers"]] == list(panel.ISSUER_KEYS)
    assert payload["revisions"].startswith("Each release revises")
    assert ctx.log.sources[-1].status == "ok"
    assert ctx.log.sources[-1].observed_date == "2026-06-30"


def test_groups_in_the_payload_sum_to_the_total_each_quarter(monkeypatch):
    _fake_fred(monkeypatch)
    payload = panel.build(_ctx(), {})
    dates = payload["history"]["dates"]
    total = np.array(payload["history"]["total"], dtype=float)
    parts = sum(np.array(v, dtype=float) for v in payload["history"]["groups"].values())
    assert dates[-1] == "2026-04-01"
    assert np.allclose(parts, total, atol=0.1)  # each value is rounded to 2 dp


def test_the_trailing_sum_is_the_last_four_quarters_of_the_chart_line(monkeypatch):
    _fake_fred(monkeypatch)
    payload = panel.build(_ctx(), {})
    total = [row for row in payload["latest"] if row["key"] == "total"][0]
    assert total["q_bn"] == pytest.approx(payload["history"]["total"][-1])
    assert total["trailing_4q_bn"] == pytest.approx(sum(payload["history"]["total"][-4:]), abs=0.2)


def test_a_fetch_failure_is_a_gap_with_an_error_record(monkeypatch):
    _fake_fred(monkeypatch, html="BOGZ1FU563064100Q")
    ctx = _ctx()
    payload = panel.build(ctx, {})
    assert set(payload) == {"unavailable"}
    assert "maintenance page" in payload["unavailable"]
    assert ctx.log.sources[-1].status == "error"


def test_a_line_one_quarter_behind_is_unavailable_not_misaligned(monkeypatch):
    _fake_fred(monkeypatch, drop="mutual_funds")
    ctx = _ctx()
    payload = panel.build(ctx, {})
    assert "2026Q2" in payload["unavailable"] and "mutual_funds" in payload["unavailable"]
    assert ctx.log.sources[-1].status == "error"


def test_the_fred_requests_are_paced_when_not_cached(monkeypatch):
    _fake_fred(monkeypatch)
    slept = []
    monkeypatch.setattr(panel.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(panel.cache, "is_fresh", lambda path, kind: False)
    panel.build(_ctx(), {})
    assert len(slept) == len(panel.SERIES) - 1
    assert all(s >= 2.0 for s in slept)


def test_the_method_and_the_residual_are_stated_in_the_payload(monkeypatch):
    _fake_fred(monkeypatch)
    payload = panel.build(_ctx(), {})
    other = next(g for g in payload["groups"] if g["key"] == "other")
    assert "everything else" in other["members"]
    assert any("Households" in note or "households" in note for note in payload["not_covered"])
