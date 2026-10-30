"""Month-end real-time growth/inflation quadrant, 2014+, for the Trade Desk's conditions.

Reads monthly_panel.parquet (evaluate.py). Growth: the ADS 3-month average as it
stood on t1 (first business day after the month), mapped onto the CFNAI-MA3 scale
by an expanding fit on first-release CFNAI-MA3 already published by t1 (ex-COVID,
>= 24 months); before that fit exists, raw ADS (0 = average growth). Inflation:
Cleveland's core PCE YoY nowcast on t1 minus the official YoY three months earlier
in the vintage of t1. The quadrant applies from the session after t1.
"""
import json, sys
import numpy as np
import pandas as pd

OUT, DEST = sys.argv[1], sys.argv[2]
COVID = (pd.Timestamp('2020-03-01'), pd.Timestamp('2021-06-01'))
df = pd.read_parquet(f'{OUT}/monthly_panel.parquet')
NAMES = {(1, 1): 'REFLATION', (1, -1): 'GOLDILOCKS', (-1, 1): 'STAGFLATION', (-1, -1): 'SLOWDOWN'}
rows = []
for _, r in df.iterrows():
    h = df[(df.cf_release < r.t1) & df.ads3.notna() & df.cf_actual.notna() & ~df.month.between(*COVID)]
    if len(h) >= 24:
        b, a = np.polyfit(h.ads3, h.cf_actual, 1); g, basis = a + b * r.ads3, 'ads_calibrated'
    else:
        g, basis = r.ads3, 'ads_raw'
    c = r.cle_chg_t1
    if pd.isna(g) or pd.isna(c) or g == 0 or c == 0:
        continue
    rows.append({'month': r.month.strftime('%Y-%m'), 'known': r.t1.strftime('%Y-%m-%d'), 'growth': round(float(g), 4),
                 'growth_basis': basis, 'inflation_change_pp': round(float(c), 4),
                 'quadrant': NAMES[(int(np.sign(g)), int(np.sign(c)))]})
doc = {'note': __doc__.strip(), 'rows': rows}
json.dump(doc, open(DEST, 'w'), indent=1)
q = pd.Series([r['quadrant'] for r in rows])
print(len(rows), rows[0]['month'], rows[-1]['month'], q.value_counts().to_dict(), sum(r['growth_basis'] == 'ads_raw' for r in rows))
print(rows[-3:])
