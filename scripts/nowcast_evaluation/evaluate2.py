"""Longer per-candidate samples, GDP as its own target, and the market read.

Reads monthly_panel.parquet from evaluate.py. Signs use each source's own
neutral line (ADS 0 = average growth, CFNAI 0 = trend, GDP-unit nowcasts 1.8%).
"""
import sys
import numpy as np
import pandas as pd
import yfinance as yf

RAW, OUT = sys.argv[1], sys.argv[2]
COVID = (pd.Timestamp('2020-03-01'), pd.Timestamp('2021-06-01'))
TREND_GDP = 1.8
df = pd.read_parquet(f'{OUT}/monthly_panel.parquet')
ex = ~df.month.between(*COVID)
pd.set_option('display.width', 200)


def sign_stats(sub, x, neutral, label):
    ok = sub[[x, 'cf_actual']].dropna()
    s = np.sign(ok[x] - neutral) == np.sign(ok.cf_actual)
    clear = ok.cf_actual.abs() > 0.1
    return {'candidate': label, 'n': len(ok), 'from': sub.loc[ok.index, 'month'].min().strftime('%Y-%m'),
            'corr_with_cfnai': ok[x].corr(ok.cf_actual), 'sign_hit': s.mean(), 'sign_hit_clear': s[clear].mean()}


print('GROWTH vs first-release CFNAI-MA3, raw signs, own longest sample, ex-COVID, 2014+')
own = df[ex]
print(pd.DataFrame([
    sign_stats(own, 'cf_naive', 0, 'Last official CFNAI-MA3 (1 month old)'),
    sign_stats(own, 'ads3', 0, 'ADS 3M avg'),
    sign_stats(own, 'gdpnow', TREND_GDP, 'GDPNow - 1.8'),
    sign_stats(own, 'eni', TREND_GDP, 'St. Louis ENI - 1.8'),
    sign_stats(own, 'wei3', TREND_GDP, 'WEI 3M avg - 1.8'),
]).round(3).to_string(index=False))

# --- GDP as its own target: first-release (advance) real GDP growth, SAAR
def alfred(sid):
    d = pd.read_parquet(f'{RAW}/alfred_{sid}.parquet')
    d['date'] = pd.to_datetime(d.date); d['rs'] = pd.to_datetime(d.realtime_start)
    return d.dropna(subset=['value'])


GDP, GNOW, ENI = alfred('A191RL1Q225SBEA'), alfred('GDPNOW'), alfred('STLENI')
ads = pd.read_parquet(f'{RAW}/ads_vintages.parquet')
ADS_V = np.sort(ads.vintage.unique())
first = GDP.sort_values('rs').groupby('date').first()
first = first[first.rs > first.rs.min()]      # drop quarters whose first vintage in ALFRED is not their advance print
rows = []
for q, r in first.iterrows():
    adv = r.rs
    for tag, t in (('quarter_end', q + pd.DateOffset(months=3)), ('day_before', adv - pd.Timedelta(days=1))):
        g = GNOW[(GNOW.date == q) & (GNOW.rs <= t)].sort_values('rs')
        e = ENI[(ENI.date == q) & (ENI.rs <= t)].sort_values('rs')
        i = np.searchsorted(ADS_V, np.datetime64(t), side='right') - 1
        v = ads[ads.vintage == ADS_V[i]]
        a = v[(v.date >= q) & (v.date < q + pd.DateOffset(months=3))].value.mean()
        prev = GDP[(GDP.rs <= t)].sort_values('rs').groupby('date').last()
        prev = prev[prev.index < q].value.iloc[-1] if (prev.index < q).any() else np.nan
        rows.append({'quarter': q, 'when': tag, 'actual': r.value, 'gdpnow': g.value.iloc[-1] if len(g) else np.nan,
                     'eni': e.value.iloc[-1] if len(e) else np.nan, 'ads_q': a, 'naive_prev_q': prev})
gq = pd.DataFrame(rows)
gq = gq[~gq.quarter.between(pd.Timestamp('2020-01-01'), pd.Timestamp('2021-04-01'))]
print('\nGDP (advance estimate, % SAAR), ex-COVID quarters')
for tag, sub in gq.groupby('when'):
    out = []
    for c in ('naive_prev_q', 'gdpnow', 'eni'):
        ok = sub[[c, 'actual']].dropna()
        out.append({'candidate': c, 'n': len(ok), 'mae_pp': (ok[c] - ok.actual).abs().mean(), 'corr': ok[c].corr(ok.actual),
                    'above_trend_hit': (np.sign(ok[c] - TREND_GDP) == np.sign(ok.actual - TREND_GDP)).mean()})
    ok = sub[['ads_q', 'actual']].dropna()
    out.append({'candidate': 'ads_q (corr only)', 'n': len(ok), 'mae_pp': np.nan, 'corr': ok.ads_q.corr(ok.actual),
                'above_trend_hit': np.nan})
    print(f'  at {tag}:'); print(pd.DataFrame(out).round(3).to_string(index=False))
gq.to_csv(f'{OUT}/gdp_quarterly.csv', index=False)

# --- market read: next-month SPX return and 10Y change by quadrant, quadrant known at month-end
px = yf.download(['^GSPC', '^TNX'], start='2013-12-01', end='2026-10-30', auto_adjust=True, progress=False)['Close']
px.to_csv(f'{RAW}/yahoo_spx_tnx.csv')


def fwd(t):
    a = px.loc[:t].iloc[-1]
    b = px.loc[:t + pd.DateOffset(months=1)].iloc[-1]
    return 100 * (b['^GSPC'] / a['^GSPC'] - 1), b['^TNX'] - a['^TNX']


m = df[ex & (df.t1 < '2026-09-25')].copy()
m[['spx_fwd', 'tnx_fwd']] = [fwd(t) for t in m.t1]
NAMES = {(1, 1): 'REFLATION', (1, -1): 'GOLDILOCKS', (-1, 1): 'STAGFLATION', (-1, -1): 'SLOWDOWN'}
methods = {
    "official, lagged (today's map)": (m.cf_naive, m.naive_chg_t1),
    'ADS + Cleveland nowcast': (m.ads3, m.cle_chg_t1),
    'actual (hindsight, first release)': (m.cf_actual, m.pce_chg),
}
print(f'\nNEXT-MONTH SPX % and 10Y bp by quadrant known at month-end, ex-COVID, {m.month.min():%Y-%m}..{m.month.max():%Y-%m}')
summary = []
for name, (x, y) in methods.items():
    q = pd.Series([NAMES.get((int(np.sign(a)), int(np.sign(b)))) if pd.notna(a) and pd.notna(b) and a != 0 and b != 0 else None
                   for a, b in zip(x, y)], index=m.index)
    g = m.assign(q=q).dropna(subset=['q']).groupby('q').agg(n=('spx_fwd', 'size'), spx=('spx_fwd', 'mean'),
                                                             spx_hit=('spx_fwd', lambda s: (s > 0).mean()),
                                                             tnx_bp=('tnx_fwd', lambda s: 100 * s.mean()))
    print(f'  {name}'); print(g.round(2).to_string())
    summary.append({'method': name, 'spread_best_worst_spx': g.spx.max() - g.spx.min(),
                    'slowdown_minus_rest': g.spx.get('SLOWDOWN', np.nan) - m.spx_fwd.mean()})
print(pd.DataFrame(summary).round(2).to_string(index=False))
m.to_parquet(f'{OUT}/market_panel.parquet')
