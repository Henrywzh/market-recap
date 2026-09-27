"""Daily settlement history of individual futures contracts, from Yahoo's chart API.

Used for the fed funds (``ZQ*.CBT``) and three-month SOFR (``SR3*.CME``)
contracts that MARKET -> Priced Path turns into a policy path. A contract's
history is what lets the page show where the path stood a week and a month
ago without waiting for the snapshot branch to accumulate. Yahoo's futures
quotes are delayed, and a nightly build reads the settled close.
"""

from __future__ import annotations

import json

import pandas as pd

from .. import cache
from .http import FetchError, get_text

NAMESPACE = "futures"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range}"


def fetch_history(symbol: str, *, range_: str = "1y", use_cache: bool = True) -> pd.Series:
    """Daily closes of one contract (date -> price); empty when Yahoo has none."""
    try:
        text = cache.fetch_text(
            NAMESPACE, f"{symbol}-{range_}",
            lambda: get_text(CHART_URL.format(symbol=symbol, range=range_), timeout=20.0, retries=1),
            kind="daily_file", suffix=".json", use_cache=use_cache,
        )
        result = (json.loads(text).get("chart") or {}).get("result") or []
    except (FetchError, ValueError):
        return pd.Series(dtype=float, name=symbol)
    if not result:
        return pd.Series(dtype=float, name=symbol)
    stamps = result[0].get("timestamp") or []
    closes = ((result[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    if not stamps or len(stamps) != len(closes):
        return pd.Series(dtype=float, name=symbol)
    index = pd.to_datetime(stamps, unit="s", utc=True).tz_convert("America/New_York").normalize().tz_localize(None)
    series = pd.Series(pd.to_numeric(pd.Series(closes), errors="coerce").to_numpy(), index=index, name=symbol)
    series = series[~series.index.duplicated(keep="last")].dropna()
    return series[series > 0]
