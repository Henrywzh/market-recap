"""iShares (BlackRock) published NAV and shares-outstanding history.

The same evidence SSGA publishes, in a different envelope: BlackRock's fund
download is a SpreadsheetML workbook whose ``Historical`` sheet carries
``As Of``, ``NAV per Share``, ``Ex-Dividends`` and ``Shares Outstanding`` back
to the fund's inception. That is everything net flow needs, so an iShares fund
gets a measured flow series rather than an estimate.

Fund identity goes through BlackRock's own product screener rather than a
hard-coded table. That is not fastidiousness: a remembered portfolio id for
SHY returned the 0-1 Year Treasury fund instead of the 1-3 Year one, and
nothing downstream would have flagged that the flow series belonged to a
different fund.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re

import pandas as pd

from ..config import CACHE_DIR
from .http import FetchError, get_bytes, get_text

SCREENER_URL = (
    "https://www.ishares.com/us/product-screener/product-screener-v3.1.jsn"
    "?dcrPath=/templatedata/config/product-screener-v3/data/en/us-ishares/"
    "ishares-product-screener-backend-config&siteEntryPassthrough=true"
)
DOCUMENT_URL = (
    "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/"
    "get-fund-document?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=us-ishares"
    "&locale=en_US&component=fundDownload&userType=individual&portfolioId={portfolio_id}"
)

_SHEET = re.compile(r'<ss:Worksheet ss:Name="Historical">(.*?)</ss:Worksheet>', re.S)
_ROW = re.compile(r"<ss:Row>(.*?)</ss:Row>", re.S)
_CELL = re.compile(r"<ss:Cell[^>]*>(.*?)</ss:Cell>", re.S)
_TAG = re.compile(r"<[^>]+>")

_SCREENER_TTL = timedelta(days=7)
_MISSING_TTL = timedelta(days=7)


def _cache(name: str) -> Path:
    return CACHE_DIR / "ishares" / name


def fetch_portfolio_map(*, use_cache: bool = True) -> dict[str, str]:
    """Ticker -> BlackRock portfolio id, from the issuer's own screener."""
    path = _cache("product_screener.json")
    payload = None
    if use_cache and path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < _SCREENER_TTL:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload = None
    if payload is None:
        text = get_text(SCREENER_URL, timeout=90.0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        payload = json.loads(text)

    mapping: dict[str, str] = {}
    for portfolio_id, record in payload.items():
        if not isinstance(record, dict):
            continue
        ticker = record.get("localExchangeTicker")
        if isinstance(ticker, str) and ticker:
            mapping.setdefault(ticker.strip().upper(), str(portfolio_id))
    return mapping


def _parse_historical(text: str) -> pd.DataFrame:
    sheet = _SHEET.search(text)
    if not sheet:
        raise ValueError("no Historical sheet in the iShares workbook")
    rows = _ROW.findall(sheet.group(1))
    if len(rows) < 2:
        raise ValueError("Historical sheet has no observations")

    def cells(row: str) -> list[str]:
        return [_TAG.sub("", cell).strip() for cell in _CELL.findall(row)]

    header = cells(rows[0])
    records = [cells(row) for row in rows[1:]]
    frame = pd.DataFrame([r for r in records if len(r) == len(header)], columns=header)
    frame = frame.rename(
        columns={
            "As Of": "date",
            "NAV per Share": "nav",
            "Shares Outstanding": "shares_outstanding",
            "Ex-Dividends": "ex_dividend",
        }
    )
    frame["date"] = pd.to_datetime(frame["date"], format="%b %d, %Y", errors="coerce")
    for column in ("nav", "shares_outstanding"):
        if column in frame:
            frame[column] = pd.to_numeric(
                frame[column].astype(str).str.replace(",", "", regex=False).replace("--", None),
                errors="coerce",
            )
    keep = [c for c in ("date", "nav", "shares_outstanding") if c in frame]
    frame = frame[keep].dropna(subset=["date", "nav"]).sort_values("date")
    return frame.drop_duplicates("date", keep="last").reset_index(drop=True)


def fetch_nav_history(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Published NAV and shares outstanding for one iShares fund."""
    ticker = ticker.upper()
    parsed_path = _cache(f"navhist-{ticker.lower()}-{datetime.now():%Y%m%d}.parquet")
    marker = _cache(f"navhist-{ticker.lower()}.missing")

    mapping = fetch_portfolio_map(use_cache=use_cache)
    portfolio_id = mapping.get(ticker)
    if portfolio_id is None:
        raise FetchError(f"{ticker}: not an iShares fund", not_found=True)
    url = DOCUMENT_URL.format(portfolio_id=portfolio_id)

    if use_cache and parsed_path.exists():
        try:
            return pd.read_parquet(parsed_path), url
        except Exception:
            pass
    if use_cache and marker.exists():
        age = datetime.now() - datetime.fromtimestamp(marker.stat().st_mtime)
        if age < _MISSING_TTL:
            raise FetchError(f"{ticker}: no Historical sheet (cached)", not_found=True)

    # The workbook is several megabytes per fund, so it is fetched once a day
    # and only the parsed frame is kept.
    try:
        text = get_bytes(url, timeout=120.0).decode("utf-8", errors="replace")
        frame = _parse_historical(text)
    except FetchError:
        raise
    except Exception as exc:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(exc)[:200], encoding="utf-8")
        raise FetchError(f"{ticker}: {exc}", not_found=True) from exc

    try:
        parsed_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(parsed_path)
    except Exception:
        pass
    return frame, url
