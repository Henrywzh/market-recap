"""Form 13F-HR holdings: what each curated hedge fund reported owning at quarter end.

Two EDGAR documents per filing: the submissions index (which 13F-HR filings a
filer has made, and for which quarter) and the filing's information table (one
row per security). Both are read here; the arithmetic lives in compute.hf_13f.

Filings are immutable once accepted, so their documents are cached as the
"archive" kind. The submissions index changes as filings arrive, so it is read
once per session like the closes.

SEC asks automated clients to stay under ten requests a second. This module
keeps its own pace at five a second, half of the limit, because a build here
makes a few hundred requests and the shared throttle in ``sources.sec`` is
tuned for a different workload.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import threading
import time

import httpx
import pandas as pd

from .. import cache
from ..config import SEC_USER_AGENT
from . import ssga
from .http import FetchError

NAMESPACE = "sec13f"
HOME_URL = "https://www.sec.gov/"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/index.json"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"

# Five requests a second, shared across every call in the build.
_MIN_INTERVAL = 0.2
_last_call = 0.0
_throttle_lock = threading.Lock()

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
ATTEMPTS = 3


def _throttle() -> None:
    """Space request starts, across threads, at least _MIN_INTERVAL apart."""
    global _last_call
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _get(url: str, timeout: float) -> str:
    """One paced GET with the declared SEC User-Agent. A throttled or dropped
    request is retried; a challenge page or a refusal is an error to report,
    never something to route around."""
    for attempt in range(ATTEMPTS):
        last = attempt == ATTEMPTS - 1
        _throttle()
        try:
            response = httpx.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=timeout, follow_redirects=True)
        except httpx.TransportError:
            if last:
                raise
        else:
            if response.status_code not in RETRY_STATUSES or last:
                response.raise_for_status()
                return response.text
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class Filing:
    """One original 13F-HR: the quarter it describes and when it was accepted."""

    period: str       # quarter end, ISO date
    filed: str        # filing date, ISO date
    accession: str    # 0000000000-YY-NNNNNN
    primary: str      # name of the primary document (not the holdings table)


def _rows(recent: dict) -> list[Filing]:
    forms = recent.get("form", [])
    out = []
    for i, form in enumerate(forms):
        # Original reports only. Amendments restate a quarter and notices
        # (13F-NT) say the holdings are reported by another manager; neither
        # is a second copy of the holdings this module reads.
        if form != "13F-HR":
            continue
        out.append(Filing(
            period=recent["reportDate"][i],
            filed=recent["filingDate"][i],
            accession=recent["accessionNumber"][i],
            primary=recent["primaryDocument"][i],
        ))
    return out


def thirteen_f_filings(cik: int, *, use_cache: bool = True) -> list[Filing]:
    """The filer's original 13F-HR filings in the submissions index, newest first."""
    text = cache.fetch_text(
        f"{NAMESPACE}/submissions",
        f"CIK{cik:010d}",
        lambda: _get(SUBMISSIONS_URL.format(cik=cik), 45.0),
        kind="daily_file",
        suffix=".json",
        use_cache=use_cache,
        compress=True,
    )
    recent = json.loads(text).get("filings", {}).get("recent", {})
    return _rows(recent)


def _information_table_name(names: list[str]) -> str | None:
    """The holdings document in a filing folder. Filers name it infotable.xml,
    or form13fInfoTable.xml, and the primary document is never it."""
    candidates = [
        n for n in names
        if n.lower().endswith(".xml") and "primary_doc" not in n.lower() and "xsl" not in n.lower()
    ]
    return candidates[0] if candidates else None


def information_table_xml(cik: int, filing: Filing, *, use_cache: bool = True) -> str:
    """The raw information table of one filing. Immutable, so cached for a year."""
    folder = filing.accession.replace("-", "")
    listing = cache.fetch_text(
        f"{NAMESPACE}/index",
        filing.accession,
        lambda: _get(INDEX_URL.format(cik=cik, folder=folder), 45.0),
        kind="archive",
        suffix=".json",
        use_cache=use_cache,
    )
    names = [item["name"] for item in json.loads(listing)["directory"]["item"]]
    name = _information_table_name(names)
    if name is None:
        raise FetchError(f"{filing.accession}: no information table in the filing folder")
    return cache.fetch_text(
        f"{NAMESPACE}/infotable",
        filing.accession,
        lambda: _get(DOCUMENT_URL.format(cik=cik, folder=folder, name=name), 90.0),
        kind="archive",
        suffix=".xml",
        use_cache=use_cache,
    )


def sp500_identifiers(*, use_cache: bool = True) -> pd.DataFrame:
    """CUSIP, yahoo symbol and index weight for each S&P 500 member, from SSGA's SPY file.

    ssga.fetch_holdings drops the Identifier column, so the same cached file is
    read here. SSGA writes the CUSIP as the nine-character 13F identifier.
    """
    payload = ssga._download(
        "SPY", "holdings", ssga.HOLDINGS_URL.format(ticker="spy"), use_cache=use_cache, optional=False,
    )
    raw = pd.read_excel(BytesIO(payload), header=None, engine="openpyxl")
    header_row = None
    for idx, row in raw.iterrows():
        values = row.tolist()
        if "Ticker" in values and "Weight" in values:
            header_row = idx
            break
    if header_row is None:
        raise ValueError("SPY: no holdings header row in SSGA file")
    frame = pd.read_excel(BytesIO(payload), header=header_row, engine="openpyxl")
    frame = frame.rename(columns={"Identifier": "cusip", "Ticker": "ticker", "Weight": "weight"})
    frame = frame[["cusip", "ticker", "weight"]].dropna(subset=["cusip", "ticker"]).copy()
    frame["cusip"] = frame["cusip"].astype(str).str.strip().str.upper()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["yahoo_symbol"] = frame["ticker"].map(ssga.to_yahoo_symbol)
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce")
    frame = frame[frame["cusip"].str.len() == 9]
    return frame.drop_duplicates("cusip").reset_index(drop=True)
