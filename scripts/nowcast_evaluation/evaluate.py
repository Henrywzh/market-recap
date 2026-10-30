"""Real-time comparison of growth and inflation nowcasts for the regime map.

Every candidate is read as it stood on the evaluation date (its own vintage);
every target is the first official release, with YoY and 3M changes computed
inside that release's vintage. Calibrations are expanding and use only targets
already released by the evaluation date.
"""
import sys
import numpy as np
import pandas as pd

RAW = sys.argv[1]
OUT = sys.argv[2]
COVID = (pd.Timestamp('2020-03-01'), pd.Timestamp('2021-06-01'))


def alfred(sid):
    df = pd.read_parquet(f'{RAW}/alfred_{sid}.parquet')
    df['date'] = pd.to_datetime(df.date)
    df['rs'] = pd.to_datetime(df.realtime_start)
    df['re'] = pd.to_datetime(df.realtime_end.replace('9999-12-31', '2262-01-01'))
    return df.dropna(subset=['value'])


def vintage(df, t):
    v = df[(df.rs <= t) & (df.re >= t)]
    return v.set_index('date').value.sort_index()


def release(df, d):
    r = df[df.date == d].rs
    return r.min() if len(r) else pd.NaT


PCE, CF, GDP = alfred('PCEPILFE'), alfred('CFNAIMA3'), alfred('A191RL1Q225SBEA')
WEI, GNOW, ENI = alfred('WEI'), alfred('GDPNOW'), alfred('STLENI')
ads = pd.read_parquet(f'{RAW}/ads_vintages.parquet')
ADS_V = np.sort(ads.vintage.unique())
cle = pd.read_parquet(f'{RAW}/cle_year.parquet')
CLE = cle[cle.series == 'Core PCE Inflation'].sort_values('asof')


def yoy(s, m):
    a, b = s.get(m), s.get(m - pd.DateOffset(years=1))
    return 100 * (a / b - 1) if a is not None and b is not None and np.isfinite(a) and np.isfinite(b) else np.nan


def ads_window(t, start, end):
    i = np.searchsorted(ADS_V, np.datetime64(t), side='right') - 1
    if i < 0:
        return np.nan
    v = ads[ads.vintage == ADS_V[i]]
    w = v[(v.date >= start) & (v.date < end)]
    return w.value.mean() if len(w) else np.nan


def latest_le(df, t, d):
    v = df[(df.date == d) & (df.rs <= t)]
    return v.sort_values('rs').value.iloc[-1] if len(v) else np.nan


rows = []
months = pd.date_range('2014-01-01', '2026-09-01', freq='MS')
for m in months:
    rel_p, rel_c = release(PCE, m), release(CF, m)
    t1 = m + pd.offsets.MonthBegin(1) + pd.offsets.BDay(0)          # first business day after month m
    row = {'month': m, 't1': t1}
    # --- inflation target: first-release core PCE YoY and its 3M change, same vintage
    if pd.notna(rel_p):
        s = vintage(PCE, rel_p)
        row['pce_yoy'] = yoy(s, m)
        row['pce_chg'] = row['pce_yoy'] - yoy(s, m - pd.DateOffset(months=3))
    for tag, t in (('t1', t1), ('pre', rel_p - pd.Timedelta(days=1) if pd.notna(rel_p) else pd.NaT)):
        if pd.isna(t):
            continue
        s = vintage(PCE, t)
        last = s.index.max()
        base = yoy(s, m - pd.DateOffset(months=3))
        row[f'naive_yoy_{tag}'] = yoy(s, last)
        row[f'naive_chg_{tag}'] = yoy(s, last) - yoy(s, last - pd.DateOffset(months=3))
        row[f'lag_{tag}'] = (m.year - last.year) * 12 + m.month - last.month
        c = CLE[(CLE.target == m) & (CLE['asof'] <= t)]
        if len(c):
            row[f'cle_yoy_{tag}'] = c.value.iloc[-1]
            row[f'cle_chg_{tag}'] = c.value.iloc[-1] - base
    # --- growth target: first-release CFNAI-MA3
    if pd.notna(rel_c):
        row['cf_actual'] = vintage(CF, rel_c).get(m, np.nan)
    s = vintage(CF, t1)
    row['cf_naive'] = s.iloc[-1] if len(s) else np.nan
    row['cf_lag'] = (m.year - s.index.max().year) * 12 + m.month - s.index.max().month if len(s) else np.nan
    start = m - pd.DateOffset(months=2)
    row['ads3'] = ads_window(t1, start, m + pd.offsets.MonthBegin(1))
    w = vintage(WEI, t1)
    w = w[(w.index >= start) & (w.index < m + pd.offsets.MonthBegin(1))]
    row['wei3'] = w.mean() if len(w) and t1 >= WEI.rs.min() else np.nan
    q = m.to_period('Q').start_time
    row['gdpnow'] = latest_le(GNOW, t1, q)
    row['eni'] = latest_le(ENI, t1, q)
    row['cf_release'] = rel_c
    rows.append(row)

df = pd.DataFrame(rows)
df.to_parquet(f'{OUT}/monthly_panel.parquet')


