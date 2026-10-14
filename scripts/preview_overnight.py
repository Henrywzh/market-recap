"""Build the missing local overnight artifact from cached bars; no fetches."""

import json

import pandas as pd

from market_recap.config import ARTIFACT_DIR, CACHE_DIR, load_config
from market_recap.panels.overnight import NOTES, _view
from market_recap.util import write_json


def main():
    as_of = json.loads((ARTIFACT_DIR / 'manifest.json').read_text())['as_of']
    cfg = load_config()['overnight']
    frames = []
    for field in ['closes', 'prices', 'open']:
        frame = pd.read_parquet(CACHE_DIR / f'prices/{field}-max.parquet')
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        frames.append(frame.loc[:as_of])
    views = [_view(spec, *frames, as_of, cfg['windows']) for spec in cfg['funds']]
    if not any(view['available'] for view in views):
        raise RuntimeError('No cached fund has both adjusted closes and raw opens/closes')
    result = {'as_of': as_of, 'settings': {'windows': cfg['windows']}, 'views': views,
              'notes': [*NOTES, 'Local preview rebuilt from existing cached bars only; no new source fetch.']}
    write_json(ARTIFACT_DIR / 'overnight.json', result)
    for view in views:
        print(view['symbol'], view.get('through'), view.get('sessions'), 'cached preview only')


if __name__ == '__main__':
    main()
