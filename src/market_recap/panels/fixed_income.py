"""FIXED INCOME tab: the published par yield curve and its changes."""

from __future__ import annotations

import pandas as pd

from ..sources import treasury
from ..util import SourceRecord, clean_float

# The curve is compared against its own history, so the labels name a
# published date rather than "a week ago" in the abstract.
SNAPSHOTS = [
    ("latest", "Latest Published", 0),
    ("week_ago", "1 Week Ago", 7),
    ("month_ago", "1 Month Ago", 30),
    ("start_of_year", "Start of Year", None),
]
SPREADS = [("10Y - 2Y", "10Y", "2Y"), ("10Y - 3M", "10Y", "3M")]


def _pivot(frame: pd.DataFrame) -> pd.DataFrame:
    wide = frame.pivot(index="date", columns="tenor", values="yield_pct")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def _on_or_before(wide: pd.DataFrame, target: pd.Timestamp) -> tuple[pd.Timestamp, pd.Series] | None:
    eligible = wide[wide.index <= target]
    if eligible.empty:
        return None
    return eligible.index[-1], eligible.iloc[-1]


def build(ctx) -> dict:
    frame, url = treasury.fetch_par_yield_curve()
    if frame.empty:
        raise ValueError("Treasury returned no curve observations")
    wide = _pivot(frame)
    latest_date = wide.index[-1]
    latest = wide.iloc[-1]

    ctx.log.add(
        SourceRecord(
            "treasury_par_yield",
            "US Treasury daily par yield curve rates",
            url,
            latest_date.strftime("%Y-%m-%d"),
            rows=len(wide),
            policy="published_curve",
        )
    )

    tenor_order = [t for _, t, _ in treasury.TENORS]
    tenors = [t for t in tenor_order if t in wide.columns]

    curves = []
    for key, label, days_back in SNAPSHOTS:
        if days_back is None:
            start = pd.Timestamp(year=latest_date.year, month=1, day=1)
            eligible = wide[wide.index >= start]
            if eligible.empty:
                continue
            stamp, row = eligible.index[0], eligible.iloc[0]
        else:
            found = _on_or_before(wide, latest_date - pd.Timedelta(days=days_back))
            if found is None:
                continue
            stamp, row = found
        curves.append(
            {
                "key": key,
                "label": label,
                "date": stamp.strftime("%Y-%m-%d"),
                "values": [clean_float(row.get(t), 2) for t in tenors],
            }
        )

    by_key = {c["key"]: c for c in curves}

    def _bps(tenor: str, key: str) -> float | None:
        snapshot = by_key.get(key)
        if snapshot is None or tenor not in tenors:
            return None
        prior = snapshot["values"][tenors.index(tenor)]
        current = clean_float(latest.get(tenor))
        if prior is None or current is None:
            return None
        return round((current - prior) * 100.0, 1)

    prior_session = _on_or_before(wide.iloc[:-1], latest_date) if len(wide) > 1 else None

    rows = []
    for tenor in tenors:
        current = clean_float(latest.get(tenor), 2)
        one_day = None
        if prior_session is not None:
            prev = clean_float(prior_session[1].get(tenor))
            if prev is not None and current is not None:
                one_day = round((current - prev) * 100.0, 1)
        rows.append(
            {
                "tenor": tenor,
                "yield_pct": current,
                "1D": one_day,
                "1W": _bps(tenor, "week_ago"),
                "1M": _bps(tenor, "month_ago"),
                "YTD": _bps(tenor, "start_of_year"),
            }
        )

    spread_rows = []
    for label, long_leg, short_leg in SPREADS:
        if long_leg not in tenors or short_leg not in tenors:
            continue

        def _spread_bps(source: pd.Series) -> float | None:
            a, b = clean_float(source.get(long_leg)), clean_float(source.get(short_leg))
            return None if a is None or b is None else (a - b) * 100.0

        current = _spread_bps(latest)
        entry = {"label": label, "bps": clean_float(current, 1)}
        for key, column in (("week_ago", "1W"), ("month_ago", "1M"), ("start_of_year", "YTD")):
            snapshot = by_key.get(key)
            if snapshot is None or current is None:
                entry[column] = None
                continue
            prior_row = wide.loc[pd.Timestamp(snapshot["date"])]
            prior = _spread_bps(prior_row)
            entry[column] = None if prior is None else round(current - prior, 1)
        if prior_session is not None and current is not None:
            prev = _spread_bps(prior_session[1])
            entry["1D"] = None if prev is None else round(current - prev, 1)
        else:
            entry["1D"] = None
        spread_rows.append(entry)

    return {
        "as_of": latest_date.strftime("%Y-%m-%d"),
        "tenors": tenors,
        "curves": curves,
        "rows": rows,
        "spreads": spread_rows,
        "note": (
            '"Latest Published" is the most recent date the U.S. Treasury has posted par yield '
            "curve rates for. Treasury usually publishes same-day but sometimes not until early "
            "evening ET, so a build run shortly after the close can show the prior business day. "
            "That is the publisher's schedule, not a gap in this dashboard."
        ),
    }
