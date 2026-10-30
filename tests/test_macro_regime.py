import pandas as pd

from market_recap.compute.macro_regime import build


def test_pairs_reference_months_and_requires_actual_three_month_lag():
    growth = pd.Series([-.2, .1, .2, .3], index=pd.to_datetime(['2024-01-01', '2024-04-01', '2024-05-01', '2024-06-01']))
    core = pd.Series([3.0, 2.8, 2.9, 3.4], index=pd.to_datetime(['2024-01-01', '2024-02-01', '2024-04-01', '2024-06-01']))
    result = build(growth, core)
    assert [p['month'] for p in result['points']] == ['2024-04']
    assert result['latest']['growth'] == .1
    assert result['latest']['inflation_change_pp'] == -.1


def test_missing_data_is_not_filled_or_classified():
    assert build(pd.Series(dtype=float), pd.Series(dtype=float))['latest'] is None
