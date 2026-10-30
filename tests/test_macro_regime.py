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


import json

import numpy as np

from market_recap.compute.macro_regime import calibrate, nowcast, quadrant, update_ledger
from market_recap.sources.nowcast import parse_cleveland


def _block(target, labels, series):
    return {'chart': {'subcaption': target}, 'categories': [{'category': [{'label': l} for l in labels]}],
            'dataset': [{'seriesname': name, 'data': [{'value': v} for v in values]} for name, values in series.items()]}


def test_cleveland_labels_without_a_year_roll_into_january_and_skip_release_markers():
    payload = json.dumps([_block('2025-12', ['12/30', 'PCE Nov', '01/02'],
                                 {'Core PCE Inflation': ['2.9', '2.9', '3.0'], 'CPI Inflation': ['1', '1', '1']})]).encode()
    frame = parse_cleveland(payload)
    assert list(frame['asof'].dt.strftime('%Y-%m-%d')) == ['2025-12-30', '2026-01-02']
    assert frame.value.tolist() == [2.9, 3.0]


def _monthly(start, values):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq='MS'), dtype=float)


def test_now_point_uses_nowcasts_past_the_last_matched_month_and_official_prints_where_they_exist():
    months = pd.date_range('2015-01-01', '2026-10-01', freq='MS')
    ads_daily = pd.Series(np.tile([.1, -.1], len(pd.date_range('2015-01-01', '2026-10-24')) // 2 + 1)[:len(pd.date_range('2015-01-01', '2026-10-24'))],
                          index=pd.date_range('2015-01-01', '2026-10-24'))
    monthly_ads = ads_daily.groupby(ads_daily.index.to_period('M')).mean().rolling(3).mean()
    growth = pd.Series(0.5 * monthly_ads.to_numpy()[:-1] + 0.01, index=months[:-1]).dropna()   # CFNAI through Sep
    core = _monthly('2015-01-01', [2.0] * (len(months) - 2))                                     # core PCE through Aug
    regime = {'latest': {'month': '2026-08'}}
    cleveland = pd.DataFrame({'target': pd.to_datetime(['2026-09-01', '2026-09-01', '2026-10-01']),
                              'asof': pd.to_datetime(['2026-09-20', '2026-10-01', '2026-10-29']), 'value': [2.3, 2.4, 2.6]})
    result = nowcast(regime, growth, core, cleveland, ads_daily, change_months=3)
    sep, oct_ = result['points']
    assert (sep['month'], sep['growth_source'], sep['inflation_source']) == ('2026-09', 'official', 'cleveland')
    assert sep['inflation_yoy'] == 2.4 and abs(sep['inflation_change_pp'] - 0.4) < 1e-9     # latest nowcast, vs Jun official
    assert (oct_['growth_source'], oct_['ads_days']) == ('ads', 24)
    assert abs(result['calibration']['slope'] - 0.5) < 1e-6


def test_calibration_leaves_out_the_pandemic_months_and_needs_two_years():
    ads3 = _monthly('2019-01-01', [0.0] * 30).to_period('M')
    assert calibrate(ads3.iloc[:20], _monthly('2019-01-01', [0.0] * 20)) is None
    big = _monthly('2018-01-01', list(range(60)))
    fit = calibrate(big.to_period('M') * 1.0, big * 2.0 + 1)
    assert fit['months'] == 60 - 16 and abs(fit['slope'] - 2) < 1e-9


def test_ledger_keeps_one_row_per_build_date_and_scores_a_month_once_as_first_seen():
    now = {'points': [{'month': '2026-10', 'growth': .1, 'growth_source': 'ads', 'inflation_yoy': 3.2, 'inflation_change_pp': .2}]}
    rows = update_ledger([], now, {'points': []}, '2026-10-30')
    rows = update_ledger(rows, now, {'points': []}, '2026-10-30')
    assert len(rows) == 1 and rows[0]['quadrant'] == 'REFLATION'
    first = {'points': [{'month': '2026-10', 'growth': -.1, 'inflation_change_pp': .1, 'inflation_yoy': 3.1}]}
    rows = update_ledger(rows, {'points': []}, first, '2026-11-25')
    revised = {'points': [{'month': '2026-10', 'growth': .3, 'inflation_change_pp': .1, 'inflation_yoy': 3.1}]}
    rows = update_ledger(rows, {'points': []}, revised, '2026-12-23')
    assert rows[0]['actual_quadrant'] == 'STAGFLATION'
    assert quadrant(0, .1) is None
