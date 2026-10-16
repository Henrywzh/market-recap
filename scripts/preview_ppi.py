"""Refresh only PPI for local preview; preserve CPI, other data and session dates."""

import json
from types import SimpleNamespace

from market_recap.config import ARTIFACT_DIR, load_config
from market_recap.panels import ppi
from market_recap.compute.inflation_releases import attach
from market_recap.util import BuildLog, write_json


def main():
    path = ARTIFACT_DIR / 'macro.json'
    original = path.read_text(encoding='utf-8')
    payload = json.loads(original)
    result = ppi.build(SimpleNamespace(config=load_config(), log=BuildLog()))
    # A concurrent refresh must not lose newly written unrelated macro data.
    if path.read_text(encoding='utf-8') != original:
        raise RuntimeError('Macro artifact changed during preview; retry without overwriting it')
    payload = attach({**payload, 'ppi': result}, payload)
    pending = path.with_suffix('.pending')
    write_json(pending, payload)
    pending.replace(path)
    print(json.dumps({'retained_macro_as_of': payload.get('as_of'), 'ppi_status': result['status'],
                      'ppi_month': result.get('month'), 'failed_sources': result.get('failed_sources', {}),
                      'reason': result.get('reason')}))


if __name__ == '__main__':
    main()
