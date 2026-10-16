"""Durable observed releases: no fake first prints, resets or same-day lookahead."""

from copy import deepcopy
import json

import pytest

from market_recap.compute import inflation_releases as R
from market_recap.sources import inflation_state as S


def release(month='2026-08', published='2026-09-10T08:30:00-04:00', mom=.2, previous=.1):
    return {'status': 'ok', 'month': month, 'published_at': published,
            'source_url': 'https://www.bls.gov/example', 'source_sha256': 'raw-body-hash',
            'retrieved_at': '2026-09-10T13:00:00Z', 'weight_month': '2025-12',
            'consensus_retrieved_at': '2026-09-10T13:00:00Z',
            'components': [{'key': 'headline', 'label': 'Final demand', 'mom': mom, 'previous_mom': previous}],
            'comparisons': [{'key': 'ppi_mom', 'label': 'Headline', 'basis': 'MoM SA',
                             'actual': mom, 'consensus': .3, 'previous_mom_bls': previous}]}


def test_repeat_checks_are_idempotent_but_changed_values_append_and_never_overwrite():
    original = R.record_release(release(), now='2026-09-10T14:00:00Z')
    second = R.record_release(release(), original, now='2026-09-11T14:00:00Z')
    assert len(second['records']) == 1
    assert original['records'][0]['last_checked_at'] == '2026-09-10T14:00:00Z'
    assert second['records'][0]['observed_at'] == '2026-09-10T14:00:00Z'
    updated = release(mom=.4)
    third = R.record_release(updated, second, now='2026-09-12T14:00:00Z')
    assert len(third['records']) == 2
    assert third['records'][0]['values']['components'][0]['mom'] == .2
    assert third['records'][1]['values']['components'][0]['mom'] == .4
    # Source formatting/hash changes alone are not economic/calendar revisions.
    updated['source_sha256'] = 'formatting-only-change'
    assert len(R.record_release(updated, third, now='2026-09-13T14:00:00Z')['records']) == 2


def test_calendar_changes_refresh_in_place_and_only_bls_values_make_a_version():
    data = release()
    first = R.record_release(data, now='2026-09-10T14:00:00Z')
    record = first['records'][0]
    assert record['digest_version'] == 2
    assert 'consensus' not in record['values']['comparisons'][0]
    assert record['calendar'][0]['consensus'] == .3
    # A different consensus, and the calendar's fetch time, update the same version.
    data['comparisons'][0]['consensus'] = .4
    data['consensus_retrieved_at'] = '2026-09-11T13:00:00Z'
    second = R.record_release(data, first, now='2026-09-11T14:00:00Z')
    assert len(second['records']) == 1 and second['records'][0]['value_sha256'] == record['value_sha256']
    assert second['records'][0]['calendar'][0]['consensus'] == .4
    assert second['records'][0]['consensus_retrieved_at'] == '2026-09-11T13:00:00Z'
    assert R.record_calendar(second['records'][0])[0]['consensus'] == .4
    # A calendar outage must not blank a consensus we already stored.
    data['comparisons'][0]['consensus'] = None
    third = R.record_release(data, second, now='2026-09-12T14:00:00Z')
    assert len(third['records']) == 1 and third['records'][0]['calendar'][0]['consensus'] == .4
    assert all('not verified pre-release' in r['consensus_provenance'] for r in third['records'])
    tampered = deepcopy(third)
    tampered['records'][0]['values']['comparisons'][0]['actual'] = 9
    with pytest.raises(ValueError, match='digest'):
        R.validate(tampered)


def v1_ledger():
    """What the previous code wrote: digest over values that include consensus."""
    data = release()
    values = {'weight_month': data['weight_month'],
              'components': [{key: r.get(key) for key in ('key', 'label', 'code', 'bls', 'mom', 'yoy',
                                                          'previous_mom', 'weight_pct', 'effect_pp')}
                             for r in data['components']],
              'comparisons': [{key: r.get(key) for key in ('key', 'label', 'basis', 'actual', 'consensus',
                                                           'previous', 'previous_mom_bls', 'source_url')}
                              for r in data['comparisons']]}
    return {'schema_version': 1, 'records': [{
        'month': data['month'], 'published_at': data['published_at'], 'observed_at': '2026-09-10T14:00:00Z',
        'last_checked_at': '2026-09-10T14:00:00Z', 'source_url': data['source_url'],
        'source_sha256': 'raw', 'source_retrieved_at': None, 'consensus_retrieved_at': None,
        'consensus_provenance': 'retrospective calendar; not verified pre-release',
        'value_sha256': R._digest(values), 'values': values}]}


