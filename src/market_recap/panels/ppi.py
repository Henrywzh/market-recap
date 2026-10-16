"""PPI release and AI-related industry prices, not an AI-demand model."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import math
import re

import pandas as pd

from .. import cache
from ..compute import cpi as C, periods
from ..sources import ppi as bls, expectations
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float
from .cpi import _series, unavailable


def release_comparison(release: dict, calendar: list[dict]) -> list[dict]:
    rows = []
    for key, code, label in (('ppi', 'FD:4', 'Headline'), ('core_ppi', 'FD:49104', 'Core · ex food & energy')):
        for basis in ('mom', 'yoy'):
            pattern = rf"^{('core ' if key == 'core_ppi' else '')}ppi {basis}$"
            matches = [r for r in calendar if r.get('country') == 'US'
                       and str(r.get('date', ''))[:10] == release['published_at'][:10]
                       and str(r.get('referenceDate', ''))[:7] == release['month']
                       and re.search(pattern, r.get('title', ''), re.I)]
            raw = matches[0] if len(matches) == 1 else {}
            actual = release['rows'][code][basis]
            forecast = clean_float(raw.get('forecast'), 4)
            rows.append({'key': f'{key}_{basis}', 'label': label,
                         'basis': 'MoM SA' if basis == 'mom' else 'YoY NSA',
                         'actual': actual, 'consensus': forecast,
                         'surprise_pp': clean_float(actual - forecast, 4) if forecast is not None else None,
                         'previous': clean_float(raw.get('previous'), 4),
                         'previous_mom_bls': release['rows'][code]['previous_mom'] if basis == 'mom' else None,
                         'source_url': 'https://www.tradingview.com/economic-calendar/',
                         'consensus_provenance': 'retrospective calendar; not a frozen pre-release snapshot'})
    return rows


def blank_industry(spec: dict, month: str) -> dict:
    return {**spec, 'source_url': f"https://fred.stlouisfed.org/series/{spec['series_id']}",
            'basis': 'NSA', 'weight_pct': None, 'effect_pp': None,
            'month': month, 'status': 'unavailable', 'latest_month': None,
            'mom': None, 'yoy': None, 'latest_mom': None, 'latest_yoy': None,
            'history': {'observations': []}}


def blank_momentum(spec: dict, month: str) -> dict:
    return {**spec, 'source_url': f"https://fred.stlouisfed.org/series/{spec['series_id']}",
            'month': month, 'latest_month': None, 'status': 'unavailable',
            'mom': None, 'ann_3m': None, 'ann_6m': None,
            'latest_mom': None, 'latest_ann_3m': None, 'latest_ann_6m': None,
            'history': {'observations': []}}


def industry_row(spec: dict, series: pd.Series | None, month: str, *, years: int, minimum: int) -> dict:
    """Exact monthly comparisons, no carry-forward across unavailable periods."""
    row = blank_industry(spec, month)
    if series is None or series.empty:
        return row
    series = series.loc[series.index <= pd.Timestamp(month)].dropna().sort_index()
    if series.empty:
        return row
    full = series.reindex(pd.date_range(series.index.min(), pd.Timestamp(month), freq='MS'))
    growth = periods.transform(full, 'yoy')
    obs = C.component_history(full.loc[full.index >= pd.Timestamp(month) - pd.DateOffset(years=2 * years)],
                              years=years, minimum=minimum)['observations']
    cutoff = (pd.Timestamp(month) - pd.DateOffset(years=years)).strftime('%Y-%m')
    indexed = {r['month']: r for r in obs}
    for point in obs:
        stamp = pd.Timestamp(point['month'])
        point['yoy'] = clean_float(growth.get(stamp), 4)
        point['index'] = clean_float(full.get(stamp), 4)
    latest = series.dropna().index[-1].strftime('%Y-%m')
    current, last = indexed.get(month, {}), indexed.get(latest, {})
    row.update(status='ok' if latest == month else 'pending', latest_month=latest,
               mom=current.get('mom'), yoy=current.get('yoy'),
               latest_mom=last.get('mom'), latest_yoy=last.get('yoy'),
               history={'observations': [r for r in obs if r['month'] >= cutoff]})
    return row


def momentum_row(spec: dict, series: pd.Series | None, month: str, *, years: int) -> dict:
    """Current-vintage SA momentum, independently dated from the release."""
    if spec.get('basis') != 'SA':
        raise ValueError('PPI short-term annualized momentum requires SA index levels')
    row = blank_momentum(spec, month)
    if series is None or series.empty:
        return row
    series = series.loc[series.index <= pd.Timestamp(month)].dropna().sort_index()
    if series.empty:
        return row
    if (series.index.has_duplicates or not series.index.is_month_start.all()
            or (series <= 0).any() or not series.map(math.isfinite).all()):
        raise ValueError('PPI momentum requires unique positive monthly index levels')
    full = series.reindex(pd.date_range(series.index.min(), pd.Timestamp(month), freq='MS'))
    values = {'mom': periods.transform(full, 'mom'), 'ann_3m': C.annualized(full, 3),
              'ann_6m': C.annualized(full, 6)}
    latest = series.index[-1]
    current = pd.Timestamp(month)
    for key, reading in values.items():
        row[key] = clean_float(reading.get(current), 4)
        row[f'latest_{key}'] = clean_float(reading.get(latest), 4)
    cutoff = current - pd.DateOffset(years=years)
    row.update(latest_month=latest.strftime('%Y-%m'), status='ok' if latest == current else 'pending',
               history={'observations': [{'month': stamp.strftime('%Y-%m'),
                                          **{key: clean_float(reading.get(stamp), 4)
                                             for key, reading in values.items()}}
                                         for stamp in full.index if stamp >= cutoff]})
    return row


def days_from_release(ctx, published_at: str) -> int:
    """Build date minus release date. ctx.as_of is the last close, so it can sit a day before the release."""
    published = datetime.fromisoformat(published_at)
    build_date = date.fromisoformat(ctx.as_of) if getattr(ctx, 'as_of', None) else datetime.now(published.tzinfo).date()
    return (build_date - published.date()).days


def build(ctx) -> dict:
    # Runs inside macro.build; a failure there publishes no macro.json at all,
    # so nothing on the PPI side may escape as an exception.
    try:
        return _build(ctx)
    except Exception as exc:
        return unavailable(ctx, 'bls_ppi', 'BLS PPI release', bls.LATEST_URL, exc)


def _build(ctx) -> dict:
    config = ctx.config['macro']['ppi']
    failed = {}
    release = bls.fetch_release()
    ctx.log.add(SourceRecord('bls_ppi', 'BLS PPI final-demand release and relative importance',
                             release['source_url'], release['month'] + '-01', rows=len(release['rows']),
                             policy='monthly_release'))
    day = datetime.fromisoformat(release['published_at']).date()
    try:
        calendar = expectations.fetch_tradingview(day, day)
        path = cache.path_for(expectations.NAMESPACE, f'tradingview-{day}-{day}', '.json')
        modified = cache.modified(path)
        retrieved = modified.isoformat() if modified else None
        note = None
    except Exception as exc:
        calendar, retrieved, note = [], None, str(exc)[:ERROR_DETAIL_CHARS]
    comparisons = release_comparison(release, calendar)
    ctx.log.add(SourceRecord('ppi_consensus', 'TradingView PPI calendar forecast (retrospective)',
                             'https://www.tradingview.com/economic-calendar/', day.isoformat(),
                             rows=sum(r['consensus'] is not None for r in comparisons),
                             status='ok' if all(r['consensus'] is not None for r in comparisons) else 'partial',
                             error=note, policy='monthly_release'))
    components = []
    for spec in config['components']:
        official = release['rows'].get(spec['code'], {})
        if not official:
            failed[spec['code']] = 'category absent from official release'
        components.append({**spec, **official})
    industry, momentum = [], []
    since_release = days_from_release(ctx, release['published_at'])
    with ThreadPoolExecutor(max_workers=3) as pool:
        for spec, series, error in pool.map(_series, config['momentum'] + config['ai_series']):
            is_momentum = spec in config['momentum']
            # One series with unusable levels (duplicates, non-positive) blanks
            # only its own row; the release and the other rows still build.
            try:
                if is_momentum:
                    row = momentum_row(spec, series, release['month'], years=config['history_years'])
                else:
                    row = industry_row(spec, series, release['month'], years=config['history_years'],
                                       minimum=config['percentile_min_months'])
            except Exception as exc:
                row = (blank_momentum if is_momentum else blank_industry)(spec, release['month'])
                error = error or str(exc)[:ERROR_DETAIL_CHARS]
            if is_momentum:
                row['release_mom'] = release['rows'].get(spec['code'], {}).get('mom')
            if row['status'] != 'ok':
                last = row['latest_month'] or 'unavailable'
                if row['status'] == 'pending' and not is_momentum and abs(since_release) <= 1:
                    # Normal lag, not a fault: FRED posts the industry series after BLS.
                    reason = f'FRED usually posts these a day after BLS; last {last}'
                else:
                    reason = f"pending {release['month']}; last {last}"
                failed[spec['series_id']] = error or reason
            path = cache.path_for('fred', spec['series_id'], '.csv')
            modified = cache.modified(path)
            row['retrieved_at'] = modified.isoformat() if modified else None
            (momentum if is_momentum else industry).append(row)
            ctx.log.add(SourceRecord(f"ppi_fred_{spec['series_id'].lower()}", spec['label'], row['source_url'],
                                     row['latest_month'] + '-01' if row['latest_month'] else None,
                                     rows=len(row['history']['observations']),
                                     status='ok' if row['status'] == 'ok' else 'partial' if row['status'] == 'pending' else 'error',
                                     error=failed.get(spec['series_id']), policy='monthly_release'))
    return {'status': 'partial' if failed else 'ok', 'month': release['month'],
            'published_at': release['published_at'], 'source_url': release['source_url'],
            'retrieved_at': release['retrieved_at'], 'source_sha256': release['sha256'],
            'weight_month': release['weight_month'], 'comparisons': comparisons, 'components': components,
            'ai_series': industry, 'momentum': momentum, 'failed_sources': failed, 'consensus_note': note,
            'ai_pending_expected': abs(since_release) <= 3,
            'consensus_retrieved_at': retrieved,
            'refresh_note': 'Updated by dashboard builds, not a live release-window service.',
            'note': 'Official PPI release rates can be preliminary and later revised. FRED industry histories are current vintage and NSA. '
                    'The five AI-related categories match alternative-data observation targets, not its custom weighted proxy. '
                    'They cover broad industries, not AI-only output, and price changes do not identify demand or sales volume. '
                    'No industry final-demand weights, official effects, consensus, synthetic basket or prediction model are supplied.'}
