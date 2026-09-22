"""Official daily fund holdings published by State Street (SSGA).

This is the same class of file a paid terminal uses for index weights: the
issuer's own published basket, with an explicit "as of" date. It is the
reason this dashboard can size a heat map by real S&P 500 weight instead of
by an approximate market cap.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re

import pandas as pd

from .. import cache
from .http import get_bytes

_BASE = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us"
)
HOLDINGS_URL = _BASE + "/holdings-daily-us-en-{ticker}.xlsx"
# SSGA abbreviates these two; they are not "nav-history"/"premium-discount".
# The names were read off the fund page rather than guessed, because guessing
# by analogy with the holdings file is what produced a string of 404s.
NAV_HISTORY_URL = _BASE + "/navhist-us-en-{ticker}.xlsx"
PREMIUM_DISCOUNT_URL = _BASE + "/pdhist-us-en-{ticker}.xlsx"

HOME_URL = "https://www.ssga.com"
NAMESPACE = "ssga"

_AS_OF = re.compile(r"As of (\d{1,2}-[A-Za-z]{3}-\d{4})")


def _download(ticker: str, kind: str, url: str, *, use_cache: bool, optional: bool) -> bytes:
    """One issuer file. ``optional`` files are negative-cached when missing:
    whether SSGA publishes a NAV history for a fund is a property of the fund,
    not of today, and re-probing every non-SSGA ticker on every build cost more
    than every successful fetch put together."""
    return cache.fetch_bytes(
        NAMESPACE,
        f"{kind}-{ticker.lower()}",
        lambda: get_bytes(url, timeout=60.0),
        kind="daily_file",
        suffix=".xlsx",
        use_cache=use_cache,
        remember_missing=optional,
    )


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


def fetch_nav_history(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Published daily NAV, shares outstanding and total net assets.

    This is what makes ETF flow a *history* rather than a running tally. Net
    flow is the change in shares outstanding priced at NAV, and because the
    issuer publishes both going back two decades, the whole series can be
    rebuilt in one fetch instead of accruing one observation per run.
    """
    url = NAV_HISTORY_URL.format(ticker=ticker.lower())

    def _parse() -> pd.DataFrame:
        payload = _download(ticker, "navhist", url, use_cache=use_cache, optional=True)
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
        return frame.drop_duplicates("date", keep="last").reset_index(drop=True)

    frame = cache.frame(
        NAMESPACE, f"navhist-{ticker.lower()}", _parse, kind="daily_file", use_cache=use_cache
    )
    return frame, url


def fetch_premium_discount(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """The issuer's own published premium/discount to NAV, in percent."""
    url = PREMIUM_DISCOUNT_URL.format(ticker=ticker.lower())

    def _parse() -> pd.DataFrame:
        payload = _download(ticker, "pdhist", url, use_cache=use_cache, optional=True)
        frame = _table(payload, "Date").rename(
            columns={"Date": "date", "Premium/Discount": "premium_pct"}
        )
        frame = frame[[c for c in ("date", "premium_pct") if c in frame]].copy()
        frame["date"] = pd.to_datetime(frame["date"], format="%d-%b-%Y", errors="coerce")
        frame["premium_pct"] = pd.to_numeric(frame["premium_pct"], errors="coerce")
        frame = frame.dropna(subset=["date", "premium_pct"]).sort_values("date")
        return frame.drop_duplicates("date", keep="last").reset_index(drop=True)

    frame = cache.frame(
        NAMESPACE, f"pdhist-{ticker.lower()}", _parse, kind="daily_file", use_cache=use_cache
    )
    return frame, url


def fetch_holdings(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str | None, str]:
    """Return (holdings, as_of_date, url) for one SSGA fund.

    The as-of date is parsed from the file's own header rather than assumed to
    be today: SSGA publishes the prior session's basket during the morning, and
    a dashboard that relabels it as today is quietly wrong.
    """
    url = HOLDINGS_URL.format(ticker=ticker.lower())
    # Not optional: a missing holdings file for an index this dashboard claims
    # to cover is a build failure, not a fact to cache.
    payload = _download(ticker, "holdings", url, use_cache=use_cache, optional=False)

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
            "SEDOL": "sedol",
            "Weight": "weight",
            "Sector": "ssga_sector",
            "Shares Held": "shares_held",
            "Local Currency": "currency",
        }
    )
    keep = [c for c in ("name", "ticker", "sedol", "weight", "ssga_sector", "shares_held") if c in frame]
    frame = frame[keep].copy()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["weight"] = pd.to_numeric(frame.get("weight"), errors="coerce")
    if "shares_held" in frame:
        frame["shares_held"] = pd.to_numeric(frame["shares_held"], errors="coerce")
    # Only listed equities are constituents. Two filters, because they catch
    # different things:
    #
    # A SEDOL identifies a listed security. The lines in these files without
    # one are cash, a money-market sweep, and -- the one that matters -- the
    # index futures the fund holds to equitise cash. QNDX carries
    # "NASD100 MICRO EMINDEC26" under the ticker HWBZ6, which looks exactly
    # like an equity ticker and passed the pattern test below. Left in, it
    # inflated the Nasdaq-100 to 102 "members", sat in the breadth and
    # advance/decline denominators as a name that can never advance, and was
    # sent to the price feed every build as a permanently missing symbol.
    #
    # The pattern test still earns its place: it drops the cash lines, whose
    # ticker is "-", and placeholder listings whose ticker is a CUSIP.
    if "sedol" in frame:
        sedol = frame["sedol"].astype(str).str.strip()
        frame = frame[~sedol.isin({"-", "", "nan", "None"})]
    frame = frame[frame["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.\-]*")]
    frame = frame.dropna(subset=["weight"])
    frame = frame[frame["weight"] > 0].reset_index(drop=True)
    return frame.drop(columns=["sedol"], errors="ignore"), as_of, url


def to_yahoo_symbol(ticker: str) -> str:
    """SSGA writes class shares as BRK.B; Yahoo wants BRK-B."""
    return ticker.replace(".", "-")
