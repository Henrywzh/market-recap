"""ADS all-vintages workbook -> long parquet (vintage, date, value), dates >= 2005."""
import sys, openpyxl, pandas as pd, numpy as np
src, out = sys.argv[1], sys.argv[2]
ws = openpyxl.load_workbook(src, read_only=True)['Sheet1']
rows = ws.iter_rows(values_only=True)
header = next(rows)
vint = pd.to_datetime([h.split('_')[-1] for h in header[1:]], format='%m%d%y')
dates, vals = [], []
for r in rows:
    if r[0] is None or r[0] < '2005': continue
    dates.append(r[0]); vals.append(np.array([np.nan if v is None else float(v) for v in r[1:]], dtype='float32'))
mat = np.vstack(vals)
df = pd.DataFrame(mat, index=pd.to_datetime(dates, format='%Y:%m:%d'), columns=vint)
long = df.stack().rename('value').reset_index().rename(columns={'level_0': 'date', 'level_1': 'vintage'})
long.to_parquet(out)
print(len(vint), vint.min(), vint.max(), long.shape)
