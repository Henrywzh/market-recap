"""Restore published release history before cloud builds; never use a TTL cache."""

import json
from pathlib import Path

from ..compute.inflation_releases import validate
from .http import get_text


def _checked(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('Published macro state is not an object')
    marked = payload.get('release_ledger_schema_version')
    if marked is not None and marked != 1:
        raise ValueError('Unsupported macro release ledger schema')
    for kind in ('cpi', 'ppi'):
        data = payload.get(kind, {})
        ledger = data.get('release_ledger')
        if ledger is not None:
            validate(ledger)
        elif marked:
            raise ValueError(f'{kind} release history missing; refusing to reset it')
    return payload


def load_previous(local_path: Path, *, published_base_url: str | None = None) -> dict:
    if published_base_url is None:
        return _checked(json.loads(local_path.read_text())) if local_path.exists() else {}
    base = published_base_url.rstrip('/') + '/artifacts/'
    def read(name):
        return json.loads(get_text(base + name, headers={'Cache-Control': 'no-cache'}, timeout=20, retries=1))
    before = read('manifest.json')
    payload = _checked(read('macro.json'))
    after = read('manifest.json')
    if not before.get('generated_at') or before.get('generated_at') != after.get('generated_at'):
        raise ValueError('Published macro changed during release-history restoration; retry the build')
    return payload
