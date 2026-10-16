"""PPI release identity, denominator, NSA industries and no fabricated AI weights."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_recap.config import load_config
from market_recap.panels import ppi as P
from market_recap.sources import ppi as B
from market_recap.util import BuildLog


def release_html():
    rows = ''.join(f'<tr><th>{label}</th><td>FD</td><td>{code}</td><td>{weight}</td>'
                   '<td>5.0</td><td>0.5</td><td>0.1</td><td>0.2</td><td>0.3</td><td>0.7<sup>(p)</sup></td></tr>'
                   for label, code, weight in [('Final demand', '4', '100.000'),
                    ('Final demand less foods and energy ( 5 )', '49104', '89.487'),
                    ('Final demand less foods, energy, and trade services', '49116', '69.732')])
    return f'''<p>8:30 a.m. (ET) Thursday, October 15, 2026</p>
    <table id="ppi_nrtable1"><caption>Table 1. Producer price index, seasonally adjusted [September 2026]</caption>
    <thead><tr><th>Relative Importance Dec. 2025</th><th>Unadjusted 12-month percent change</th>
    <th>Seasonally adjusted 1-month percent change</th></tr></thead>
    <tbody><tr><th>Final Demand</th><td colspan="9"></td></tr>{rows}</tbody></table>'''


def test_official_ppi_weights_are_annual_reference_not_cpi_prior_month():
    out = B.parse(release_html())
    assert out['month'] == '2026-09' and out['weight_month'] == '2025-12'
    assert out['published_at'] == '2026-10-15T08:30:00-04:00'
    assert out['rows']['FD:49104']['official_label'] == 'Final demand less foods and energy'
    assert out['rows']['FD:4']['mom'] == .7
    assert out['rows']['FD:4']['previous_mom'] == .3
    assert out['rows']['FD:4']['yoy'] == 5.0
    assert all(r['effect_pp'] is None for r in out['rows'].values())


def test_ppi_parser_fails_closed_on_wrong_release_schema_and_duplicate_codes():
    with pytest.raises(ValueError, match='different publication'):
        B.parse(release_html(), expected_release=datetime(2026, 10, 16, 8, 30, tzinfo=ZoneInfo('America/New_York')))
    with pytest.raises(ValueError, match='schema changed'):
        B.parse(release_html().replace('Unadjusted 12-month percent change', 'Unspecified change'))
    with pytest.raises(ValueError, match='Duplicate'):
        B.parse(release_html().replace('<td>49104</td>', '<td>4</td>'))
    with pytest.raises(ValueError, match='required release'):
        B.parse(release_html().replace('0.7<sup>', '-<sup>'))
    with pytest.raises(ValueError, match='not before'):
        B.parse(release_html().replace('Dec. 2025', 'Dec. 2026'))
    with pytest.raises(ValueError, match='denominator'):
        B.parse(release_html().replace('100.000', '99.0'))
    assert B._number('0.0(p)') == 0
    assert B._number('(NA)') is None


def test_ppi_joins_only_the_correct_core_definition_day_month_and_country():
    release = B.parse(release_html())
    row = dict(country='US', date='2026-10-15T12:30:00Z', referenceDate='2026-09-30',
               title='Core PPI MoM', forecast=.4, previous=.2)
    matched = lambda rows: next(r for r in P.release_comparison(release, rows) if r['key'] == 'core_ppi_mom')
    assert matched([row])['surprise_pp'] == .3
    assert next(r for r in P.release_comparison(release, [row]) if r['key'] == 'ppi_mom')['consensus'] is None
    for bad in [{**row, 'title': 'PPI Ex Food Energy and Trade MoM'}, {**row, 'date': '2026-10-14'},
                {**row, 'country': 'CA'}, {**row, 'referenceDate': '2026-08-31'}]:
        assert matched([bad])['consensus'] is None
    assert matched([row, row])['consensus'] is None


def test_delayed_industry_stays_pending_and_does_not_borrow_last_month():
    spec = load_config()['macro']['ppi']['ai_series'][0]
    series = pd.Series([100, 102, 200], index=pd.to_datetime(['2026-06-01', '2026-08-01', '2026-10-01']))
    out = P.industry_row(spec, series, '2026-09', years=10, minimum=1)
    assert out['basis'] == 'NSA' and out['weight_pct'] is None and out['effect_pp'] is None
    assert out['status'] == 'pending' and out['latest_month'] == '2026-08'
    assert out['mom'] is None and out['yoy'] is None and out['latest_mom'] is None
    points = out['history']['observations']
    assert points[-1]['month'] == '2026-09' and points[-1]['index'] is None
    assert next(r for r in points if r['month'] == '2026-07')['mom'] is None
    assert not any(r['month'] == '2026-10' for r in points)


def test_industry_growth_uses_exact_calendar_periods():
    spec = load_config()['macro']['ppi']['ai_series'][0]
    series = pd.Series([100, 110, 121], index=pd.to_datetime(['2025-09-01', '2026-08-01', '2026-09-01']))
    out = P.industry_row(spec, series, '2026-09', years=10, minimum=1)
    assert out['mom'] == 10 and out['yoy'] == 21 and out['status'] == 'ok'
    assert out['history']['observations'][-1]['index'] == 121


def test_ppi_failure_named_and_independent_from_cpi(monkeypatch):
    monkeypatch.setattr(B, 'fetch_release', lambda: (_ for _ in ()).throw(ValueError('publisher schema changed')))
    log = BuildLog()
    assert P.build(SimpleNamespace(config=load_config(), log=log)) == {'status': 'unavailable', 'reason': 'publisher schema changed'}
    assert log.sources[0].status == 'error'


def test_partial_ppi_build_has_no_synthetic_ai_weighted_index(monkeypatch):
    release = B.parse(release_html())
    release.update(source_url='https://www.bls.gov/news.release/archives/ppi_10152026.htm',
                   retrieved_at='2026-10-15T14:00:00Z', sha256='test-only')
    monkeypatch.setattr(B, 'fetch_release', lambda: release)
    monkeypatch.setattr(P.expectations, 'fetch_tradingview', lambda *a: [])
    monkeypatch.setattr(P, '_series', lambda spec: (spec, None, 'temporarily unavailable'))
    out = P.build(SimpleNamespace(config=load_config(), log=BuildLog()))
    assert out['status'] == 'partial'
    assert len(out['ai_series']) == 5
    assert all(r['weight_pct'] is None and r['status'] == 'unavailable' for r in out['ai_series'])
    assert 'basket' not in out


def test_ppi_source_failures_are_optional_not_a_strict_publication_blocker():
    from market_recap.validate import OPTIONAL_SOURCES
    for name in ['bls_ppi', 'ppi_consensus', 'ppi_fred_pcu33443344', 'bls_cpi', 'cpi_consensus']:
        assert OPTIONAL_SOURCES.match(name)


def test_momentum_is_compounded_from_sa_levels_not_rounded_monthly_prints():
    spec = load_config()['macro']['ppi']['momentum'][0]
    values = pd.Series([100 * 1.002 ** n for n in range(8)], index=pd.date_range('2026-02-01', periods=8, freq='MS'))
    out = P.momentum_row(spec, values, '2026-09', years=10)
    expected = round((1.002 ** 12 - 1) * 100, 4)
    assert out['mom'] == .2 and out['ann_3m'] == expected and out['ann_6m'] == expected
    assert out['status'] == 'ok' and out['basis'] == 'SA'
    assert out['history']['observations'][-1]['ann_6m'] == expected


def test_momentum_gaps_endpoints_pending_future_and_nsa_are_not_filled():
    spec = load_config()['macro']['ppi']['momentum'][0]
    values = pd.Series(range(100, 108), index=pd.date_range('2026-02-01', periods=8, freq='MS'), dtype=float)
    gap = values.drop(pd.Timestamp('2026-07-01'))
    out = P.momentum_row(spec, gap, '2026-09', years=10)
    assert out['ann_3m'] is None and out['ann_6m'] is None
    assert out['mom'] is not None
    pending = P.momentum_row(spec, values.drop(pd.Timestamp('2026-08-01')), '2026-08', years=10)
    assert pending['status'] == 'pending' and pending['latest_month'] == '2026-07'
    assert pending['mom'] is None and pending['ann_3m'] is None
    assert pending['latest_ann_3m'] is not None
    assert pending['history']['observations'][-1]['month'] == '2026-08'
    with pytest.raises(ValueError, match='requires SA'):
        P.momentum_row({**spec, 'basis': 'NSA'}, values, '2026-09', years=10)
    with pytest.raises(ValueError, match='positive monthly'):
        P.momentum_row(spec, values * 0, '2026-09', years=10)
    with pytest.raises(ValueError, match='positive monthly'):
        P.momentum_row(spec, values.replace(100, float('inf')), '2026-09', years=10)


def test_momentum_missing_is_not_zero():
    spec = load_config()['macro']['ppi']['momentum'][0]
    out = P.momentum_row(spec, None, '2026-09', years=10)
    assert out['status'] == 'unavailable'
    assert out['mom'] is None and out['ann_3m'] is None and out['ann_6m'] is None


def _ppi_build(monkeypatch, fake_series, as_of=None):
    release = B.parse(release_html())
    release.update(source_url='https://www.bls.gov/news.release/archives/ppi_10152026.htm',
                   retrieved_at='2026-10-15T14:00:00Z', sha256='test-only')
    monkeypatch.setattr(B, 'fetch_release', lambda: release)
    monkeypatch.setattr(P.expectations, 'fetch_tradingview', lambda *a: [])
    monkeypatch.setattr(P, '_series', fake_series)
    ctx = SimpleNamespace(config=load_config(), log=BuildLog())
    if as_of:
        ctx.as_of = as_of
    return P.build(ctx), ctx


def test_one_bad_momentum_series_blanks_only_its_own_row(monkeypatch):
    good = pd.Series([100 * 1.002 ** n for n in range(8)], index=pd.date_range('2026-02-01', periods=8, freq='MS'))

    def fake(spec):
        if spec['key'] == 'ex_trade' and 'code' in spec:
            return spec, good * 0, None  # non-positive levels: momentum_row raises
        return spec, (good if 'code' in spec else None), None

    out, ctx = _ppi_build(monkeypatch, fake)
    rows = {r['key']: r for r in out['momentum']}
    assert rows['ex_trade']['status'] == 'unavailable' and rows['ex_trade']['mom'] is None
    assert 'positive monthly' in out['failed_sources']['WPSFD49116']
    assert rows['core_goods']['status'] == 'ok' and len(out['momentum']) == 4
    assert out['comparisons'] and len(out['ai_series']) == 5
    assert next(r for r in ctx.log.sources if r.source_id == 'ppi_fred_wpsfd49116').status == 'error'


def test_industry_pending_on_release_day_says_fred_posts_a_day_later(monkeypatch):
    stale = pd.Series([100, 101], index=pd.to_datetime(['2026-07-01', '2026-08-01']))
    fake = lambda spec: (spec, stale if 'detail' in spec else None, None)
    out, _ = _ppi_build(monkeypatch, fake, as_of='2026-10-15')
    assert out['ai_pending_expected'] is True
    assert {r['status'] for r in out['ai_series']} == {'pending'}
    assert all(out['failed_sources'][r['series_id']] == 'FRED usually posts these a day after BLS; last 2026-08'
               for r in out['ai_series'])
    # The flag outlives the shorter reason: day 3 still expects it, day 5 does not.
    out, _ = _ppi_build(monkeypatch, fake, as_of='2026-10-18')
    assert out['ai_pending_expected'] is True
    assert out['failed_sources'][out['ai_series'][0]['series_id']].startswith('pending 2026-09')
    out, _ = _ppi_build(monkeypatch, fake, as_of='2026-10-20')
    assert out['ai_pending_expected'] is False
    assert {r['status'] for r in out['ai_series']} == {'pending'}


def test_unexpected_ppi_error_becomes_a_named_gap_not_an_exception(monkeypatch):
    monkeypatch.setattr(P, 'release_comparison', lambda *a: (_ for _ in ()).throw(KeyError('FD:4')))
    release = B.parse(release_html())
    release.update(source_url='u', retrieved_at='2026-10-15T14:00:00Z', sha256='x')
    monkeypatch.setattr(B, 'fetch_release', lambda: release)
    monkeypatch.setattr(P.expectations, 'fetch_tradingview', lambda *a: [])
    ctx = SimpleNamespace(config=load_config(), log=BuildLog())
    out = P.build(ctx)
    assert out['status'] == 'unavailable' and 'FD:4' in out['reason']
    records = [r for r in ctx.log.sources if r.source_id == 'bls_ppi']
    assert [r.status for r in records] == ['error']
