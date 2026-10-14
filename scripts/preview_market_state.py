"""Rebuild the local market-state artifact from cached data, keeping its date.

No HTTP, new market session, manifest update or deployment. Useful for
verifying label/method changes without a full nightly run.
"""

import json
from datetime import date

import pandas as pd

from market_recap.config import ARTIFACT_DIR, CACHE_DIR, load_config
from market_recap.panels.market_state import assemble
from market_recap.util import write_json


def main():
    config = load_config()
    path = ARTIFACT_DIR / 'market_state.json'
    as_of = date.fromisoformat(json.loads(path.read_text())['as_of'])
    cfg = config['market_state']
    closes = pd.read_parquet(CACHE_DIR / f"prices/closes-{int(cfg['history_years'])}y.parquet")
    result = assemble(as_of=as_of, closes=closes, sectors=config['universe']['sectors'],
                      market=config['universe']['market_proxy'], cfg=cfg)
    write_json(path, result)
    print(f"Local cached rebuild only: market_state as_of={result['as_of']}, prices_through={result['inputs']['prices_through']}")


if __name__ == '__main__':
    main()
