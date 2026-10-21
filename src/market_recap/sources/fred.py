"""FRED series via the keyless CSV export.

``fredgraph.csv`` serves the same observations as the API without requiring an
API key, which keeps this dashboard runnable by anyone who clones it. It
returns the *current vintage* of a series, not the historical vintage that was
visible on a past date -- so these values are used for a release table and a
level chart, never as a point-in-time model input.
"""

from __future__ import annotations

from io import StringIO

import pandas as pd

from .. import cache
from .http import FetchError, get_text

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
NAMESPACE = "fred"


def _is_csv(text: str) -> bool:
    first = text.lstrip().split("\n", 1)[0]
    return not first.startswith("<") and "," in first


def _csv(url: str) -> str:
    """The CSV, or a FetchError. During maintenance FRED answers 200 with an HTML
    page; taken as data it replaced the cached series and failed every panel
    reading FRED (2026-10-21). As an error, the cache serves its last good copy."""
    text = get_text(url, timeout=45.0)
    if not _is_csv(text):
        raise FetchError(f"FRED served no CSV for {url} (a maintenance page?)")
    return text


def fetch_series(series_id: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Return (date, value) for one series, dropping FRED's '.' missing marker."""
    url = CSV_URL.format(series_id=series_id)
    text = cache.fetch_text(
        NAMESPACE,
        series_id,
        lambda: _csv(url),
        kind="macro_series",
        suffix=".csv",
        use_cache=use_cache,
    )
    if not _is_csv(text):
        # A page cached before the check above: never data. Fetch again, past the cache.
        if not use_cache:
            raise FetchError(f"FRED served no CSV for {url} (a maintenance page?)")
        return fetch_series(series_id, use_cache=False)
    frame = pd.read_csv(StringIO(text))
    date_col = frame.columns[0]
    value_col = frame.columns[1]
    frame = frame.rename(columns={date_col: "date", value_col: "value"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"]).reset_index(drop=True)
    frame["series_id"] = series_id
    return frame, url
