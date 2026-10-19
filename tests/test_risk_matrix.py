"""RISK matrix: percentiles and states per direction, grey rules, changes, and the real config's mapping.

Series are small and synthetic (daily, ending on a fixed date), never the network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import risk as R
from market_recap.config import load_config
from market_recap.panels import risk

THRESHOLDS = {"elevated": 75, "stressed": 95}
END = "2026-10-16"


def _daily(values, end=END):
    """Daily observations ending on ``end``: the last value is the lead's reading."""
    index = pd.date_range(end=end, periods=len(values), freq="D")
    return pd.Series(np.asarray(values, dtype=float), index=index)


def _reading(series, as_of=END, risk_when="high"):
    return R.matrix_reading(series, risk_when=risk_when, as_of=as_of, years=10, min_years=3,
                            stale_days=10, thresholds=THRESHOLDS)


# --- percentile, per direction -----------------------------------------------

def test_percentile_is_read_in_the_risk_direction():
    sample = _daily(np.arange(1, 101, dtype=float))  # 1..100
    assert R.risk_percentile(sample, 50, "high") == pytest.approx(50)     # 50 of 100 at or below
    assert R.risk_percentile(sample, 100, "high") == pytest.approx(100)
    assert R.risk_percentile(sample, 50, "low") == pytest.approx(51)      # 51 of 100 at or above
    assert R.risk_percentile(sample, 1, "low") == pytest.approx(100)


def test_extreme_reads_both_tails_as_high_percentiles():
    sample = _daily(np.arange(1, 101, dtype=float))
    assert R.risk_percentile(sample, 50, "extreme") == pytest.approx(0)      # the median is calm
    assert R.risk_percentile(sample, 100, "extreme") == pytest.approx(100)  # the top tail
    assert R.risk_percentile(sample, 1, "extreme") == pytest.approx(98)     # the bottom tail, as far out


def test_no_value_or_no_history_has_no_percentile():
    sample = _daily([1.0, 2.0])
    assert R.risk_percentile(sample, None, "high") is None
    assert R.risk_percentile(sample, float("nan"), "high") is None
    assert R.risk_percentile(pd.Series(dtype=float), 1.0, "high") is None


# --- states ----------------------------------------------------------------------

def test_state_lines_are_at_75_and_95():
    assert [R.cell_state(p, THRESHOLDS) for p in (74.9, 75, 94.9, 95, 100)] == \
        ["calm", "elevated", "elevated", "stressed", "stressed"]
    assert R.cell_state(None, THRESHOLDS) == "grey"


# --- grey rules ------------------------------------------------------------------

def test_less_than_three_years_of_history_is_grey_with_its_value_shown():
    short = _reading(_daily(np.linspace(0, 1, 365 * 2)))
    assert short["state"] == "grey" and short["percentile"] is None
    assert short["value"] == pytest.approx(1.0) and short["date"] == END
    assert _reading(_daily(np.linspace(0, 1, 365 * 4)))["state"] != "grey"


def test_a_stale_lead_is_grey_at_the_edge_of_its_allowance():
    series = _daily(np.linspace(0, 1, 365 * 4))
    assert _reading(series, as_of="2026-10-26")["state"] != "grey"   # 10 days old: still a reading
    assert _reading(series, as_of="2026-10-27")["state"] == "grey"   # 11 days old: stale


def test_a_missing_value_is_grey_with_nothing_else():
    empty = _reading(pd.Series(dtype=float))
    assert empty == {"value": None, "date": None, "percentile": None, "state": "grey", "state_prev": None,
                     "change_1m": None, "worse_1m": None, "years_used": None}


def test_a_source_shorter_than_the_window_says_how_many_years_it_was_read_over():
    days = pd.bdate_range("2023-10-17", "2026-10-16")
    reading = R.matrix_reading(pd.Series(range(len(days)), index=days, dtype=float), risk_when="high",
                               as_of="2026-10-16", years=10, min_years=2.5, stale_days=10,
                               thresholds={"elevated": 75, "stressed": 95})
    assert reading["years_used"] == 3.0 and reading["state"] == "stressed"


# --- one-month change and its direction ------------------------------------------

def _month(values, risk_when):
    return _reading(_daily(values), risk_when=risk_when)


def test_high_series_rising_is_worse_and_falling_is_better():
    rising = np.zeros(1460)
    rising[-1] = 3.0
    falling = np.zeros(1460)
    falling[-1] = -3.0
    assert _month(rising, "high")["change_1m"] == pytest.approx(3.0)
    assert _month(rising, "high")["worse_1m"] is True
    assert _month(falling, "high")["worse_1m"] is False


def test_low_series_falling_is_worse_and_rising_is_better():
    falling = np.zeros(1460)
    falling[-1] = -3.0
    rising = np.zeros(1460)
    rising[-1] = 3.0
    assert _month(falling, "low")["change_1m"] == pytest.approx(-3.0)
    assert _month(falling, "low")["worse_1m"] is True
    assert _month(rising, "low")["worse_1m"] is False