def test_records_written_by_the_old_digest_still_validate_and_are_never_rewritten():
    old = v1_ledger()
    R.validate(old)
    assert R.record_calendar(old['records'][0])[0]['consensus'] == .3
    before = deepcopy(old['records'][0])
    # Same BLS values, even with a different consensus: only last_checked_at moves.
    data = release()
    data['comparisons'][0]['consensus'] = .5
    again = R.record_release(data, old, now='2026-09-11T14:00:00Z')
    assert len(again['records']) == 1
    assert {k: v for k, v in again['records'][0].items() if k != 'last_checked_at'} == \
        {k: v for k, v in before.items() if k != 'last_checked_at'}
    # A BLS change appends a version-2 record after the untouched version-1 one.
    changed = R.record_release(release(mom=.4), old, now='2026-09-12T14:00:00Z')
    assert [r.get('digest_version', 1) for r in changed['records']] == [1, 2]
    assert changed['records'][0]['values'] == before['values']
    tampered = v1_ledger()
    tampered['records'][0]['values']['comparisons'][0]['consensus'] = .9
    with pytest.raises(ValueError, match='digest'):
        R.validate(tampered)


def test_revision_uses_only_observations_captured_before_the_new_release():
    data = release()
    ledger = R.record_release(data, now='2026-09-10T14:00:00Z')
    data['components'][0]['mom'] = .3
    ledger = R.record_release(data, ledger, now='2026-10-14T14:00:00Z')
    september = release('2026-09', '2026-10-15T08:30:00-04:00', mom=.7, previous=.4)
    row = R.revision_rows(september, ledger)[0]
    assert row['first_observed_mom'] == .2 and row['last_observed_mom'] == .3
    assert row['revision_since_first_pp'] == .2 and row['revision_since_last_pp'] == .1
    late = R.record_release(release(), now='2026-10-15T13:00:00Z')
    assert R.revision_rows(september, late)[0]['revision_since_first_pp'] is None
    # Same date but actually before 08:30 EDT; compare instants, not ISO strings.
    early = R.record_release(release(), now='2026-10-15T12:00:00Z')
    assert R.revision_rows(september, early)[0]['revision_since_first_pp'] == .2


def test_missing_release_preserves_history_and_new_month_is_not_backfilled():
    prior = R.record_release(release(), now='2026-09-10T14:00:00Z')
    assert R.record_release({'status': 'unavailable'}, prior) == prior
    current = release('2026-09', '2026-10-15T08:30:00-04:00')
    empty_prior = R.record_release(current, now='2026-10-15T14:00:00Z')
    assert len(empty_prior['records']) == 1
    assert R.revision_rows(current, empty_prior)[0]['revision_since_first_pp'] is None


def test_corrupt_schema_values_clock_and_release_rollbacks_are_rejected():
    prior = R.record_release(release(), now='2026-09-10T14:00:00Z')
    bad = deepcopy(prior)
    bad['records'][0]['values']['components'][0]['mom'] = 99
    with pytest.raises(ValueError, match='digest'):
        R.record_release(release(), bad)
    with pytest.raises(ValueError, match='schema'):
        R.record_release(release(), {'records': []})
    with pytest.raises(ValueError, match='clock'):
        R.record_release(release(), prior, now='2026-09-10T13:00:00Z')
    later = R.record_release(release('2026-09', '2026-10-15T08:30:00-04:00'), prior,
                             now='2026-10-15T14:00:00Z')
    with pytest.raises(ValueError, match='release moved backwards'):
        R.record_release(release(), later, now='2026-10-16T14:00:00Z')


def test_local_bootstrap_and_marked_history_must_not_silently_disappear(tmp_path):
    path = tmp_path / 'macro.json'
    assert S.load_previous(path) == {}
    path.write_text(json.dumps({'cpi': {'status': 'ok'}}))
    assert S.load_previous(path)['cpi']['status'] == 'ok'
    path.write_text(json.dumps({'release_ledger_schema_version': 1, 'cpi': {}, 'ppi': {}}))
    with pytest.raises(ValueError, match='history missing'):
        S.load_previous(path)
    first = R.attach({'cpi': release(), 'ppi': {'status': 'unavailable'}}, {}, now='2026-09-10T14:00:00Z')
    path.write_text(json.dumps(first))
    assert len(S.load_previous(path)['cpi']['release_ledger']['records']) == 1


