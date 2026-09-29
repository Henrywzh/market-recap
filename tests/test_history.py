"""History payloads for range-switch charts: daily recently, weekly before."""

import pandas as pd

from market_recap.util import history_payload


def _daily(start: str, end: str) -> pd.Series:
    index = pd.bdate_range(start, end)
    return pd.Series(range(len(index)), index=index, dtype=float)


def test_recent_year_daily_older_weekly():
    series = _daily("2020-01-01", "2026-09-25")
    out = history_payload(series, years=10, digits=2)
    dates = pd.to_datetime(out["dates"])
    recent = dates[dates > pd.Timestamp("2026-09-25") - pd.Timedelta(days=365)]
    older = dates[dates <= pd.Timestamp("2026-09-25") - pd.Timedelta(days=365)]
    assert len(recent) > 250                                    # every session of the last year
    # One point a week before; the week the cut falls in ends at the cut.
    assert (pd.Series(older).diff().dropna().dt.days.iloc[:-1] == 7).all()
    assert out["dates"][-1] == "2026-09-25"
    assert len(out["dates"]) == len(out["values"])


def test_weekly_point_is_the_last_print_of_its_week():
    series = _daily("2024-01-01", "2026-09-25")
    out = history_payload(series, years=10, digits=2)
    first = pd.Timestamp(out["dates"][0])
    assert first.dayofweek == 4                                 # a Friday close
    assert out["values"][0] == series.loc[first]


def test_years_bound_the_start_and_gaps_are_dropped():
    series = _daily("2010-01-01", "2026-09-25")
    series.iloc[-3] = float("nan")
    out = history_payload(series, years=5, digits=2)
    assert pd.Timestamp(out["dates"][0]) > pd.Timestamp("2021-09-25")
    assert None not in out["values"]


def test_empty_series():
    assert history_payload(pd.Series(dtype=float), years=10, digits=2) == {"dates": [], "values": []}
