"""Same-reference-month growth/inflation map; current-vintage, descriptive."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import clean_float, to_iso_date


def build(growth: pd.Series, core_yoy: pd.Series, *, months: int = 12, change_months: int = 3) -> dict:
    def monthly(series: pd.Series) -> pd.Series:
        result = series.copy()
        result.index = pd.to_datetime(result.index).to_period('M')
        return result[~result.index.duplicated(keep='last')].sort_index()

    g, p = monthly(growth), monthly(core_yoy)
    if g.empty or p.empty:
        return {'points': [], 'latest': None}
    axis = pd.period_range(min(g.index.min(), p.index.min()), max(g.index.max(), p.index.max()), freq='M')
    frame = pd.DataFrame({'growth': g.reindex(axis), 'inflation': p.reindex(axis)})
    frame['change'] = frame.inflation - frame.inflation.shift(change_months)
    frame = frame.dropna(subset=['growth', 'inflation', 'change']).tail(months)
    points = [{'month': str(date), 'growth': clean_float(row.growth, 4),
               'inflation_yoy': clean_float(row.inflation, 4), 'inflation_change_pp': clean_float(row.change, 4)}
              for date, row in frame.iterrows()]
    return {'points': points, 'latest': points[-1] if points else None}


# --- NOW point: real-time nowcasts past the last matched official month -----
# Pandemic months swing ADS and CFNAI by tens of points; a line fitted through
# them describes 2020, not an ordinary month.
CALIBRATION_EXCLUDE = (pd.Period('2020-03', 'M'), pd.Period('2021-06', 'M'))


def _monthly(series: pd.Series) -> pd.Series:
    result = series.copy()
    result.index = pd.to_datetime(result.index).to_period('M')
    return result[~result.index.duplicated(keep='last')].sort_index()


def ads_three_month(ads: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Each month's ADS average over it and the two months before (month to date for the
    latest), and how many daily readings the latest month has."""
    daily = ads.dropna().copy()
    daily.index = pd.to_datetime(daily.index).to_period('M')
    monthly = daily.groupby(level=0).mean()
    days = daily.groupby(level=0).size()
    return monthly.rolling(3, min_periods=3).mean().dropna(), days


def calibrate(ads3: pd.Series, cfnai_ma3: pd.Series, *, years: int = 10) -> dict | None:
    """Least-squares line from ADS 3M onto CFNAI-MA3 over the last ``years`` of matched months."""
    frame = pd.DataFrame({'ads': ads3, 'cfnai': _monthly(cfnai_ma3)}).dropna()
    if frame.empty:
        return None
    frame = frame[frame.index > frame.index.max() - 12 * years]
    frame = frame[~((frame.index >= CALIBRATION_EXCLUDE[0]) & (frame.index <= CALIBRATION_EXCLUDE[1]))]
    if len(frame) < 24:
        return None
    slope, intercept = np.polyfit(frame.ads, frame.cfnai, 1)
    return {'intercept': clean_float(intercept, 4), 'slope': clean_float(slope, 4), 'months': len(frame),
            'corr': clean_float(frame.ads.corr(frame.cfnai), 3), 'from': str(frame.index.min()), 'to': str(frame.index.max())}


