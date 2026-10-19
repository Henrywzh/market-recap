"""Robert J. Shiller's stock market data (shillerdata.com), for the excess CAPE yield.

The spreadsheet behind "Irrational Exuberance": monthly from 1871, the S&P
composite price (the month's average of daily closes), CPI, the 10-year
Treasury yield (GS10) and the cyclically adjusted P/E (CAPE: the real price
over ten years of real earnings). Shiller updates it about monthly; the latest
month's earnings are his estimate until reported. Current vintage: CPI is as
revised, so the history is a description, not a record of what was known.

Attribution: Robert J. Shiller, "Irrational Exuberance" data, shillerdata.com.
The page that reads this names him beside every value derived from it.

The file's address carries a version number that changes with each update,
so it is read off the data page rather than written here.
"""

from __future__ import annotations

from io import BytesIO
import re

import numpy as np
import pandas as pd

from .. import cache
from .http import get_bytes, get_text

HOME_URL = "https://shillerdata.com/"
NAMESPACE = "shiller"
ATTRIBUTION = 'Robert J. Shiller, "Irrational Exuberance" data (shillerdata.com)'
_LINK = re.compile(r'(?:https:)?//[^"\s]+/ie_data\.xls(?:\?ver=\d+)?')
# Spreadsheet columns (0-based) on the "Data" sheet, below its eight header rows.
COLUMNS = {"date": 0, "price": 1, "cpi": 4, "gs10": 6, "cape": 12, "ecy": 16}
HEADER_ROWS = 8


def _file_url() -> str:
    match = _LINK.search(get_text(HOME_URL))
    if not match:
        raise ValueError("shillerdata.com: no ie_data.xls link on the page")
    link = match.group(0)
    return link if link.startswith("https:") else "https:" + link


def parse(payload: bytes) -> pd.DataFrame:
    """Monthly rows indexed by month start: price, cpi, gs10, cape, ecy (%), infl_10y (%)."""
    raw = pd.read_excel(BytesIO(payload), sheet_name="Data", header=None, skiprows=HEADER_ROWS)
    raw = raw[pd.to_numeric(raw[COLUMNS["date"]], errors="coerce").notna()]
    stamp = raw[COLUMNS["date"]].astype(float)
    # "1871.1" is October: the decimals are the month number, not a fraction of a year.
    month = np.round((stamp - np.floor(stamp)) * 100).astype(int)
    index = pd.to_datetime({"year": np.floor(stamp).astype(int), "month": month, "day": 1})
    frame = pd.DataFrame({key: pd.to_numeric(raw[col], errors="coerce").to_numpy()
                          for key, col in COLUMNS.items() if key != "date"}, index=index.to_numpy())
    frame["ecy"] *= 100
    # His real rate: GS10 less the CPI's annualised change over the past ten years.
    frame["infl_10y"] = ((frame["cpi"] / frame["cpi"].shift(120)) ** 0.1 - 1) * 100
    return frame.sort_index()


def fetch(*, use_cache: bool = True) -> pd.DataFrame:
    payload = cache.fetch_bytes(NAMESPACE, "ie_data", lambda: get_bytes(_file_url(), timeout=60.0),
                                kind="macro_series", suffix=".xls", use_cache=use_cache)
    return parse(payload)
