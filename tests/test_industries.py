"""INDUSTRIES: a group read as the median of its names, and what each flag means."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import config, validate
from market_recap.compute import industries as I
from market_recap.panels import industries as panel

SETTINGS = config.load_config()["industries"]


def _members(rows, sector="Financials", sub="Banks"):
    frame = pd.DataFrame(rows)
    frame.index = [f"T{i}" for i in range(len(frame))]
    for column in I.MEMBER_FIELDS:
        if column not in frame:
            frame[column] = np.nan if column != "name" else "n"
    frame["sector"], frame["sub_sector"] = sector, sub
    return frame


def _row(frame, **kwargs):
    return I.group_row(frame, SETTINGS, sector="Financials", label="Banks", kind="sub_industry", with_members=True, **kwargs)


def test_a_group_is_its_median_member_not_its_biggest_name():
    frame = _members([{"weight": 90, "r1M": 10.0}, {"weight": 5, "r1M": -8.0}, {"weight": 5, "r1M": -9.0},
                      {"weight": 1, "r1M": -10.0}, {"weight": 1, "r1M": -11.0}])
    row = _row(frame)
    assert row["returns"]["1M"] == -9.0
    assert row["down_share"] == 80
    assert row["best"]["ticker"] == "T0" and row["worst"]["ticker"] == "T4"


def test_sold_off_needs_both_the_median_and_the_breadth():
    deep_but_narrow = _members([{"r1M": -50.0}, {"r1M": 3.0}, {"r1M": 2.0}, {"r1M": 1.0}, {"r1M": 4.0}])
    assert _row(deep_but_narrow)["evidence"]["sold_off"] is False   # one name's crash is not an industry's
    broad = _members([{"r1M": -7.0}, {"r1M": -8.0}, {"r1M": -9.0}, {"r1M": -6.5}, {"r1M": -6.1}])
    assert _row(broad)["evidence"]["sold_off"] is True
    shallow = _members([{"r1M": -2.0}] * 5)
    assert _row(shallow)["evidence"]["sold_off"] is False


def test_estimates_are_cut_when_either_median_is_below_its_threshold_and_unknown_when_missing():
    held = _members([{"r1M": -7.0, "rev30": 0.2, "rev90": 1.0}] * 4)
    cut_recent = _members([{"r1M": -7.0, "rev30": -1.0, "rev90": 1.0}] * 4)
    cut_longer = _members([{"r1M": -7.0, "rev30": 0.1, "rev90": -1.2}] * 4)
    noise = _members([{"r1M": -7.0, "rev30": -0.1, "rev90": -0.04}] * 4)   # Insurance Brokers, 2026-10-06
    assert _row(held)["evidence"]["estimates_cut"] is False
    assert _row(cut_recent)["evidence"]["estimates_cut"] is True
    assert _row(cut_longer)["evidence"]["estimates_cut"] is True
    assert _row(noise)["evidence"]["estimates_cut"] is False
    assert _row(_members([{"r1M": -7.0}] * 4))["evidence"]["estimates_cut"] is None


def test_cheap_is_the_median_percentile_against_the_threshold():
    cheap = _members([{"pe_percentile": 10.0}, {"pe_percentile": 40.0}, {"pe_percentile": 90.0}])
    assert _row(cheap)["evidence"]["cheap_vs_own_history"] is True      # median 40 <= 50
    assert _row(_members([{"pe_percentile": 80.0}] * 3))["evidence"]["cheap_vs_own_history"] is False
    assert _row(_members([{"pe_percentile": np.nan}] * 3))["pe_percentile"]["median"] is None


def test_pe_is_withheld_where_it_is_not_the_multiple():
    reits = _members([{"fwd_pe": 115.0, "pe_percentile": 68.0}] * 3, sector="Real Estate", sub="Health Care REITs")
    row = I.group_row(reits, SETTINGS, sector="Real Estate", label="Health Care REITs", kind="sub_industry", with_members=True)
    assert row["forward_pe"]["median"] is None and row["pe_percentile"]["median"] is None
    assert row["evidence"]["cheap_vs_own_history"] is None
    assert all(m["forward_pe"] is None for m in row["member_rows"])


def test_a_small_group_is_marked_thin_and_a_smaller_one_is_not_shown():
    five = _members([{"r1M": -1.0}] * 5)
    assert _row(five)["thin"] is False
    assert _row(_members([{"r1M": -1.0}] * 3))["thin"] is True
    frame = pd.concat([_members([{"r1M": -1.0}] * 3, sub="Banks"), _members([{"r1M": -2.0}] * 2, sub="Cable")])
    card = I.scorecard(frame, SETTINGS)
    assert [r["label"] for r in card["sub_industries"]] == ["Banks"]
    assert card["omitted"] == {"groups": 1, "names": 2, "examples": ["Cable (2)"]}
    assert card["sectors"][0]["members"] == 5          # the sector row still counts every name


def test_a_percentage_off_a_loss_is_not_a_revision():
    assert I.revision(2.0, 1.0) == pytest.approx(100.0)
    assert I.revision(-1.0, 1.0) is None              # a loss now
    assert I.revision(1.0, -1.0) is None              # a loss before: the ratio is meaningless
    assert I.revision(1.0, None) is None
    assert I.revision(24.0, 22.5, reported=6.5) == 6.5   # the monitor's roll-over-aware figure wins


class _Frame:
    """Just enough of the build context for the panel."""

    def __init__(self, closes, members):
        self.config = {"industries": SETTINGS}
        self.closes, self._members = closes, members
        self.as_of, self.holdings_as_of = "2026-10-05", "2026-10-05"
        self.primary = type("P", (), {"key": "SPX", "label": "S&P 500", "holdings_etf": "SPY"})()

    def priced(self, key):
        return self._members


def _ctx():
    days = pd.bdate_range("2025-09-01", periods=260)
    rng = np.random.default_rng(1)
    closes = pd.DataFrame({s: 100 * np.cumprod(1 + rng.normal(0, 0.01, len(days))) for s in "ABC"}, index=days)
    members = pd.DataFrame({"yahoo_symbol": list("ABC"), "name": ["a co", "b co", "c co"], "sector": "Financials",
                            "sub_sector": "Banks", "weight": [1.0, 2.0, 3.0]})
    return _Frame(closes, members)


def test_the_panel_names_an_input_that_did_not_build_and_leaves_its_columns_empty():
    out = panel.build(_ctx(), {"valuation": None, "monitor": None})
    assert out["missing"] == ["valuation", "monitor"]
    row = out["sub_industries"][0]
    assert row["drawdown"] is None and row["revision"]["90d"] is None and row["forward_pe"]["median"] is None
    assert row["returns"]["1M"] is not None and row["above_ma"] is not None


def test_the_panel_reads_drawdown_revisions_and_multiples_from_the_session_panels():
    monitor = {"rows": [{"ticker": t, "drawdown_pct": -12.0,
                         "expectations": {"eps": 2.0, "eps_30d": 2.0, "eps_90d": 1.9, "change_30d_pct": 0.0, "change_90d_pct": 5.2}}
                        for t in "ABC"]}
    valuation = {"rows": [{"ticker": t, "pe_forward": 11.0, "pe_percentile": 30.0} for t in "ABC"]}
    out = panel.build(_ctx(), {"valuation": valuation, "monitor": monitor})
    row = out["sub_industries"][0]
    assert out["missing"] == []
    assert row["drawdown"] == -12.0 and row["revision"] == {"30d": 0.0, "90d": 5.2, "names": 3}
    assert row["forward_pe"]["median"] == 11.0 and row["evidence"]["cheap_vs_own_history"] is True
    assert set(out["settings"]) >= {"sold_off_return_pct", "no_pe_sectors"}


def test_validate_notes_an_input_the_scorecard_lacked_and_is_quiet_otherwise():
    findings = validate._check_industries({"missing": ["monitor"], "sub_industries": [{}], "sectors": [{}]})
    assert [(f.severity, f.check) for f in findings] == [("notice", "industries")]
    assert "monitor" in findings[0].detail
    assert validate._check_industries({"missing": [], "sub_industries": [{}], "sectors": [{}]}) == []
    assert validate._check_industries(None) == []
    # No groups at all is not a quiet market; it is a build that read nothing.
    assert validate._check_industries({"missing": [], "sub_industries": [], "sectors": []})[0].severity == "warning"