def calibrated(df, col):
    """Expanding OLS of first-release CFNAI-MA3 on ``col``; only targets released by t1."""
    pred = []
    for _, r in df.iterrows():
        h = df[(df.cf_release < r.t1) & df[col].notna() & df.cf_actual.notna()]
        h = h[~h.month.between(*COVID)]
        if len(h) < 24 or pd.isna(r[col]):
            pred.append(np.nan); continue
        b, a = np.polyfit(h[col], h.cf_actual, 1)
        pred.append(a + b * r[col])
    return pd.Series(pred, index=df.index)


for col in ('ads3', 'wei3', 'gdpnow', 'eni'):
    df[f'{col}_cal'] = calibrated(df, col)


def score(sub, pred, actual, label):
    ok = sub[[pred, actual]].dropna()
    if ok.empty:
        return None
    e = ok[pred] - ok[actual]
    big = ok[ok[actual].abs() > 0.1]
    return {'candidate': label, 'n': len(ok), 'mae': e.abs().mean(), 'rmse': np.sqrt((e ** 2).mean()),
            'corr': ok[pred].corr(ok[actual]), 'sign_hit': (np.sign(ok[pred]) == np.sign(ok[actual])).mean(),
            'sign_hit_clear': (np.sign(big[pred]) == np.sign(big[actual])).mean() if len(big) else np.nan,
            'n_clear': len(big), 'from': ok.index.min() if False else sub.loc[ok.index, 'month'].min().strftime('%Y-%m')}


def table(sub, specs):
    return pd.DataFrame([x for x in (score(sub, p, a, l) for p, a, l in specs) if x])


ex = ~df.month.between(*COVID)
out = []
for name, mask in (('ex-COVID 2015+', ex & (df.month >= '2015-01-01')), ('all 2015+', df.month >= '2015-01-01')):
    sub = df[mask]
    infl = table(sub, [
        ('naive_yoy_t1', 'pce_yoy', 'Last official core PCE YoY (month-end)'),
        ('cle_yoy_t1', 'pce_yoy', 'Cleveland nowcast (month-end)'),
        ('naive_yoy_pre', 'pce_yoy', 'Last official (day before release)'),
        ('cle_yoy_pre', 'pce_yoy', 'Cleveland nowcast (day before release)'),
    ])
    chg = table(sub, [
        ('naive_chg_t1', 'pce_chg', 'Last official 3M change (month-end)'),
        ('cle_chg_t1', 'pce_chg', 'Cleveland-implied 3M change (month-end)'),
        ('cle_chg_pre', 'pce_chg', 'Cleveland-implied 3M change (day before release)'),
    ])
    common = sub[sub[['ads3_cal', 'gdpnow_cal', 'eni_cal', 'cf_naive', 'cf_actual']].notna().all(axis=1)]
    grow = table(common, [
        ('cf_naive', 'cf_actual', 'Last official CFNAI-MA3'),
        ('ads3_cal', 'cf_actual', 'ADS 3M avg (calibrated)'),
        ('gdpnow_cal', 'cf_actual', 'GDPNow (calibrated)'),
        ('eni_cal', 'cf_actual', 'St. Louis ENI (calibrated)'),
    ])
    wei = table(sub[sub.wei3_cal.notna()], [
        ('cf_naive', 'cf_actual', 'Last official CFNAI-MA3'),
        ('wei3_cal', 'cf_actual', 'WEI 3M avg (calibrated)'),
        ('ads3_cal', 'cf_actual', 'ADS 3M avg (calibrated)'),
        ('gdpnow_cal', 'cf_actual', 'GDPNow (calibrated)'),
    ])
    for kind, t in (('inflation_level', infl), ('inflation_direction', chg), ('growth_common_sample', grow), ('growth_wei_sample', wei)):
        t.insert(0, 'table', kind); t.insert(0, 'sample', name); out.append(t)

res = pd.concat(out)
res.to_csv(f'{OUT}/scores.csv', index=False)
pd.set_option('display.width', 220); pd.set_option('display.max_columns', 20)
print(res.round(3).to_string(index=False))
print('\nlags at month-end: PCE', df.lag_t1.median(), ' CFNAI', df.cf_lag.median())

# --- quadrant agreement at month-end: map's lagged official point vs nowcast point
sub = df[ex & (df.month >= '2016-06-01')].copy()
sub['q_actual'] = list(zip(np.sign(sub.cf_actual), np.sign(sub.pce_chg)))
cands = {'official (lagged, today\'s map)': ('cf_naive', 'naive_chg_t1'),
         'ADS + Cleveland': ('ads3_cal', 'cle_chg_t1'),
         'GDPNow + Cleveland': ('gdpnow_cal', 'cle_chg_t1'),
         'ENI + Cleveland': ('eni_cal', 'cle_chg_t1'),
         'official growth + Cleveland': ('cf_naive', 'cle_chg_t1')}
sub = sub.dropna(subset=['cf_actual', 'pce_chg'] + [c for pair in cands.values() for c in pair])
print(f'\nquadrant hit vs first-release quadrant, month-end, ex-COVID, n={len(sub)} ({sub.month.min():%Y-%m}..{sub.month.max():%Y-%m})')
for k, (x, y) in cands.items():
    hit = (np.sign(sub[x]).values == np.sign(sub.cf_actual).values) & (np.sign(sub[y]).values == np.sign(sub.pce_chg).values)
    print(f'  {k:34s} {hit.mean():.1%}')
sub.to_parquet(f'{OUT}/quadrant_panel.parquet')
