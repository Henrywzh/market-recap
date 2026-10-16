"""Observed release versions, not reconstructed first prints or model vintages."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json

import pandas as pd

from ..util import ERROR_DETAIL_CHARS, clean_float, utc_now_iso

# Comparison fields BLS itself publishes. Consensus and the calendar's
# "previous" come from a third-party calendar and live beside the version.
_BLS_COMPARISON_KEYS = ('key', 'label', 'basis', 'actual', 'previous_mom_bls')


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _bls_values(values: dict) -> dict:
    """The BLS-only view of a record's values, for either digest version."""
    return {**values, 'comparisons': [{key: c.get(key) for key in _BLS_COMPARISON_KEYS}
                                      for c in values['comparisons']]}


def record_calendar(record: dict) -> list[dict]:
    """Consensus and calendar-previous per comparison; version-1 records kept them inside `values`."""
    if record.get('digest_version', 1) >= 2:
        return record.get('calendar', [])
    return [{key: c.get(key) for key in ('key', 'consensus', 'previous', 'source_url')}
            for c in record['values']['comparisons']]


def validate(ledger: dict) -> None:
    if not isinstance(ledger, dict) or ledger.get('schema_version') != 1 or not isinstance(ledger.get('records'), list):
        raise ValueError('Invalid inflation release ledger schema; refusing to reset history')
    previous = None
    for record in ledger['records']:
        for key in ('observed_at', 'last_checked_at', 'published_at'):
            stamp = datetime.fromisoformat(record[key])
            if stamp.tzinfo is None:
                raise ValueError('Inflation ledger timestamps must include timezone')
        if datetime.fromisoformat(record['last_checked_at']) < datetime.fromisoformat(record['observed_at']):
            raise ValueError('Inflation ledger observation order invalid')
        month = pd.Timestamp(record['month'])
        if month.strftime('%Y-%m') != record['month']:
            raise ValueError('Inflation ledger month invalid')
        if previous and datetime.fromisoformat(record['observed_at']) < datetime.fromisoformat(previous):
            raise ValueError('Inflation ledger is not chronological')
        previous = record['observed_at']
        if not isinstance(record['values'].get('components'), list) or not isinstance(record['values'].get('comparisons'), list):
            raise ValueError('Inflation ledger values missing')
        # Each record is checked against the digest rule it was written under.
        version = record.get('digest_version', 1)
        if version not in (1, 2):
            raise ValueError('Inflation ledger digest version unsupported')
        if version == 2 and not isinstance(record.get('calendar', []), list):
            raise ValueError('Inflation ledger calendar invalid')
        if record['value_sha256'] != _digest(record['values']):
            raise ValueError('Inflation ledger content digest mismatch')


def _refresh_calendar(record: dict, calendar: list[dict], fetched_at: str | None) -> None:
    """Update the calendar side of an unchanged version, as last_checked_at is.

    A check where the calendar returned nothing must not blank a consensus
    already stored: that is an outage, not a changed forecast.
    """
    has_new = any(c['consensus'] is not None for c in calendar)
    has_stored = any(c['consensus'] is not None for c in record_calendar(record))
    if has_new or not has_stored:
        record['calendar'] = calendar
        record['consensus_retrieved_at'] = fetched_at


