"""Same-reference-month growth/inflation map; current-vintage, descriptive."""
from __future__ import annotations

import pandas as pd

from ..util import clean_float


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
