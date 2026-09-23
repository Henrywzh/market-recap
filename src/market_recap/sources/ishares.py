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

import json
import re

import pandas as pd

from .. import cache
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

HOME_URL = "https://www.ishares.com"
NAMESPACE = "ishares"


def fetch_portfolio_map(*, use_cache: bool = True) -> dict[str, str]:
    """Ticker -> BlackRock portfolio id, from the issuer's own screener.

    Resolved rather than hard-coded. A remembered id was wrong once already --
    239466 returns the 0-1 Year Treasury fund, not SHY -- and a wrong id fails
    silently by returning a real fund's real history under another name.
    """
    text = cache.fetch_text(
        NAMESPACE,
        "product_screener",
        lambda: get_text(SCREENER_URL, timeout=90.0),
        kind="reference_data",
        suffix=".json",
        use_cache=use_cache,
    )
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


def _document(ticker: str, url: str, *, use_cache: bool) -> str:
    """The fund's download workbook: holdings, NAV history and more, one file.

    Several megabytes of SpreadsheetML per fund, so it is stored compressed and
    read once per session by both the NAV history and the holdings.
    """
    raw = cache.fetch_bytes(
        NAMESPACE,
        f"document-{ticker.lower()}",
        lambda: get_bytes(url, timeout=120.0),
        kind="daily_file",
        suffix=".xml",
        use_cache=use_cache,
        remember_missing=True,
        compress=True,
    )
    return raw.decode("utf-8", errors="replace")


def _sheet_rows(text: str, name: str) -> list[list[str]]:
    sheet = re.search(rf'<ss:Worksheet ss:Name="{re.escape(name)}">(.*?)</ss:Worksheet>', text, re.S)
    if not sheet:
        return []
    return [[_TAG.sub("", cell).strip() for cell in _CELL.findall(row)] for row in _ROW.findall(sheet.group(1))]


# The workbook's column names, as this repository calls them. Equity and bond
# funds share one sheet layout with different columns; whichever exist are kept.
HOLDINGS_COLUMNS = {
    "Ticker": "ticker", "Name": "name", "Sector": "sector", "Asset Class": "asset_class",
    "Market Value": "market_value", "Weight (%)": "weight", "Location": "country",
    "Exchange": "exchange", "Currency": "currency", "Duration": "duration", "YTM (%)": "ytm",
    "Maturity": "maturity", "Coupon (%)": "coupon", "Par Value": "par_value", "Price": "price",
}
_NUMERIC = ("market_value", "weight", "duration", "ytm", "coupon", "par_value", "price")


def _parse_holdings(text: str) -> tuple[pd.DataFrame, str | None]:
    rows = _sheet_rows(text, "Holdings")
    header = next((i for i, row in enumerate(rows) if "Weight (%)" in row), None)
    if header is None:
        raise ValueError("no Holdings sheet with a weight column")
    as_of = None
    for row in rows[:header]:
        if len(row) >= 2 and row[0] == "Fund Holdings as of":
            as_of = pd.to_datetime(row[1], format="%b %d, %Y", errors="coerce")
            as_of = None if pd.isna(as_of) else as_of.strftime("%Y-%m-%d")
    names = rows[header]
    frame = pd.DataFrame([r for r in rows[header + 1:] if len(r) == len(names)], columns=names)
    frame = frame.rename(columns=HOLDINGS_COLUMNS)
    frame = frame[[c for c in HOLDINGS_COLUMNS.values() if c in frame]]
    for column in _NUMERIC:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column].str.replace(",", "", regex=False), errors="coerce")
    if "maturity" in frame:
        frame["maturity"] = pd.to_datetime(frame["maturity"], format="%b %d, %Y", errors="coerce")
    frame["weight"] = frame["weight"] / 100.0
    return frame.dropna(subset=["weight"]).reset_index(drop=True), as_of


def fetch_holdings(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str | None, str]:
    """(holdings, as-of date, url) from the fund's own workbook. Weights are
    fractions of the fund, cash and derivatives lines included."""
    ticker = ticker.upper()
    portfolio_id = fetch_portfolio_map(use_cache=use_cache).get(ticker)
    if portfolio_id is None:
        raise FetchError(f"{ticker}: not an iShares fund", not_found=True)
    url = DOCUMENT_URL.format(portfolio_id=portfolio_id)
    frame, as_of = _parse_holdings(_document(ticker, url, use_cache=use_cache))
    return frame, as_of, url


def fetch_nav_history(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Published NAV and shares outstanding for one iShares fund."""
    ticker = ticker.upper()
    mapping = fetch_portfolio_map(use_cache=use_cache)
    portfolio_id = mapping.get(ticker)
    if portfolio_id is None:
        raise FetchError(f"{ticker}: not an iShares fund", not_found=True)
    url = DOCUMENT_URL.format(portfolio_id=portfolio_id)

    def _parse() -> pd.DataFrame:
        # A fund whose document carries no Historical sheet is negative-cached:
        # that is a property of the fund, not of today.
        raw = _document(ticker, url, use_cache=use_cache)
        try:
            return _parse_historical(raw)
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(f"{ticker}: {exc}", not_found=True) from exc

    frame = cache.frame(
        NAMESPACE, f"navhist-{ticker.lower()}", _parse, kind="daily_file", use_cache=use_cache
    )
    return frame, url
