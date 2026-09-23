"""Yahoo's recent sessions checked against IVV's closes, and rebuilt when wrong or missing."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import gapfill

DAYS = pd.to_datetime(["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23"])
SYMBOLS = [f"S{i}" for i in range(120)] + ["ASML"]


def _frames(day_22_scale=1.0):
    raw = pd.DataFrame(100.0, index=DAYS, columns=SYMBOLS)
    raw.loc["2026-09-22"] = 101.0
    raw.loc["2026-09-23"] = 102.0
    adjusted = raw * 0.98            # a dividend after these dates: factor 0.98
    adjusted.loc["2026-09-22"] *= day_22_scale
    return adjusted, raw


@pytest.fixture
def sources(monkeypatch):
    holdings = {gapfill.ticker_key(s): 101.0 for s in SYMBOLS if s != "ASML"}
    monkeypatch.setattr(gapfill, "_holdings", lambda use_cache: (pd.Timestamp("2026-09-22"), holdings))
    monkeypatch.setattr(gapfill, "_nasdaq_closes", lambda s, a, b, c, u: {"2026-09-22": 101.0} if s == "ASML" else {})
    monkeypatch.setattr(gapfill, "_fred_closes", lambda s, u: {})


def test_a_session_that_agrees_with_the_issuer_passes(sources):
    adjusted, raw = _frames()
    check = gapfill.verify(adjusted, raw)
    assert check["names"] == 120 and check["median_deviation_pct"] == pytest.approx(0.0) and not check["suspect"]


def test_a_stale_session_is_flagged_and_rebuilt_on_the_adjusted_basis(sources):
    adjusted, raw = _frames(day_22_scale=1.01)     # every close 1% off, as on 2026-09-22
    check = gapfill.verify(adjusted, raw)
    assert check["suspect"] and check["median_deviation_pct"] == pytest.approx(1.0, abs=0.01)
    fixed, fixed_raw, report = gapfill.fill(adjusted, raw, label="constituents", replace=[pd.Timestamp("2026-09-22")])
    assert fixed.at[pd.Timestamp("2026-09-22"), "S0"] == pytest.approx(101.0 * 0.98)
    assert fixed_raw.at[pd.Timestamp("2026-09-22"), "S0"] == 101.0
    day = report["2026-09-22"]
    assert (day["ishares"], day["nasdaq"], day["unfilled"]) == (120, 1, 0)


def test_a_dropped_session_is_filled(sources):
    adjusted, raw = _frames()
    adjusted.loc["2026-09-22"] = np.nan
    fixed, _, report = gapfill.fill(adjusted, raw.drop(index=pd.Timestamp("2026-09-22")), label="constituents")
    assert report["2026-09-22"]["reason"] == "missing at Yahoo"
    assert fixed.loc["2026-09-22"].notna().all()


def test_nothing_to_do_returns_the_frame_untouched(sources):
    adjusted, raw = _frames()
    same, _, report = gapfill.fill(adjusted, raw, label="constituents")
    assert report == {} and same is adjusted
