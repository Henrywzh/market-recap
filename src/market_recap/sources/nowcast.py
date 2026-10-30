"""Real-time macro nowcasts for the growth / inflation map's NOW point.

Cleveland Fed inflation nowcasts (the JSON its nowcasting chart draws from) and
the Philadelphia Fed's ADS business-conditions index (its latest vintage). Both
Banks allow non-commercial reuse with credit; the page credits each one.
"""

from __future__ import annotations

from io import BytesIO
import json

import pandas as pd

from .. import cache
from .http import get_bytes

NAMESPACE = "nowcast"
CLEVELAND_URL = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_year.json"
CLEVELAND_PAGE = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
ADS_URL = "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/ads/ADS_Index_Most_Current_Vintage.xlsx"
ADS_PAGE = "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/ads"
CORE_PCE = "Core PCE Inflation"
# The chart file carries one block per target month back to 2013; the NOW
# point only needs the months the official release has not reached yet.
RECENT_TARGETS = 4


def parse_cleveland(payload: bytes, series: str = CORE_PCE, recent: int = RECENT_TARGETS) -> pd.DataFrame:
    """(target, asof, value) for ``series``: each target month's daily nowcast path.

    Its x-axis labels are MM/DD without a year; a label more than two months
    before the target month belongs to the next calendar year (a December
    target's nowcasts run into January).
    """
    rows = []
    for block in json.loads(payload)[-recent:]:
        year, month = map(int, block["chart"]["subcaption"].split("-"))
        target = pd.Timestamp(year, month, 1)
        dates = []
        for item in block["categories"][0]["category"]:
            try:
                mm, dd = map(int, item["label"].split("/"))
            except ValueError:
                dates.append(None)        # a release marker ("PCE Sep"), not a day
                continue
            day = pd.Timestamp(year, mm, dd)
            dates.append(day if day >= target - pd.Timedelta(days=60) else pd.Timestamp(year + 1, mm, dd))
        for data in block["dataset"]:
            if data.get("seriesname") != series:
                continue
            for day, point in zip(dates, data["data"]):
                value = point.get("value")
                if day is not None and value not in (None, ""):
                    rows.append((target, day, float(value)))
    return pd.DataFrame(rows, columns=["target", "asof", "value"]).sort_values(["target", "asof"]).reset_index(drop=True)


def core_pce_nowcasts(*, use_cache: bool = True) -> pd.DataFrame:
    payload = cache.fetch_bytes(NAMESPACE, "cleveland_year", lambda: get_bytes(CLEVELAND_URL, timeout=60),
                                kind="macro_series", suffix=".json", use_cache=use_cache, compress=True)
    return parse_cleveland(payload)


def parse_ads(payload: bytes) -> pd.Series:
    frame = pd.read_excel(BytesIO(payload), engine="openpyxl")
    dates = pd.to_datetime(frame["Date"].astype(str), format="%Y:%m:%d")
    return pd.Series(frame["ADS_Index"].to_numpy(dtype=float), index=dates, name="ads").dropna().sort_index()


def ads_daily(*, use_cache: bool = True) -> pd.Series:
    payload = cache.fetch_bytes(NAMESPACE, "ads_current", lambda: get_bytes(ADS_URL, timeout=60),
                                kind="macro_series", suffix=".xlsx", use_cache=use_cache)
    return parse_ads(payload)
