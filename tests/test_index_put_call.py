"""Real-session gaps, precise source scope and authorized-import boundaries."""

from datetime import date
import json

import pandas as pd
import pytest

from market_recap.config import load_config
from market_recap.panels.index_put_call import PERMISSION_REASON, build_component, readings
from market_recap.sources import index_put_call as source
from market_recap.util import BuildLog
from market_recap.validate import OPTIONAL_SOURCES


def test_ratio_no_placeholder_zero_or_infinity():
    assert source.ratio(0, 100) == 0
    for puts, calls in [(0, 0), (10, 0), (-1, 1), (1, -1), (float('inf'), 1), (1, float('nan')), ('bad', 1)]:
        assert source.ratio(puts, calls) is None


def test_cache_uses_volume_not_open_interest_and_no_network(tmp_path, monkeypatch):
    monkeypatch.setattr(source.cache, 'path_for', lambda ns, name, suffix: tmp_path / f'{name}{suffix}')
    day = date(2026, 10, 8)
    path = tmp_path / 'putcall-2026-10-08.json'
    path.write_text(json.dumps({'S': [{'name': 'VOLUME', 'put': 300, 'call': 200},
                                     {'name': 'OPEN INTEREST', 'put': 1, 'call': 1000}]}))
    got = source.cached_cboe({'volume_key': 'S'}, [day, date(2026, 10, 9)])
    assert got.iloc[0] == 1.5 and pd.isna(got.iloc[1])
    path.write_text('{broken')
    assert source.cached_cboe({'volume_key': 'S'}, [day]).isna().all()


def test_missing_sessions_break_rolling_window_and_latest_is_not_stale():
    days = list(pd.bdate_range('2026-09-14', periods=8).date)
    raw = pd.Series([1., 2., 3., 4., 5., 6.], index=pd.DatetimeIndex(days[:6]))
    got = readings(raw, days, ['1D', '1W'])
    assert got['windows']['1W']['values'] == [None, None, None, None, 3., 4., None, None]
    assert got['windows']['1W']['values'][-1] is None
    assert got['windows']['1D']['values'][-1] is None
    assert got['coverage']['missing'] == 2
    assert got['coverage']['last'] == days[5].isoformat()
    raw = raw.drop(pd.Timestamp(days[2]))
    assert readings(raw, days, ['1W'])['windows']['1W']['observations'] == 0


def test_shared_month_definition_and_no_page_statistics_in_artifact():
    days = list(pd.bdate_range('2026-09-01', periods=21).date)
    raw = pd.Series(2., index=pd.DatetimeIndex(days))
    got = readings(raw, days, ['1M'])['windows']['1M']
    assert got['sessions'] == 21 and got['observations'] == 1
    assert got['values'][-1] == 2
    assert set(got) == {'sessions', 'values', 'observations'}


def test_permission_gate_runs_before_reading_private_file(tmp_path):
    spec = {'csv_path': str(tmp_path / 'does-not-exist'), 'underlying': 'NDX'}
    for allowed, reference in [(False, ''), (True, ''), (True, '   '), ('true', 'permission'), (False, 'permission')]:
        with pytest.raises(PermissionError):
            source.licensed_csv({**spec, 'publish_allowed': allowed, 'permission_reference': reference}, as_of=date(2026, 10, 8))


def test_authorized_import_filters_underlying_future_and_rejects_duplicates(tmp_path):
    path = tmp_path / 'authorized.csv'
    spec = {'csv_path': str(path), 'underlying': 'NDX', 'publish_allowed': True, 'permission_reference': 'test-only fixture'}
    path.write_text('date,underlying,put_volume,call_volume\n2026-10-08,NDX,30,10\n2026-10-09,NDX,90,10\n2026-10-08,QQQ,1,1\n')
    got = source.licensed_csv(spec, as_of=date(2026, 10, 8))
    assert list(got) == [3.] and len(got) == 1
    path.write_text('date,underlying,put_volume,call_volume\n2026-10-08,NDX,30,10\n2026-10-08,NDX,1,1\n')
    with pytest.raises(ValueError, match='Duplicate'):
        source.licensed_csv(spec, as_of=date(2026, 10, 8))
    path.write_text('date,underlying,put_volume,call_volume\n2026-10-08,NDX,30,0\n')
    with pytest.raises(ValueError, match='Invalid'):
        source.licensed_csv(spec, as_of=date(2026, 10, 8))


def test_component_uses_nyse_calendar_and_disables_unlicensed_ndx(monkeypatch):
    settings = load_config()['positioning']['index_put_call']
    settings = {**settings, 'sessions': 5}
    monkeypatch.setattr(source, 'cached_cboe', lambda spec, days: pd.Series(1.25, index=pd.DatetimeIndex(days)))
    log = BuildLog()
    got = build_component('2026-01-12', settings, log)
    assert '2026-01-10' not in got['series'][0]['dates']
    assert got['series'][0]['windows']['1W']['values'][-1] == 1.25
    # NDX is disabled, not shown as an unavailable column, and logs no source record.
    assert [row['key'] for row in got['series']] == ['spx']
    assert got['disabled'] == [{'key': 'ndx', 'label': 'NDX family', 'reason': PERMISSION_REASON}]
    assert all(OPTIONAL_SOURCES.match(r.source_id) for r in log.sources)
    assert 'index_put_call_ndx' not in [r.source_id for r in log.sources]
    # Carter closure and MLK holiday use the existing exchange calendar.
    got = build_component('2025-01-21', settings)
    assert '2025-01-20' not in got['series'][0]['dates']
    assert '2025-01-09' not in build_component('2025-01-10', settings)['series'][0]['dates']


def test_licensed_series_without_recorded_permission_is_disabled_before_any_read(tmp_path, monkeypatch):
    monkeypatch.setattr(source, 'cached_cboe', lambda spec, days: pd.Series(1.25, index=pd.DatetimeIndex(days)))
    spx = {'key': 'spx', 'label': 'SPX + SPXW', 'provider': 'cboe_cache', 'volume_key': 'SPX + SPXW',
           'source_label': 'Cboe', 'source_url': 'https://example.com/cboe', 'scope': 'SPX'}
    settings = {'sessions': 5, 'windows': ['1W'], 'default_window': '1W', 'series': [spx]}
    csv_path = tmp_path / 'ndx.csv'  # Deliberately absent: the gate must run before any file access.
    for allowed, reference in [(False, ''), (True, ''), (True, '  '), ('true', 'ref'), (False, 'ref')]:
        ndx = {'key': 'ndx', 'label': 'NDX family', 'provider': 'licensed_csv', 'underlying': 'NDX',
               'csv_path': str(csv_path), 'source_label': 'OCC', 'source_url': 'https://example.com/occ',
               'scope': 'NDX', 'publish_allowed': allowed, 'permission_reference': reference}
        log = BuildLog()
        got = build_component('2026-01-12', {**settings, 'series': [spx, ndx]}, log)
        assert [row['key'] for row in got['series']] == ['spx']
        assert got['disabled'] == [{'key': 'ndx', 'label': 'NDX family', 'reason': PERMISSION_REASON}]
        assert 'index_put_call_ndx' not in [r.source_id for r in log.sources]
    got = build_component('2026-01-12', settings)
    assert got['disabled'] == []
