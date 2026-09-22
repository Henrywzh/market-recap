"""FRED series via the keyless CSV export.

``fredgraph.csv`` serves the same observations as the API without requiring an
API key, which keeps this dashboard runnable by anyone who clones it. It
returns the *current vintage* of a series, not the historical vintage that was
visible on a past date -- so these values are used for a release table and a
level chart, never as a point-in-time model input.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd

from ..config import CACHE_DIR
from .http import get_text

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
CACHE_MAX_AGE_HOURS = 12


def fetch_series(series_id: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Return (date, value) for one series, dropping FRED's '.' missing marker."""
    url = CSV_URL.format(series_id=series_id)
    path = CACHE_DIR / "fred" / f"{series_id}.csv"
    if use_cache and path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(hours=CACHE_MAX_AGE_HOURS):
            text = path.read_text(encoding="utf-8")
        else:
            text = _download(url, path)
    else:
        text = _download(url, path)

    frame = pd.read_csv(StringIO(text))
    date_col = frame.columns[0]
    value_col = frame.columns[1]
    frame = frame.rename(columns={date_col: "date", value_col: "value"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"]).reset_index(drop=True)
    frame["series_id"] = series_id
    return frame, url


def _download(url: str, path: Path) -> str:
    text = get_text(url, timeout=45.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text
