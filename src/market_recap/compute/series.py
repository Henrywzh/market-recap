"""Thinning a long daily series for the page: daily for the last year, the
last session of each week before that, so ten years of history stays small
while a short window still has every session."""

from __future__ import annotations

import pandas as pd

DAILY_DAYS = 365


def thin(frame: pd.DataFrame, years: int | None = None, *, daily_days: int = DAILY_DAYS) -> pd.DataFrame:
    """The last ``daily_days`` daily, older weeks' last row (and the first row,
    so a series rebased at its start keeps that start), within ``years``."""
    frame = frame.sort_index()
    if frame.empty:
        return frame
    last = frame.index[-1]
    if years:
        frame = frame[frame.index > last - pd.DateOffset(years=years)]
    cut = last - pd.Timedelta(days=daily_days)
    older = frame[frame.index <= cut]
    first = older.iloc[:1]
    older = older.groupby(older.index.to_period("W-FRI")).tail(1)
    return pd.concat([first[~first.index.isin(older.index)], older, frame[frame.index > cut]]).sort_index()


def payload(frame: pd.DataFrame, years: int | None = None, digits: int = 2) -> dict:
    """{dates, <column>: [...]} after thinning; blanks stay null."""
    thinned = thin(frame, years)
    return {"dates": [d.strftime("%Y-%m-%d") for d in thinned.index],
            **{col: [None if pd.isna(v) else round(float(v), digits) for v in thinned[col].to_numpy()]
               for col in thinned.columns}}