def test_extreme_series_is_worse_when_moving_away_from_its_ten_year_median():
    away = np.zeros(1460)
    away[-31] = 0.0   # 30 calendar days before the last observation
    away[-1] = 5.0    # moved away from the median (zero)
    back = np.zeros(1460)
    back[-31] = 5.0
    back[-1] = 0.0    # moved toward the median
    assert _month(away, "extreme")["worse_1m"] is True
    assert _month(back, "extreme")["worse_1m"] is False
    assert _month(back, "extreme")["change_1m"] == pytest.approx(-5.0)


# --- state before --------------------------------------------------------------

def test_state_prev_is_the_same_test_one_observation_earlier():
    values = np.concatenate([np.linspace(0, 100, 1460 - 2), [1.0, 100.0]])
    reading = _reading(_daily(values))
    assert reading["state"] == "stressed"
    assert reading["state_prev"] == "calm"


# --- the panel's cells -----------------------------------------------------------

def _settings(cells, rows=(("volatility", "VOLATILITY"),), columns=(("technical", "TECHNICAL"),), tiles=()):
    return {
        "tiles": list(tiles),
        "matrix": {"elevated": 75, "stressed": 95, "years": 10, "min_years": 3,
                   "stale_days_daily": 10, "stale_days_weekly": 21,
                   "rows": [{"key": k, "label": v} for k, v in rows],
                   "columns": [{"key": k, "label": v} for k, v in columns],
                   "cells": cells},
    }


def test_a_placeholder_cell_has_no_lead_no_members_and_a_dash():
    matrix = risk._matrix(_settings([]), {}, {}, END)
    (cell,) = matrix["cells"]
    assert cell["lead"] is None and cell["members"] == [] and cell["pending"] == "—"
    assert cell["state"] == "grey" and cell["value"] is None
    assert matrix["thresholds"] == {"elevated": 75, "stressed": 95} and matrix["years"] == 10


def test_a_lead_that_fails_leaves_its_cell_grey_and_the_others_render():
    def broken():
        raise ZeroDivisionError("no data")

    settings = _settings(
        [{"row": "volatility", "column": "technical", "lead": "vix", "members": ["vix"]},
         {"row": "volatility", "column": "structure", "lead": "baa10y_4w", "members": []}],
        columns=(("technical", "TECHNICAL"), ("structure", "STRUCTURE")),
        tiles=[{"key": "vix", "label": "VIX", "unit": "pts", "risk_when": "high"}])
    series = _daily(np.linspace(0, 1, 365 * 4))
    builders = {"vix": broken, "baa10y_4w": lambda: series}
    cells = {c["column"]: c for c in risk._matrix(settings, builders, {}, END)["cells"]}
    assert cells["technical"]["state"] == "grey" and cells["technical"]["value"] is None
    assert cells["technical"]["label"] == "VIX"
    assert cells["structure"]["state"] != "grey" and cells["structure"]["label"] == "BAA − 10Y · 20D CHANGE"


# The leads the real config must produce, one per row and column; None is a placeholder.
EXPECTED_LEADS = {
    ("equities", "structure"): "vix_term", ("equities", "technical"): "spx_drawdown",
    ("equities", "fundamental"): None,
    ("treasuries", "structure"): None, ("treasuries", "technical"): "move",
    ("treasuries", "fundamental"): "real_10y_3m",
    ("credit", "structure"): "hyg_ief", ("credit", "technical"): "baa10y_4w",
    ("credit", "fundamental"): "baa10y",
    ("volatility", "structure"): "vvix", ("volatility", "technical"): "vix",
    ("volatility", "fundamental"): "vrp",
    ("cross_asset", "structure"): "dxy_3m", ("cross_asset", "technical"): None,
    ("cross_asset", "fundamental"): "copper_oil",
    ("macro", "structure"): "net_liquidity", ("macro", "technical"): None,
    ("macro", "fundamental"): "nfci",
}


def test_the_real_config_builds_eighteen_cells_with_their_leads_and_risk_directions():
    settings = load_config()["risk"]
    series = _daily(np.cumsum(np.random.default_rng(3).normal(size=1460)) + 100)
    keys = [t["key"] for t in settings["tiles"]] + list(risk.DERIVED_LEADS)
    builders = {key: (lambda s=series: s) for key in keys}
    matrix = risk._matrix(settings, builders, {}, END)
    cells = matrix["cells"]
    assert len(cells) == 18
    assert {(c["row"], c["column"]): c["lead"] for c in cells} == EXPECTED_LEADS
    directions = {t["key"]: t["risk_when"] for t in settings["tiles"]}
    directions.update({k: v["risk_when"] for k, v in risk.DERIVED_LEADS.items()})
    for cell in cells:
        if cell["lead"] is None:
            continue
        assert cell["risk_when"] == directions[cell["lead"]]
        assert cell["percentile"] is not None
        expected = ("unrated",) if cell["scale"] == "none" else ("calm", "elevated", "stressed")
        assert cell["state"] in expected