def test_cloud_restore_uses_published_state_and_refuses_failure_or_deployment_race(monkeypatch, tmp_path):
    path = tmp_path / 'macro.json'
    path.write_text('{}')
    published = R.attach({'cpi': release(), 'ppi': release()}, {}, now='2026-09-10T14:00:00Z')
    replies = iter([{'generated_at': 'one'}, published, {'generated_at': 'one'}])
    monkeypatch.setattr(S, 'get_text', lambda *a, **k: json.dumps(next(replies)))
    assert S.load_previous(path, published_base_url='https://example.test') == published
    replies = iter([{'generated_at': 'one'}, published, {'generated_at': 'two'}])
    with pytest.raises(ValueError, match='changed during'):
        S.load_previous(path, published_base_url='https://example.test')
    monkeypatch.setattr(S, 'get_text', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('network unavailable')))
    with pytest.raises(RuntimeError, match='network unavailable'):
        S.load_previous(path, published_base_url='https://example.test')


def test_attach_never_raises_and_keeps_the_last_good_ledger_with_a_note():
    good = R.attach({'cpi': release(), 'ppi': release()}, {}, now='2026-09-10T14:00:00Z')
    # Clock moved backwards: data stays, the previous ledger is carried unchanged.
    out = R.attach({'cpi': release(mom=.4), 'ppi': {'status': 'unavailable'}}, good, now='2026-09-10T13:00:00Z')
    assert out['cpi']['release_ledger'] == good['cpi']['release_ledger']
    assert out['cpi']['components'][0]['mom'] == .4
    assert out['cpi']['revisions'] == [] and 'clock' in out['cpi']['release_ledger_note']
    assert 'release_ledger_note' not in out['ppi']
    # A corrupt previous ledger is omitted rather than carried.
    bad = deepcopy(good)
    bad['cpi']['release_ledger']['records'][0]['values']['components'][0]['mom'] = 99
    out = R.attach({'cpi': release()}, bad, now='2026-09-11T14:00:00Z')
    assert 'release_ledger' not in out['cpi'] and 'digest' in out['cpi']['release_ledger_note']
    # One kind failing leaves the other recording normally.
    mixed = R.attach({'cpi': release(), 'ppi': release()}, {'cpi': good['cpi'], 'ppi': good['ppi']},
                     now='2026-09-10T14:00:00Z')
    assert 'release_ledger_note' not in mixed['cpi'] and 'release_ledger_note' not in mixed['ppi']


def macro_build(monkeypatch):
    import pandas as pd
    from types import SimpleNamespace
    from market_recap import config
    from market_recap.panels import macro
    from market_recap.sources import fred, yahoo
    from market_recap.util import BuildLog

    index = pd.date_range('2025-01-01', periods=14, freq='MS')
    monkeypatch.setattr(fred, 'fetch_series', lambda sid, **_: (pd.DataFrame({'date': index, 'value': range(14)}), 'u'))
    monkeypatch.setattr(yahoo, 'fetch_closes', lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(macro.cpi, 'build', lambda ctx: release())
    monkeypatch.setattr(macro.ppi, 'build', lambda ctx: {'status': 'unavailable', 'reason': 'x'})
    ctx = SimpleNamespace(config=config.load_config(), as_of='2026-09-21', log=BuildLog())
    return macro, ctx


def test_macro_survives_a_failed_release_history_restore(monkeypatch):
    from market_recap.validate import OPTIONAL_SOURCES
    macro, ctx = macro_build(monkeypatch)
    for failure in (RuntimeError('network unavailable'), ValueError('Published macro changed during release-history restoration'),
                    json.JSONDecodeError('Expecting value', '<html>', 0)):
        ctx.log.sources.clear()
        monkeypatch.setattr(macro.inflation_state, 'load_previous', lambda *a, **k: (_ for _ in ()).throw(failure))
        payload = macro.build(ctx)
        assert payload['commodities']['rows']
        assert payload['inflation']['rows'] and len(payload['cpi']['release_ledger']['records']) == 1
        record = next(r for r in ctx.log.sources if r.source_id == 'cpi_fred_release_state')
        assert record.status == 'partial' and str(failure)[:20] in record.error
        assert OPTIONAL_SOURCES.match(record.source_id)
    # A clean restore logs nothing extra.
    ctx.log.sources.clear()
    monkeypatch.setattr(macro.inflation_state, 'load_previous', lambda *a, **k: {})
    macro.build(ctx)
    assert not any(r.source_id == 'cpi_fred_release_state' for r in ctx.log.sources)