def record_release(data: dict, previous: dict | None = None, *, now: str | None = None) -> dict:
    """Append only changed parsed values; never overwrite an earlier observation."""
    ledger = deepcopy(previous) if previous is not None else {'schema_version': 1, 'records': []}
    validate(ledger)
    if data.get('status') == 'unavailable':
        return ledger
    now = now or utc_now_iso()
    if ledger['records'] and datetime.fromisoformat(now) < datetime.fromisoformat(ledger['records'][-1]['last_checked_at']):
        raise ValueError('Inflation ledger clock moved backwards')
    if ledger['records'] and datetime.fromisoformat(data['published_at']) < datetime.fromisoformat(ledger['records'][-1]['published_at']):
        raise ValueError('Inflation source release moved backwards')
    values = {
        'weight_month': data['weight_month'],
        'components': [{key: r.get(key) for key in ('key', 'label', 'code', 'bls', 'mom', 'yoy',
                                                     'previous_mom', 'weight_pct', 'effect_pp')}
                       for r in data['components']],
        'comparisons': [{key: r.get(key) for key in _BLS_COMPARISON_KEYS} for r in data['comparisons']],
    }
    calendar = [{key: r.get(key) for key in ('key', 'consensus', 'previous', 'source_url')}
                for r in data['comparisons']]
    digest = _digest(values)
    latest = ledger['records'][-1] if ledger['records'] else None
    # A version changes only when BLS values do, so a version-1 record (digest
    # over consensus too) is matched on its BLS part and never rewritten.
    if latest and latest['published_at'] == data['published_at'] and _digest(_bls_values(latest['values'])) == digest:
        latest['last_checked_at'] = now
        if latest.get('digest_version', 1) >= 2:
            _refresh_calendar(latest, calendar, data.get('consensus_retrieved_at'))
    else:
        ledger['records'].append({
            'month': data['month'], 'published_at': data['published_at'], 'observed_at': now,
            'last_checked_at': now, 'source_url': data['source_url'],
            'source_sha256': data['source_sha256'], 'source_retrieved_at': data.get('retrieved_at'),
            'consensus_retrieved_at': data.get('consensus_retrieved_at'),
            'consensus_provenance': 'retrospective calendar; not verified pre-release',
            'digest_version': 2, 'value_sha256': digest, 'values': values, 'calendar': calendar,
        })
    validate(ledger)
    return ledger


def revision_rows(data: dict, ledger: dict) -> list[dict]:
    """Compare the new release's prior-month MoM to what we really observed."""
    if data.get('status') == 'unavailable':
        return []
    prior_month = (pd.Timestamp(data['month']) - pd.DateOffset(months=1)).strftime('%Y-%m')
    prior = [r for r in ledger['records'] if r['month'] == prior_month
             and datetime.fromisoformat(r['observed_at']) < datetime.fromisoformat(data['published_at'])]
    first = {r['key']: r for r in prior[0]['values']['components']} if prior else {}
    last = {r['key']: r for r in prior[-1]['values']['components']} if prior else {}
    rows = []
    for component in data.get('components', []):
        key = component['key']
        a, b, c = first.get(key, {}).get('mom'), last.get(key, {}).get('mom'), component.get('previous_mom')
        rows.append({'key': key, 'label': component['label'], 'month': prior_month,
                     'first_observed_mom': a, 'last_observed_mom': b, 'reported_prior_mom': c,
                     'revision_since_first_pp': clean_float(c - a, 4) if a is not None and c is not None else None,
                     'revision_since_last_pp': clean_float(c - b, 4) if b is not None and c is not None else None})
    return rows


def _keep_previous(data: dict, prior: dict | None, exc: Exception) -> None:
    """Fall back to the last good ledger for one kind, saying why; its data stays."""
    try:
        validate(prior)
        data['release_ledger'] = deepcopy(prior)
    except Exception:
        data.pop('release_ledger', None)
    data['revisions'] = []
    data['release_ledger_note'] = str(exc)[:ERROR_DETAIL_CHARS]


def attach(payload: dict, previous: dict, *, now: str | None = None) -> dict:
    """Same path for normal builds and partial local previews.

    Never raises: a ledger that cannot be extended (clock or release moved
    backwards, digest mismatch) must not take the macro artifact down with it.
    """
    now = now or utc_now_iso()
    for kind in ('cpi', 'ppi'):
        if kind not in payload:
            continue
        data = payload[kind]
        prior = previous.get(kind, {}).get('release_ledger')
        try:
            data['release_ledger'] = record_release(data, prior, now=now)
            data['revisions'] = revision_rows(data, data['release_ledger'])
        except Exception as exc:
            _keep_previous(data, prior, exc)
    payload['release_ledger_schema_version'] = 1
    return payload
