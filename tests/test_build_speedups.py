"""Faster forms of hot build code must give exactly what the plain forms gave."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from market_recap.compute import catalysts as C
from market_recap.compute.scenarios import _spearman
from market_recap.util import clean_float, clean_floats


def test_clean_floats_equals_clean_float_per_element():
    rng = np.random.default_rng(3)
    values = rng.normal(0, 1e4, 5000) * rng.choice([1e-6, 1, 1e6], 5000)
    values[::97] = np.nan
    values[5], values[6] = np.inf, -np.inf
    for digits in (None, 0, 2, 4):
        assert clean_floats(values, digits) == [clean_float(v, digits) for v in values]
    mixed = [1.23456, None, "x", float("nan"), 7]
    assert clean_floats(mixed, 2) == [clean_float(v, 2) for v in mixed]
    assert clean_floats(pd.Series([], dtype=float).to_numpy(), 2) == []


def test_spearman_matches_pandas_ranks_with_ties():
    rng = np.random.default_rng(5)
    for _ in range(200):
        n = int(rng.integers(5, 12))
        a = rng.integers(0, 4, n).astype(float)   # many ties
        b = rng.normal(size=n)
        ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
        expected = float("nan") if ra.std() == 0 or rb.std() == 0 else float(np.corrcoef(ra, rb)[0, 1])
        got = _spearman(a, b)
        assert (np.isnan(got) and np.isnan(expected)) or abs(got - expected) < 1e-12


def test_cached_holidays_are_the_same_and_a_callers_copy_is_its_own():
    first = C.nyse_holidays(2026)
    assert first[date(2026, 4, 3)] == "Good Friday" and date(2026, 1, 1) in first
    first[date(2026, 5, 5)] = "not a holiday"
    assert date(2026, 5, 5) not in C.nyse_holidays(2026)
    assert C.is_session(date(2026, 10, 29)) and not C.is_session(date(2026, 11, 26))