def test_every_banded_cell_has_two_lines_in_its_risk_direction():
    settings = load_config()["risk"]
    directions = {t["key"]: t["risk_when"] for t in settings["tiles"]}
    directions.update({k: v["risk_when"] for k, v in risk.DERIVED_LEADS.items()})
    banded = [c for c in settings["matrix"]["cells"] if c.get("scale") == "bands"]
    assert len(banded) == 10
    for cell in banded:
        elevated, stressed = cell["bands"]["elevated"], cell["bands"]["stressed"]
        # The stressed line lies further in the risk direction than the elevated one.
        assert (stressed > elevated) if directions[cell["lead"]] == "high" else (stressed < elevated), cell["lead"]


def test_the_real_config_keeps_its_members_notes_caution_and_pending_text():
    settings = load_config()["risk"]
    series = _daily(np.cumsum(np.random.default_rng(3).normal(size=1460)) + 100)
    builders = {key: (lambda s=series: s) for key in [t["key"] for t in settings["tiles"]] + list(risk.DERIVED_LEADS)}
    cells = {(c["row"], c["column"]): c for c in risk._matrix(settings, builders, {}, END)["cells"]}
    assert cells[("equities", "structure")]["members"] == [
        "vix_term", "vix9d_term", "skew", "vx_front", "put_call", "cftc_es", "cftc_nq"]
    assert cells[("credit", "technical")]["members"] == ["baa10y", "hy_oas"]
    assert cells[("cross_asset", "fundamental")]["caution"] == "failed out of sample"
    assert cells[("cross_asset", "fundamental")]["members"] == ["copper_oil", "ovx"]
    assert cells[("equities", "fundamental")]["pending"] == \
        "Equity risk premium: forward earnings yield less the real yield (next step)"
    assert cells[("cross_asset", "technical")]["pending"] == "Stock–bond correlation (next step)"
    assert cells[("treasuries", "structure")]["members"] == ["cftc_zn"]
    assert cells[("treasuries", "fundamental")]["note"].endswith("Term premium to follow (next step)")
    assert cells[("credit", "fundamental")]["members"] == ["baa10y", "hy_oas", "ccc_oas", "ig_oas"]
    assert cells[("macro", "fundamental")]["note"] == "OFR Financial Stress Index to follow (next step)"
    assert cells[("macro", "technical")]["pending"] == "—"


# --- fixed bands and the unrated scale ---------------------------------------------

def test_bands_read_the_value_against_lines_in_its_risk_direction():
    high = {"elevated": 25.0, "stressed": 35.0}
    assert [R.band_state(v, high, "high") for v in (24.9, 25.0, 34.9, 35.0)] == \
        ["calm", "elevated", "elevated", "stressed"]
    low = {"elevated": -2.0, "stressed": -5.0}
    assert [R.band_state(v, low, "low") for v in (-1.9, -2.0, -4.9, -5.0)] == \
        ["calm", "elevated", "elevated", "stressed"]
    assert R.band_state(None, high, "high") == "grey"


def test_a_banded_cell_ignores_the_percentile_for_its_colour():
    # A calm decade then a modest rise: the 10y percentile is at the top, the level is not.
    series = _daily(np.r_[np.full(365 * 4 - 1, 12.0), 20.0])
    reading = R.matrix_reading(series, risk_when="high", as_of=END, years=10, min_years=3, stale_days=10,
                               thresholds=THRESHOLDS, scale="bands", bands={"elevated": 25.0, "stressed": 35.0})
    assert reading["percentile"] == 100.0 and reading["state"] == "calm"
    assert reading["state_prev"] == "calm"


def test_a_banded_cell_needs_no_minimum_history_and_still_goes_stale():
    series = _daily(np.full(200, 40.0))
    kwargs = dict(risk_when="high", years=10, min_years=3, thresholds=THRESHOLDS, scale="bands",
                  bands={"elevated": 25.0, "stressed": 35.0})
    reading = R.matrix_reading(series, as_of=END, stale_days=10, **kwargs)
    assert reading["state"] == "stressed" and reading["percentile"] is None
    late = (pd.Timestamp(END) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    assert R.matrix_reading(series, as_of=late, stale_days=10, **kwargs)["state"] == "grey"


def test_an_unrated_cell_shows_its_percentile_but_no_colour():
    series = _daily(np.linspace(0, 1, 365 * 4))
    reading = R.matrix_reading(series, risk_when="high", as_of=END, years=10, min_years=3, stale_days=10,
                               thresholds=THRESHOLDS, scale="none")
    assert reading["state"] == "unrated" and reading["state_prev"] == "unrated"
    assert reading["percentile"] == 100.0
