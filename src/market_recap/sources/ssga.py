"""Official daily fund holdings published by State Street (SSGA).

This is the same class of file a paid terminal uses for index weights: the
issuer's own published basket, with an explicit "as of" date. It is the
reason this dashboard can size a heat map by real S&P 500 weight instead of
by an approximate market cap.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import re

import pandas as pd

from ..config import CACHE_DIR
from .http import get_bytes

HOLDINGS_URL = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-{ticker}.xlsx"
)
_AS_OF = re.compile(r"As of (\d{1,2}-[A-Za-z]{3}-\d{4})")


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / "ssga" / f"{ticker.lower()}-{datetime.now():%Y%m%d}.xlsx"


def fetch_holdings(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str | None, str]:
    """Return (holdings, as_of_date, url) for one SSGA fund.

    The as-of date is parsed from the file's own header rather than assumed to
    be today: SSGA publishes the prior session's basket during the morning, and
    a dashboard that relabels it as today is quietly wrong.
    """
    url = HOLDINGS_URL.format(ticker=ticker.lower())
    path = _cache_path(ticker)
    if use_cache and path.exists():
        payload = path.read_bytes()
    else:
        payload = get_bytes(url, timeout=45.0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    raw = pd.read_excel(BytesIO(payload), header=None, engine="openpyxl")

    as_of = None
    header_row = None
    for idx, row in raw.iterrows():
        joined = " ".join(str(v) for v in row.tolist() if v is not None and str(v) != "nan")
        if as_of is None:
            match = _AS_OF.search(joined)
            if match:
                as_of = datetime.strptime(match.group(1), "%d-%b-%Y").strftime("%Y-%m-%d")
        if header_row is None and "Ticker" in row.tolist() and "Weight" in row.tolist():
            header_row = idx
            break
    if header_row is None:
        raise ValueError(f"{ticker}: no holdings header row in SSGA file")

    frame = pd.read_excel(BytesIO(payload), header=header_row, engine="openpyxl")
    frame = frame.rename(
        columns={
            "Name": "name",
            "Ticker": "ticker",
            "Identifier": "cusip",
            "Weight": "weight",
            "Sector": "ssga_sector",
            "Shares Held": "shares_held",
            "Local Currency": "currency",
        }
    )
    keep = [c for c in ("name", "ticker", "weight", "ssga_sector", "shares_held") if c in frame]
    frame = frame[keep].copy()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["weight"] = pd.to_numeric(frame.get("weight"), errors="coerce")
    if "shares_held" in frame:
        frame["shares_held"] = pd.to_numeric(frame["shares_held"], errors="coerce")
    # Cash and unsettled lines carry no ticker and must not become constituents.
    frame = frame[frame["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.\-]*")]
    frame = frame.dropna(subset=["weight"])
    frame = frame[frame["weight"] > 0].reset_index(drop=True)
    return frame, as_of, url


def to_yahoo_symbol(ticker: str) -> str:
    """SSGA writes class shares as BRK.B; Yahoo wants BRK-B."""
    return ticker.replace(".", "-")
