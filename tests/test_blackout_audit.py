import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


spec = importlib.util.spec_from_file_location('blackout_audit', Path(__file__).resolve().parents[1] / 'scripts/audit_blackout_backtest.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_probabilities_are_percent_and_only_complete_outcomes_are_scored():
    index = pd.date_range('2026-01-01', periods=5)
    outcomes = pd.DataFrame({'ret': [1, -1, 3, np.nan, np.nan], 'worst_dd': [-1, -6, -2, np.nan, np.nan], 'hit': [0, 1, 0, np.nan, np.nan]}, index=index)
    found = audit.summarize(outcomes, pd.Series(True, index=index), 2)
    daily = found['daily_overlapping']
    assert daily['n'] == 3
    assert daily['median_return_pct'] == 1
    assert daily['positive_return_probability_pct'] == pytest.approx(66.7)
    assert daily['fall_5pct_probability_pct'] == pytest.approx(33.3)
    assert found['nonoverlapping_entries']['n'] == 2


def test_empty_group_stays_missing_not_zero_probability():
    outcomes = pd.DataFrame({'ret': [1], 'worst_dd': [-1], 'hit': [0]})
    found = audit.summarize(outcomes, pd.Series([False]), 5)['daily_overlapping']
    assert found['n'] == 0
    assert found['mean_return_pct'] is None
    assert found['fall_5pct_probability_pct'] is None


def test_derivative_groups_keep_direction_acceleration_and_turns_distinct():
    velocity = pd.Series([np.nan, 0, 2, 1, -1, -2, -1, 0, 2])
    acceleration = pd.Series([np.nan, 0, 2, -1, -2, -1, 1, 1, 2])
    groups = audit.momentum_groups(velocity, acceleration)
    assert np.flatnonzero(groups['upturn_from_nonpositive']).tolist() == [2, 8]
    assert np.flatnonzero(groups['downturn_from_nonnegative']).tolist() == [4]
    assert np.flatnonzero(groups['rising_decelerating']).tolist() == [3]
    assert np.flatnonzero(groups['falling_decelerating']).tolist() == [6]
    assert not groups['coverage_rising'][0]
