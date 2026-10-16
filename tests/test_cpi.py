"""CPI release identity, units, non-overlapping attribution and missing months."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_recap.compute import cpi as C
from market_recap.config import load_config
from market_recap.panels import cpi as P
from market_recap.sources import cpi as B
from market_recap.util import BuildLog


def release_html(month="September", effect_month="September", *, published="October 14, 2026"):
    rows1 = ''.join(f'<tr><th>{label}</th><td>100</td><td>300</td><td>310</td><td>311</td>'
                    '<td>3.7</td><td>0.6</td><td>0.1</td><td>0.4</td><td>0.6</td></tr>'
                    for label in ['All items', 'All items less food and energy', 'Food', 'Energy'])
    rows6 = ''.join(f'<tr><th>{label}<sup>(1)</sup></th><td>{weight}</td><td>{mom}</td>'
                    f'<td>{effect}</td><td>0.04</td><td>-</td><td>-</td></tr>'
                    for label, weight, mom, effect in [
                        ('All items', 100, .6, '-'), ('Food', 13.5, 0, .006),
                        ('Energy', 7.4, 5.2, .377), ('All items less food and energy', 79.1, .3, .265)])
    return f'''<html><body><p>8:30 a.m. (ET) Wednesday, {published}</p>
    <table id="cpipress1"><caption>Table 1. CPI, {month} 2026</caption>
    <thead><tr><th>Relative importance Aug. 2026</th><th>Unadjusted percent change</th>
    <th>Seasonally adjusted percent change</th></tr></thead><tbody>{rows1}</tbody></table>
    <table id="cpipress6"><caption>Table 6. CPI, {effect_month} 2026, 1-month analysis table</caption>
    <thead><tr><th>Relative importance Aug. 2026</th><th>Seasonally adjusted percent change</th>
    <th>Seasonally adjusted effect on All Items</th></tr></thead>
    <tbody>{rows6}<tr><th>Special aggregate indexes</th><td colspan="6"></td></tr></tbody></table></body></html>'''


def test_release_keeps_official_effects_and_footnote_free_labels():
    out = B.parse(release_html())
    assert out['month'] == '2026-09' and out['weight_month'] == '2026-08'
    assert out['rows']['All items']['effect_pp'] is None
    assert out['rows']['Energy']['effect_pp'] == .377
    assert out['rows']['All items']['yoy'] == 3.7
    assert out['rows']['All items']['previous_mom'] == .4
    assert 'Special aggregate indexes' not in out['rows']


def test_cpi_publication_uses_eastern_dst_not_fixed_utc():
    assert B.parse(release_html())['published_at'] == '2026-10-14T08:30:00-04:00'
    assert B.release_time('8:30 a.m. (ET) Tuesday, January 13, 2026').utcoffset().total_seconds() == -5 * 3600


def test_old_month_200_cannot_masquerade_as_new_release():
    with pytest.raises(ValueError, match='different publication'):
        B.parse(release_html(), expected_release=datetime(2026, 11, 10, 8, 30, tzinfo=ZoneInfo('America/New_York')))
    with pytest.raises(ValueError, match='reference months disagree'):
        B.parse(release_html(effect_month='August'))
    with pytest.raises(ValueError, match='preceding month'):
        B.parse(release_html(month='August', effect_month='August'))


def test_schema_changes_fail_closed_and_sentinels_stay_null():
    with pytest.raises(ValueError, match='schema changed'):
        B.parse(release_html().replace('Seasonally adjusted effect on All Items', 'Other field'))
    assert B._number('-') is None
    assert B._number('0.000') == 0
    assert B._number('1,234.5') == 1234.5
    assert 'Food' in B.parse(release_html().replace('Food<sup>', 'Food ( 17 )<sup>'))['rows']


def test_history_retains_blank_months_instead_of_connecting_across_them():
    series = pd.Series([100, 102], index=pd.to_datetime(['2026-01-01', '2026-03-01']))
    assert P._history(series, 1) == {'dates': ['2026-01-01', '2026-02-01', '2026-03-01'],
                                      'values': [100.0, None, 102.0]}


def test_forecast_join_requires_date_month_and_exact_metric():
    release = B.parse(release_html())
    row = dict(country='US', date='2026-10-14T12:30:00Z', referenceDate='2026-09-30T00:00:00Z',
               title='Core Inflation Rate MoM', forecast=.2, previous=.3)
    out = P.release_comparison(release, [row])
    core = next(r for r in out if r['key'] == 'core_cpi_mom')
    assert core['consensus'] == .2 and core['surprise_pp'] == .1
    assert 'retrospective' in core['consensus_provenance']
    assert next(r for r in out if r['key'] == 'cpi_mom')['consensus'] is None
    for bad in [{**row, 'country': 'CA'}, {**row, 'referenceDate': '2026-08-31'}, {**row, 'date': '2026-10-13'}, {**row, 'title': 'Core Inflation Rate YoY'}]:
        assert next(r for r in P.release_comparison(release, [bad]) if r['key'] == 'core_cpi_mom')['consensus'] is None
    assert next(r for r in P.release_comparison(release, [row, row]) if r['key'] == 'core_cpi_mom')['consensus'] is None


def test_annualized_requires_all_calendar_months():
    index = pd.Series([100, 101, 102, 103, 104], index=pd.date_range('2025-07-01', periods=5, freq='MS'))
    assert C.annualized(index, 3).loc['2025-10-01'] == pytest.approx(((103 / 100) ** 4 - 1) * 100)
    missing = index.drop(pd.Timestamp('2025-09-01'))
    assert pd.isna(C.annualized(missing, 3).loc['2025-10-01'])


def test_percentiles_and_bands_do_not_look_forward_or_hide_gaps():
    index = pd.Series([100, 101, 102, 103, 104, 105], index=pd.date_range('2026-01-01', periods=6, freq='MS'))
    before = C.component_history(index, years=10, minimum=3)['observations']
    changed = index.copy()
    changed.iloc[-1] = 1000
    after = C.component_history(changed, years=10, minimum=3)['observations']
    assert before[:-1] == after[:-1]
    assert before[1]['percentile'] is None
    assert before[-1]['prior_n'] == 4
    assert before[-1]['p90'] < 1.01
    missing = C.component_history(index.drop(pd.Timestamp('2026-03-01')), years=10, minimum=1)['observations']
    assert next(r for r in missing if r['month'] == '2026-04')['mom'] is None


def test_release_failure_is_named_gap_not_a_model_or_zero(monkeypatch):
    monkeypatch.setattr(B, 'fetch_release', lambda: (_ for _ in ()).throw(ValueError('schema changed')))
    log = BuildLog()
    out = P.build(SimpleNamespace(config=load_config(), log=log))
    assert out == {'status': 'unavailable', 'reason': 'schema changed'}
    assert log.sources[0].status == 'error'


def test_delayed_or_missing_series_are_pending_not_borrowed(monkeypatch):
    release = B.parse(release_html())
    release.update(source_url='https://www.bls.gov/news.release/archives/cpi_10142026.htm',
                   retrieved_at='2026-10-15T14:00:00+00:00', sha256='test-only')
    monkeypatch.setattr(B, 'fetch_release', lambda: release)
    monkeypatch.setattr(P.expectations, 'fetch_tradingview', lambda *a: [])
    config = load_config()

    def source(spec):
        if spec['key'] == 'core':
            return spec, None, 'not published'
        return spec, pd.Series([2.5], index=pd.to_datetime(['2026-08-01'])), None

    monkeypatch.setattr(P, '_series', source)
    out = P.build(SimpleNamespace(config=config, log=BuildLog()))
    assert len(out['persistence']) == 6
    assert all(r['status'] == 'pending' and r['value'] is None for r in out['persistence'])
    sticky = next(r for r in out['persistence'] if r['key'] == 'sticky')
    assert sticky['latest_value'] == 2.5 and sticky['latest_month'] == '2026-08'
    assert all(r['consensus'] is None for r in out['comparisons'])
    assert out['contributions']['sum_pp'] == pytest.approx(.648)
    assert out['contributions']['residual_pp'] == -.048


def test_contract_uses_nsa_year_on_year_and_nonoverlapping_partition():
    config = load_config()
    cpi = next(r for r in config['catalysts']['releases'] if r['label'] == 'CPI')
    assert [p['series'] for p in cpi['prints']] == ['CPIAUCNS', 'CPILFENS']
    assert config['macro']['cpi']['contribution_keys'] == ['food', 'energy', 'core']
    assert len({r['key'] for r in config['macro']['cpi']['components']}) == len(config['macro']['cpi']['components'])


def test_contribution_reports_the_unrounded_headline_index_change(monkeypatch):
    release = B.parse(release_html())
    release.update(source_url='https://www.bls.gov/news.release/archives/cpi_10142026.htm',
                   retrieved_at='2026-10-15T14:00:00+00:00', sha256='test-only')
    monkeypatch.setattr(B, 'fetch_release', lambda: release)
    monkeypatch.setattr(P.expectations, 'fetch_tradingview', lambda *a: [])
    monkeypatch.setattr(P, '_series', lambda spec: (spec, pd.Series(
        [100, 100.5], index=pd.to_datetime(['2026-08-01', '2026-09-01'])), None))
    out = P.build(SimpleNamespace(config=load_config(), log=BuildLog()))
    contributions = out['contributions']
    assert contributions['headline_mom'] == .6 and contributions['residual_pp'] == -.048
    assert contributions['headline_mom_index'] == .5
    assert contributions['residual_index_pp'] == pytest.approx(-.148)


def test_unexpected_cpi_error_becomes_a_named_gap_not_an_exception(monkeypatch):
    release = B.parse(release_html())
    release.update(source_url='u', retrieved_at='2026-10-15T14:00:00+00:00', sha256='x')
    monkeypatch.setattr(B, 'fetch_release', lambda: release)
    monkeypatch.setattr(P.expectations, 'fetch_tradingview', lambda *a: [])
    monkeypatch.setattr(P, 'release_comparison', lambda *a: (_ for _ in ()).throw(KeyError('All items')))
    log = BuildLog()
    out = P.build(SimpleNamespace(config=load_config(), log=log))
    assert out['status'] == 'unavailable' and 'All items' in out['reason']
    # The earlier ok record of the same failed build is replaced, not left beside it.
    assert [r.status for r in log.sources if r.source_id == 'bls_cpi'] == ['error']
