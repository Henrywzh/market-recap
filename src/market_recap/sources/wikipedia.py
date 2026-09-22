"""GICS sector and sub-industry labels for the S&P 500.

Classification is descriptive metadata, not a price. It is cached and refreshed
weekly, and it is explicitly a *current* mapping -- it is never used to claim
what a company's sector was on a past date.
"""

from __future__ import annotations

from pathlib import Path

from io import StringIO

import pandas as pd

from .. import cache
from .http import get_text

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NAMESPACE = "wikipedia"


def fetch_sp500_classification(*, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Current GICS sector and sub-industry labels.

    Descriptive metadata, not a point-in-time record: it reflects today's
    classification for every name, including ones reclassified since.
    """

    def _parse() -> pd.DataFrame:
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
        frame["ticker"] = (
            frame["ticker"].astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
        )
        return frame

    frame = cache.frame(
        NAMESPACE, "sp500_classification", _parse, kind="reference_data", use_cache=use_cache
    )
    return frame, SP500_URL
