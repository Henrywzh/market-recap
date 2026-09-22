"""GICS sector and sub-industry labels for the S&P 500.

Classification is descriptive metadata, not a price. It is cached and refreshed
weekly, and it is explicitly a *current* mapping -- it is never used to claim
what a company's sector was on a past date.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from io import StringIO

import pandas as pd

from ..config import CACHE_DIR
from .http import get_text

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CACHE_MAX_AGE_DAYS = 7


def fetch_sp500_classification(*, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    path = CACHE_DIR / "wikipedia" / "sp500_classification.csv"
    if use_cache and path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(days=CACHE_MAX_AGE_DAYS):
            return pd.read_csv(path), SP500_URL

    tables = pd.read_html(StringIO(get_text(SP500_URL, timeout=45.0)))
    frame = next(t for t in tables if "Symbol" in t.columns and "GICS Sector" in t.columns)
    frame = frame.rename(
        columns={
            "Symbol": "ticker",
            "Security": "name",
            "GICS Sector": "sector",
            "GICS Sub-Industry": "sub_sector",
        }
    )[["ticker", "name", "sector", "sub_sector"]]
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame, SP500_URL
