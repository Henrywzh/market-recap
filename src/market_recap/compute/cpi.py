"""Descriptive CPI transforms. No forecasts, fitting or synthetic observations."""

from __future__ import annotations

import pandas as pd

from . import periods
from ..util import clean_float


def annualized(index: pd.Series, months: int) -> pd.Series:
    """Require every calendar month in the window, including its endpoints."""
    if index.empty:
        return index
    monthly = index.reindex(pd.date_range(index.index.min(), index.index.max(), freq="MS"))
    out = ((monthly / monthly.shift(months)) ** (12 / months) - 1) * 100
    return out.where(monthly.rolling(months + 1).count() == months + 1)


def component_history(index: pd.Series, *, years: int, minimum: int) -> dict:
    # A percentile compares this month only with earlier monthly moves. It is
    # unusualness, NOT a probability, a forecast error or a policy threshold.
    growth = periods.transform(index, "mom")
    rows = []
    for stamp, value in growth.items():
        prior = growth.loc[(growth.index < stamp) &
                           (growth.index >= stamp - pd.DateOffset(years=years))].dropna()
        rows.append({"month": stamp.strftime("%Y-%m"), "mom": clean_float(value, 4),
                     "percentile": (clean_float(float((prior <= value).mean() * 100), 1)
                                    if pd.notna(value) and len(prior) >= minimum else None),
                     "prior_n": len(prior),
                     "p10": clean_float(prior.quantile(.1), 4) if len(prior) >= minimum else None,
                     "p90": clean_float(prior.quantile(.9), 4) if len(prior) >= minimum else None})
    return {"observations": rows}
