"""Cleveland Fed nowcast_year.json -> long (target, asof, series, value)."""
import json, sys, pandas as pd
d = json.load(open(sys.argv[1])); rows = []
for block in d:
    y, m = map(int, block['chart']['subcaption'].split('-'))
    target = pd.Timestamp(y, m, 1)
    labels = [c['label'] for c in block['categories'][0]['category']]
    dates = []
    for lab in labels:
        try: mm, dd = map(int, lab.split('/'))
        except ValueError: dates.append(None); continue
        t = pd.Timestamp(y, mm, dd)
        if t < target - pd.Timedelta(days=60): t = pd.Timestamp(y + 1, mm, dd)
        dates.append(t)
    for s in block['dataset']:
        for t, pt in zip(dates, s['data']):
            v = pt.get('value')
            if t is None or v in (None, ''): continue
            rows.append((target, t, s['seriesname'], float(v)))
df = pd.DataFrame(rows, columns=['target', 'asof', 'series', 'value'])
df.to_parquet(sys.argv[2])
print(df.series.unique()); print(df.groupby('series').target.nunique())
g = df[df.series == 'Core PCE Inflation'].groupby('target').asof.agg(['min', 'max', 'count']); print(g.head(3)); print(g.tail(3))
