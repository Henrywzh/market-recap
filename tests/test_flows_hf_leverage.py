"""FLOWS · HEDGE FUNDS: OFR Form PF leverage and equity exposure.

No network: the source is exercised through a stubbed transport, and the panel
through a synthetic dataset in tests/fixtures/ofr_formpf_sample.json (shaped
like the OFR dataset, with invented values).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from market_recap.compute import hf_leverage as H
from market_recap.panels import flows_hf_leverage as panel
from market_recap.sources import ofr
from market_recap.sources.http import FetchError
from market_recap.util import BuildLog

FIXTURE = Path(__file__).parent / "fixtures" / "ofr_formpf_sample.json"


def _quarters(values, start="2023-03-31"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="QE"), dtype=float)


def _dataset(series_map):
    """A minimal dataset in the OFR shape for the given {mnemonic: [(date, value), ...]}."""
    return {
        "timeseries": {
            name: {
                "timeseries": {"aggregation": [[d, v] for d, v in rows]},
                "metadata": {
                    "description": {"name": f"name of {name}"},
                    "unit": {"name": "U.S. dollars"},
                    "schedule": {"last_update": "2026-09-16 15:19:27"},
                },
            }
            for name, rows in series_map.items()
        }
    }


@pytest.fixture(autouse=True)
def no_cache_writes(monkeypatch):
    """cache.fetch_bytes writes whatever it fetched, even with use_cache=False.
    In tests that would overwrite the real cached dataset, so it is replaced by a pass-through."""
    monkeypatch.setattr(ofr.cache, "fetch_bytes", lambda namespace, name, fetch, **kwargs: fetch())


@pytest.fixture
def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- compute -----------------------------------------------------------------

def test_points_drops_withheld_quarters_and_sorts():
    data = _dataset({"M": [("2024-06-30", 2.0), ("2024-03-31", None), ("2023-12-31", 1.0)]})
    series = H.points(data, "M")
    assert list(series.index.strftime("%Y-%m-%d")) == ["2023-12-31", "2024-06-30"]
    assert list(series.values) == [1.0, 2.0]


def test_points_rejects_a_series_not_in_the_dataset():
    with pytest.raises(KeyError):
        H.points(_dataset({}), "MISSING")


def test_ratio_and_net_share_use_only_shared_quarters_and_skip_zero_base():
    a = _quarters([10.0, 20.0, 30.0])
    b = _quarters([5.0, 0.0])  # no third quarter; the second is a zero denominator
    assert list(H.ratio(a, b).values) == [2.0]
    long, short, base = _quarters([80.0, 90.0]), _quarters([30.0, 30.0]), _quarters([100.0, 0.0])
    net = H.net_share_of_base(long, short, base)
    assert list(net.values) == [50.0]


def test_change_compares_calendar_quarters_not_day_counts():
    series = _quarters([1.0, 2.0, 3.0, 4.0, 5.0])
    absolute, pct = H.change(series, 1, relative=True)
    assert absolute == 1.0
    assert round(pct, 6) == round(100 * (5.0 / 4.0 - 1), 6)
    absolute, pct = H.change(series, 4, relative=True)  # four quarters back is the first value, 1.0
    assert absolute == 4.0
    assert round(pct, 6) == 400.0


def test_change_is_none_when_the_lagged_quarter_is_absent():
    # Q1 2023 to Q4 2023 with Q2 and Q3 missing: the year-earlier quarter exists, the quarter before does not.
    series = pd.Series([1.0, 2.0], index=pd.to_datetime(["2022-12-31", "2023-12-31"]))
    assert H.change(series, 1, relative=True) == (None, None)
    assert H.change(series, 4, relative=True) == (1.0, 100.0)


def test_relative_change_is_none_for_percent_units_and_zero_bases():
    series = _quarters([-7.0, -6.0, -8.0, -9.0, -5.0])
    absolute, pct = H.change(series, 1, relative=False)
    assert absolute == 4.0 and pct is None
    zero_base = _quarters([0.0, 3.0])
    assert H.change(zero_base, 1, relative=True) == (3.0, None)


def test_percentile_needs_history_and_counts_ties_as_at_or_below():
    short = _quarters(list(range(1, 8)))
    assert H.percentile(short) is None  # seven quarters: too few to rank
    series = _quarters([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 7.0])
    assert H.percentile(series) == 100.0  # the latest value ties the maximum
    series = _quarters([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 3.0])
    assert H.percentile(series) == 50.0  # 1, 2, 3 and the latest 3 are at or below it: four of eight


def test_latest_row_on_an_empty_series_is_all_none():
    row = H.latest_row(pd.Series([], dtype=float), relative=True)
    assert row["period"] is None and row["value"] is None and row["percentile"] is None and row["n_obs"] == 0


# --- source ------------------------------------------------------------------

def test_fetch_dataset_decodes_gzip_by_magic_number(monkeypatch):
    body = json.dumps({"timeseries": {"X": {}}}).encode("utf-8")
    monkeypatch.setattr(ofr, "get_bytes", lambda url, **kwargs: gzip.compress(body))
    assert ofr.fetch_dataset(use_cache=False) == {"timeseries": {"X": {}}}


def test_fetch_dataset_refuses_an_error_object_and_a_non_json_page(monkeypatch):
    monkeypatch.setattr(ofr, "get_bytes", lambda url, **kwargs: b'{"message":"Missing Authentication Token"}')
    with pytest.raises(FetchError, match="Missing Authentication Token"):
        ofr.fetch_dataset(use_cache=False)
    monkeypatch.setattr(ofr, "get_bytes", lambda url, **kwargs: b"<html>maintenance</html>")
    with pytest.raises(FetchError, match="not JSON"):
        ofr.fetch_dataset(use_cache=False)


def test_fetch_dataset_asks_for_the_fpf_dataset_once(monkeypatch):
    seen = []
    monkeypatch.setattr(ofr, "get_bytes", lambda url, **kwargs: seen.append(url) or b'{"timeseries": {}}')
    ofr.fetch_dataset(use_cache=False)
    assert seen == [ofr.DATASET_URL]
    assert "dataset=fpf" in seen[0] and seen[0].startswith("https://data.financialresearch.gov/hf/v1/")


# --- panel -------------------------------------------------------------------

def _ctx():
    return SimpleNamespace(as_of="2026-10-23", log=BuildLog())


def test_build_payload_from_the_fixture(monkeypatch, sample):
    monkeypatch.setattr(ofr, "fetch_dataset", lambda **kwargs: sample)
    ctx = _ctx()
    out = panel.build(ctx, None)
    json.dumps(out, allow_nan=False)  # never NaN in the payload
    assert set(out) == {"as_of", "source", "series", "latest"}
    assert out["source"]["latest_period"] == "2026-06-30"
    assert out["source"]["first_period"] == "2023-03-31"
    assert out["source"]["lag_days"] == 78
    ids = [s["id"] for s in out["series"]]
    assert ids == ["gross_leverage", "equity_long", "equity_short", "equity_net_pct_nav", "equity_down20", "equity_borrowing"]
    by_id = {s["id"]: s for s in out["series"]}
    # Gross assets over net assets: 12.0/5.0 at the first quarter, and the fixture's last quarter.
    assert by_id["gross_leverage"]["values"][0] == 2.4
    assert by_id["gross_leverage"]["unit"] == "x"
    # Net equity exposure: (long - short) over net assets, in per cent.
    first_net = (5.0e12 - 3.0e12) / 5.0e12 * 100
    assert by_id["equity_net_pct_nav"]["values"][0] == round(first_net, 1)
    assert by_id["equity_long"]["unit"] == "$bn"
    assert by_id["equity_long"]["values"][0] == 5000.0
    # The withheld quarter is absent, not zero.
    assert len(by_id["equity_down20"]["dates"]) == 13
    assert "2024-06-30" not in by_id["equity_down20"]["dates"]
    latest = {row["id"]: row for row in out["latest"]}
    assert latest["gross_leverage"]["period"] == "2026-06-30"
    assert latest["gross_leverage"]["q_change"] is not None
    assert latest["equity_net_pct_nav"]["q_change_pct"] is None  # percentage units: no percentage change
    assert latest["gross_leverage"]["n_obs"] == 14
    # The source names come from OFR's own metadata, not from this file.
    assert by_id["equity_long"]["ofr_names"] == ["SYNTHETIC TEST FIXTURE: FPF-ASSETCLASS_EQUITIES_LGNE_SUM"]
    record = ctx.log.sources[-1]
    assert record.source_id == "ofr_formpf" and record.status == "ok"
    assert record.observed_date == "2026-06-30" and record.policy == "quarterly_filing"


def test_build_is_unavailable_and_logged_when_the_fetch_fails(monkeypatch):
    def fail(**kwargs):
        raise FetchError("data.financialresearch.gov: HTTP 503")

    monkeypatch.setattr(ofr, "fetch_dataset", fail)
    ctx = _ctx()
    out = panel.build(ctx, None)
    assert out == {"unavailable": "data.financialresearch.gov: HTTP 503"}
    assert ctx.log.sources[-1].status == "error"


def test_build_is_unavailable_when_a_needed_series_is_absent(monkeypatch, sample):
    del sample["timeseries"]["FPF-ALLQHF_NAV_SUM"]
    monkeypatch.setattr(ofr, "fetch_dataset", lambda **kwargs: sample)
    ctx = _ctx()
    out = panel.build(ctx, None)
    assert "FPF-ALLQHF_NAV_SUM" in out["unavailable"]
    assert ctx.log.sources[-1].status == "error"
