"""Aswath Damodaran's implied equity risk premium for the S&P 500, by month.

From his data page (pages.stern.nyu.edu/~adamodar): the premium that equates
the index level with expected cash flows to investors, at the start of each
month from September 2008, as he published it then. The column read is
"ERP (T12m)", the one filled for every month; his other variants start later.

Attribution: Aswath Damodaran, implied ERP (pages.stern.nyu.edu/~adamodar).
"""

from __future__ import annotations

from io import BytesIO
import warnings

import pandas as pd

from .. import cache
from .http import get_bytes

URL = "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPbymonth.xlsx"
HOME_URL = "https://pages.stern.nyu.edu/~adamodar/"
NAMESPACE = "damodaran"
ATTRIBUTION = "Aswath Damodaran, implied ERP (pages.stern.nyu.edu/~adamodar)"
SHEET = "Historical ERP"
DATE_COLUMN = "Start of month"
ERP_COLUMN = "ERP (T12m)"


def parse(payload: bytes) -> pd.Series:
    """The implied ERP in percent, indexed by the month it was published for."""
    with warnings.catch_warnings():
        # The workbook carries an Excel extension openpyxl does not read; the data is unaffected.
        warnings.simplefilter("ignore", UserWarning)
        frame = pd.read_excel(BytesIO(payload), sheet_name=SHEET)
    series = pd.Series(pd.to_numeric(frame[ERP_COLUMN], errors="coerce").to_numpy() * 100,
                       index=pd.to_datetime(frame[DATE_COLUMN], errors="coerce"))
    return series[series.index.notna()].dropna().sort_index()


def fetch(*, use_cache: bool = True) -> pd.Series:
    payload = cache.fetch_bytes(NAMESPACE, "ERPbymonth", lambda: get_bytes(URL, timeout=60.0),
                                kind="macro_series", suffix=".xlsx", use_cache=use_cache)
    return parse(payload)
