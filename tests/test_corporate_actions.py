"""Spin-off adjustments: the feed does not make them, and a false -84% reads as a loss."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import corporate_actions as ca, validate

DAYS = pd.to_datetime(["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"])
CONFIG = {"corporate_actions": [{
    "ticker": "CTVA", "kind": "spin-off", "ex_date": "2026-10-01", "distributed": "VYLR",
    "ratio": 1.0, "source": "https://example.com/8-K"}]}


def _prices(vylr=(np.nan, np.nan, 68.26, 67.26)):
    return pd.DataFrame({"CTVA": [77.87, 77.65, 12.57, 11.92], "VYLR": list(vylr), "AAPL": [200.0, 201.0, 202.0, 203.0]},
                        index=DAYS)


def test_factor_is_read_from_the_prices_on_the_ex_date():
    (item,) = ca.resolve(CONFIG, _prices())
    assert item.factor == pytest.approx(12.57 / (12.57 + 68.26))


def test_history_before_the_ex_date_is_rescaled_and_the_rest_left_alone():
    prices = _prices()
    (item,) = ca.resolve(CONFIG, prices)
    out = ca.adjust(prices, [item])
    # Across the ex-date the stub and the distributed share together moved about +4%, not -84%.
    ex_day_return = out.at[DAYS[2], "CTVA"] / out.at[DAYS[1], "CTVA"] - 1
    assert ex_day_return == pytest.approx((12.57 + 68.26) / 77.65 - 1)
    assert 0.03 < ex_day_return < 0.05
    assert out.loc[DAYS[2]:, "CTVA"].tolist() == [12.57, 11.92]
    assert out["AAPL"].tolist() == prices["AAPL"].tolist()
    assert prices.at[DAYS[0], "CTVA"] == 77.87  # the input is not modified


def test_history_is_dropped_when_the_distributed_line_has_no_price():
    prices = _prices(vylr=(np.nan, np.nan, np.nan, np.nan))
    (item,) = ca.resolve(CONFIG, prices)
    assert item.factor is None
    out = ca.adjust(prices, [item])
    assert out["CTVA"].iloc[:2].isna().all() and out["CTVA"].iloc[2:].notna().all()


def test_an_action_dated_after_the_last_session_is_not_in_effect_yet():
    future = {"corporate_actions": [{**CONFIG["corporate_actions"][0], "ex_date": "2026-11-01"}]}
    assert ca.resolve(future, _prices()) == []


def test_a_malformed_entry_is_a_configuration_error():
    bad = {"corporate_actions": [{"ticker": "CTVA", "kind": "spin-off", "ex_date": "2026-10-01"}]}
    with pytest.raises(ValueError, match="distributed"):
        ca.resolve(bad, _prices())


def test_moves_are_listed_only_when_unadjusted_and_without_a_split():
    prices = _prices()
    listed = ca.unexplained_moves(prices, None, drop_pct=60, rise_pct=150, sessions=10)
    assert [(m["ticker"], m["date"]) for m in listed] == [("CTVA", "2026-10-01")]
    # Once the configured action is applied the move is explained and not listed.
    adjusted = ca.adjust(prices, ca.resolve(CONFIG, prices))
    assert ca.unexplained_moves(adjusted, None, drop_pct=60, rise_pct=150, sessions=10) == []
    # A split on record explains it too.
    splits = pd.DataFrame({"CTVA": [np.nan, np.nan, 0.2, np.nan]}, index=DAYS)
    assert ca.unexplained_moves(prices, splits, drop_pct=60, rise_pct=150, sessions=10) == []


def test_validate_warns_on_an_uncomputable_action_and_only_notes_a_jump():
    manifest = {"corporate_actions": [{"ticker": "CTVA", "distributed": "VYLR", "ex_date": "2026-10-01", "factor": None}],
                "price_jumps": [{"ticker": "XYZ", "date": "2026-10-01", "move_pct": -71.0}]}
    findings = validate._check_price_actions(manifest)
    assert [(f.severity, f.check) for f in findings] == [("warning", "corporate_actions"), ("notice", "price_jump")]
    ok = {"corporate_actions": [{"ticker": "CTVA", "factor": 0.155}], "price_jumps": []}
    assert validate._check_price_actions(ok) == []


def test_both_lines_are_priced_for_the_factor_and_then_dropped():
    # By 2026-10-06 SPY held Vylor and not Corteva: both are still priced, for this only.
    assert ca.priced_lines(CONFIG) == {"CTVA", "VYLR"}
    assert ca.priced_lines({}) == set()
    frame = pd.DataFrame({"CTVA": [1.0], "VYLR": [2.0]})
    assert list(ca.drop_extra(frame, {"VYLR"}).columns) == ["CTVA"]
    assert list(ca.drop_extra(frame, set()).columns) == ["CTVA", "VYLR"]
    assert ca.drop_extra(pd.DataFrame(), {"VYLR"}).empty


def test_an_unknown_factor_names_the_line_without_a_price():
    prices = pd.DataFrame({"VYLR": [68.26]}, index=pd.to_datetime(["2026-10-01"]))
    [item] = ca.resolve(CONFIG, prices)
    assert item.factor is None and item.unpriced == ("CTVA",)
    findings = validate._check_price_actions({"corporate_actions": [item.as_dict()]})
    assert "no price for CTVA on 2026-10-01" in findings[0].detail


def test_a_split_yahoo_announced_but_did_not_apply_is_applied_once():
    """2026-11-05: SOXX split 3:1; the new close came with the old history and read -70.7%."""
    days = pd.to_datetime(["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"])
    raw = pd.DataFrame({"SOXX": [465.0, 450.41, 131.90, 133.0], "XLK": [170.0, 176.5, 162.4, 163.0]}, index=days)
    splits = pd.DataFrame({"SOXX": [float("nan"), float("nan"), 3.0, float("nan")]}, index=days)
    fixed, applied = ca.unapplied_splits(raw, splits)
    assert [a["ticker"] for a in applied] == ["SOXX"] and applied[0]["ratio"] == 3.0
    assert abs(fixed.at[days[1], "SOXX"] - 150.1367) < 1e-3 and fixed.at[days[2], "SOXX"] == 131.90
    assert fixed["XLK"].equals(raw["XLK"]) and raw.at[days[1], "SOXX"] == 450.41   # the input is not changed
    # Once Yahoo has rescaled its history the ex-date move is ordinary: nothing more is done.
    again, none = ca.unapplied_splits(fixed, splits)
    assert none == [] and again.equals(fixed)
    # A split day whose move is not the split's ratio (a real -12% on adjusted history) is left alone.
    assert ca.unapplied_splits(raw.assign(SOXX=[465.0, 150.14, 131.90, 133.0]), splits)[1] == []


def test_small_ratios_are_not_splits_and_only_the_unadjusted_stretch_is_rescaled():
    days = pd.to_datetime(["2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"])
    # Yahoo's SOXX that night: adjusted to 10-30, the old scale from 11-02, the new close on 11-05.
    raw = pd.DataFrame({"SOXX": [171.29, 157.17, 453.65, 465.0, 450.41, 131.90],
                        "GE": [100.0, 101.0, 99.0, 100.5, 102.0, 101.0]}, index=days)
    splits = pd.DataFrame({"SOXX": [np.nan] * 5 + [3.0], "GE": [np.nan] * 5 + [1.04]}, index=days)
    fixed, applied = ca.unapplied_splits(raw, splits)
    assert [(a["ticker"], a["from"]) for a in applied] == [("SOXX", "2026-11-02")]   # GE's 1.04 is not a split
    assert fixed["GE"].equals(raw["GE"])
    assert list(fixed["SOXX"].round(2)) == [171.29, 157.17, 151.22, 155.0, 150.14, 131.90]