def nowcast(regime: dict, growth: pd.Series, core_yoy: pd.Series, cleveland: pd.DataFrame, ads: pd.Series,
            *, change_months: int = 3) -> dict:
    """One point per month after the last matched official month that a nowcast covers.

    Each axis takes the official print where one exists and the nowcast where it
    does not: growth from ADS (mapped onto CFNAI-MA3 by ``calibrate``), inflation
    from the Cleveland Fed's latest core PCE YoY nowcast, its change measured
    against the official print ``change_months`` earlier.
    """
    latest = (regime or {}).get('latest')
    if not latest or cleveland is None or cleveland.empty:
        return {'points': [], 'calibration': None}
    last = pd.Period(latest['month'], 'M')
    g, p = _monthly(growth), _monthly(core_yoy)
    ads3, days = ads_three_month(ads) if ads is not None and not ads.empty else (pd.Series(dtype=float), pd.Series(dtype=int))
    fit = calibrate(ads3, growth)
    paths = cleveland.assign(month=pd.to_datetime(cleveland.target).dt.to_period('M'))
    points = []
    for month, path in paths.groupby('month'):
        if month <= last:
            continue
        final = path.sort_values('asof').iloc[-1]
        base = p.get(month - change_months)
        if month in p.index:
            yoy, inflation_source, inflation_asof = p[month], 'official', None
        else:
            yoy, inflation_source, inflation_asof = final.value, 'cleveland', to_iso_date(final['asof'])
        if month in g.index:
            x, growth_source = g[month], 'official'
        elif fit and month in ads3.index:
            x, growth_source = fit['intercept'] + fit['slope'] * ads3[month], 'ads'
        else:
            continue
        if base is None or pd.isna(base) or pd.isna(x):
            continue
        points.append({'month': str(month), 'growth': clean_float(x, 4), 'growth_source': growth_source,
                       'ads_3m': clean_float(ads3.get(month), 4), 'ads_days': int(days.get(month, 0)),
                       'inflation_yoy': clean_float(yoy, 4), 'inflation_source': inflation_source,
                       'inflation_asof': inflation_asof,
                       'inflation_change_pp': clean_float(yoy - base, 4)})
    return {'points': points, 'calibration': fit,
            'ads_through': to_iso_date(ads.index.max()) if ads is not None and not ads.empty else None,
            'cleveland_through': to_iso_date(cleveland['asof'].max())}


def quadrant(growth, change) -> str | None:
    if growth is None or change is None or growth == 0 or change == 0:
        return None
    return ('REFLATION' if change > 0 else 'GOLDILOCKS') if growth > 0 else ('STAGFLATION' if change > 0 else 'SLOWDOWN')


def update_ledger(previous: list, now: dict, official: dict, as_of: str) -> list:
    """Today's NOW reading added to the carried ledger (one row per build date), and each
    row scored once the official map reaches its month."""
    rows = {row['date']: row for row in previous or [] if isinstance(row, dict) and row.get('date')}
    point = (now.get('points') or [None])[-1]
    if point and as_of:
        rows[as_of] = {'date': as_of, 'month': point['month'], 'growth': point['growth'],
                       'growth_source': point['growth_source'], 'inflation_yoy': point['inflation_yoy'],
                       'inflation_change_pp': point['inflation_change_pp'],
                       'quadrant': quadrant(point['growth'], point['inflation_change_pp'])}
    actual = {p['month']: p for p in (official or {}).get('points', [])}
    for row in rows.values():
        hit = actual.get(row['month'])
        # Scored against the official month as first seen, not as later revised.
        if hit and 'actual_quadrant' not in row:
            row['actual_quadrant'] = quadrant(hit['growth'], hit['inflation_change_pp'])
            row['actual_inflation_yoy'] = hit['inflation_yoy']
    return [rows[d] for d in sorted(rows)]


# --- REAL-TIME view: each month as it was known at the time ------------------
def realtime_points(history: list, ledger: list, first_month: str | None) -> list:
    """One point per month from ``first_month`` on, as known then.

    Archive rows (``config/regime_quadrant_history.json``) are the month-end reads
    (known the first business day after the month). A month past the archive takes
    the nowcast ledger's last read of it, flagged ``source="ledger"``: still moving
    while that month has no official figures.
    """
    by_month = {}
    for row in ledger or []:                     # date-ordered: the last read wins
        if row.get('month') and row.get('quadrant'):
            by_month[row['month']] = {'month': row['month'], 'known': row.get('date'), 'growth': row.get('growth'),
                                      'inflation_change_pp': row.get('inflation_change_pp'),
                                      'quadrant': row['quadrant'], 'source': 'ledger'}
    for row in history or []:
        if row.get('month') and row.get('quadrant'):
            by_month[row['month']] = {'month': row['month'], 'known': row.get('known'), 'growth': row.get('growth'),
                                      'inflation_change_pp': row.get('inflation_change_pp'),
                                      'quadrant': row['quadrant'], 'source': 'archive', 'basis': row.get('growth_basis')}
    return [by_month[m] for m in sorted(by_month) if first_month is None or m >= first_month]
