"""Official daily fund holdings published by State Street (SSGA).

This is the same class of file a paid terminal uses for index weights: the
issuer's own published basket, with an explicit "as of" date. It is the
reason this dashboard can size a heat map by real S&P 500 weight instead of
by an approximate market cap.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import re

import pandas as pd

from ..config import CACHE_DIR
from .http import FetchError, get_bytes

_BASE = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us"
)
HOLDINGS_URL = _BASE + "/holdings-daily-us-en-{ticker}.xlsx"
# SSGA abbreviates these two; they are not "nav-history"/"premium-discount".
# The names were read off the fund page rather than guessed, because guessing
# by analogy with the holdings file is what produced a string of 404s.
NAV_HISTORY_URL = _BASE + "/navhist-us-en-{ticker}.xlsx"
PREMIUM_DISCOUNT_URL = _BASE + "/pdhist-us-en-{ticker}.xlsx"

_AS_OF = re.compile(r"As of (\d{1,2}-[A-Za-z]{3}-\d{4})")


def _cache_path(ticker: str, kind: str = "holdings") -> Path:
    return CACHE_DIR / "ssga" / f"{kind}-{ticker.lower()}-{datetime.now():%Y%m%d}.xlsx"


# Whether an issuer publishes an optional file is a property of the fund, not
# of today, so a miss is remembered for a week. Re-probing seventeen funds that
# are not State Street products on every build is pure latency, but pinning the
# list in config would hide it the day SSGA adds one.
_MISSING_TTL = timedelta(days=7)


def _missing_marker(path: Path) -> Path:
    return path.with_suffix(".missing")


def _download(url: str, path: Path, *, use_cache: bool) -> bytes:
    if use_cache and path.exists():
        return path.read_bytes()

    marker = _missing_marker(path)
    if use_cache and marker.exists():
        age = datetime.now() - datetime.fromtimestamp(marker.stat().st_mtime)
        if age < _MISSING_TTL:
            raise FetchError(f"{url}: not published (cached)", not_found=True)

    try:
        payload = get_bytes(url, timeout=60.0)
    except FetchError as exc:
        if exc.not_found:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(url, encoding="utf-8")
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _table(payload: bytes, first_column: str) -> pd.DataFrame:
    """Read an SSGA fund-data sheet whose real header sits below a title block.

    Every one of these files opens with Fund Name / Ticker Symbol lines before
    the actual column headers, so the header row has to be located by its first
    cell rather than assumed to be row 0.
    """
    raw = pd.read_excel(BytesIO(payload), header=None, engine="openpyxl")
    header_row = None
    for idx, row in raw.iterrows():
        if str(row.iloc[0]).strip() == first_column:
            header_row = idx
            break
    if header_row is None:
        raise ValueError(f"no '{first_column}' header row in SSGA file")
    frame = pd.read_excel(BytesIO(payload), header=header_row, engine="openpyxl")
    return frame.dropna(how="all")


def _parsed_cache(ticker: str, kind: str) -> Path:
    return CACHE_DIR / "ssga" / f"{kind}-{ticker.lower()}-{datetime.now():%Y%m%d}.parquet"


def _load_parsed(ticker: str, kind: str, use_cache: bool) -> pd.DataFrame | None:
    """Re-reading a 5,700-row xlsx through openpyxl on every build cost more
    than downloading it did. The parsed frame is cached beside the workbook."""
    if not use_cache:
        return None
    path = _parsed_cache(ticker, kind)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _save_parsed(ticker: str, kind: str, frame: pd.DataFrame) -> None:
    try:
        path = _parsed_cache(ticker, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path)
    except Exception:
        pass


def fetch_nav_history(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Published daily NAV, shares outstanding and total net assets.

    This is what makes ETF flow a *history* rather than a running tally. Net
    flow is the change in shares outstanding priced at NAV, and because the
    issuer publishes both going back two decades, the whole series can be
    rebuilt in one fetch instead of accruing one observation per run.
    """
    url = NAV_HISTORY_URL.format(ticker=ticker.lower())
    cached = _load_parsed(ticker, "navhist", use_cache)
    if cached is not None:
        return cached, url
    payload = _download(url, _cache_path(ticker, "navhist"), use_cache=use_cache)
    frame = _table(payload, "Date").rename(
        columns={
            "Date": "date",
            "NAV": "nav",
            "Shares Outstanding": "shares_outstanding",
            "Total Net Assets": "total_net_assets",
        }
    )
    keep = [c for c in ("date", "nav", "shares_outstanding", "total_net_assets") if c in frame]
    frame = frame[keep].copy()
    frame["date"] = pd.to_datetime(frame["date"], format="%d-%b-%Y", errors="coerce")
    for column in keep[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "nav"]).sort_values("date")
    frame = frame.drop_duplicates("date", keep="last").reset_index(drop=True)
    _save_parsed(ticker, "navhist", frame)
    return frame, url


def fetch_premium_discount(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """The issuer's own published premium/discount to NAV, in percent."""
    url = PREMIUM_DISCOUNT_URL.format(ticker=ticker.lower())
    cached = _load_parsed(ticker, "pdhist", use_cache)
    if cached is not None:
        return cached, url
    payload = _download(url, _cache_path(ticker, "pdhist"), use_cache=use_cache)
    frame = _table(payload, "Date").rename(columns={"Date": "date", "Premium/Discount": "premium_pct"})
    frame = frame[[c for c in ("date", "premium_pct") if c in frame]].copy()
    frame["date"] = pd.to_datetime(frame["date"], format="%d-%b-%Y", errors="coerce")
    frame["premium_pct"] = pd.to_numeric(frame["premium_pct"], errors="coerce")
    frame = frame.dropna(subset=["date", "premium_pct"]).sort_values("date")
    frame = frame.drop_duplicates("date", keep="last").reset_index(drop=True)
    _save_parsed(ticker, "pdhist", frame)
    return frame, url


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
