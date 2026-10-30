"""All ALFRED vintages for a few series -> parquet. Key read from market-recap's config, never printed."""
import sys, json, time, urllib.request, urllib.parse, pandas as pd
sys.path.insert(0, '/Users/henrywzh/Desktop/Quant/market-recap.nosync/src')
from market_recap.sources.alfred import api_key
KEY = api_key(); out = sys.argv[1]
SERIES = ['PCEPILFE', 'CFNAIMA3', 'CFNAI', 'A191RL1Q225SBEA', 'WEI', 'GDPNOW', 'STLENI']
for sid in SERIES:
    q = dict(series_id=sid, api_key=KEY, file_type='json', realtime_start='1776-07-04', realtime_end='9999-12-31',
             observation_start='2005-01-01', limit=100000)
    rows, offset = [], 0
    while True:
        q['offset'] = offset
        with urllib.request.urlopen('https://api.stlouisfed.org/fred/series/observations?' + urllib.parse.urlencode(q), timeout=120) as r:
            d = json.load(r)
        rows += d['observations']
        if len(d['observations']) < 100000: break
        offset += 100000
    df = pd.DataFrame(rows)
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    df.to_parquet(f'{out}/alfred_{sid}.parquet')
    print(sid, len(df), df.realtime_start.nunique(), 'vintages', df.realtime_start.min(), df.date.min(), df.date.max())
    time.sleep(1)
