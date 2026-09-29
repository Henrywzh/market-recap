"""FINRA consolidated short interest, from FINRA's public query API.

Member firms report short positions in every US-listed and OTC equity twice a
month: as of the settlement date nearest the 15th and the month's last. FINRA
publishes each round about seven business days later. The API needs no key;
a query must name the settlement date (the dataset's partition key), and a
date that was not a settlement date answers 204 with no body.

Figures are shares short as reported, the previous round's figure, FINRA's
own days-to-cover (shares short over average daily volume), and the change.
A published round can be revised; the cache keeps a round for a week and
then refetches it. An empty answer is never cached.
"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json

import httpx
import pandas as pd

from .. import cache
from ..config import USER_AGENT

NAMESPACE = "finra"
URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
HOME_URL = "https://www.finra.org/finra-data/browse-catalog/equity-short-interest"
PAGE = 5000
FIELDS = {
    "symbolCode": "symbol",
    "settlementDate": "settlement_date",
    "currentShortPositionQuantity": "shares_short",
    "previousShortPositionQuantity": "previous_shares_short",
    "averageDailyVolumeQuantity": "average_daily_volume",
    "daysToCoverQuantity": "days_to_cover",
    "changePercent": "change_pct",
    "revisionFlag": "revision_flag",
}


def finra_symbol(yahoo_symbol: str) -> str:
    """Yahoo writes share classes with a dash (BRK-B); FINRA runs the class
    letter on (BRKB, BFB)."""
    return yahoo_symbol.replace("-", "").replace(".", "")


def candidate_dates(until: date, rounds: int) -> list[date]:
    """The last ``rounds`` nominal settlement dates on or before ``until``,
    newest first: the 15th and the month's last day. The real settlement
    date can fall a day or two earlier (a weekend or holiday), which
    ``fetch_round`` resolves by stepping back."""
    out: list[date] = []
    year, month = until.year, until.month
    while len(out) < rounds:
        last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
        for day in (last, date(year, month, 15)):
            if day <= until and len(out) < rounds:
                out.append(day)
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return out


def _post(body: dict) -> list[dict] | None:
    response = httpx.post(URL, json=body, timeout=60.0, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/json",
    })
    if response.status_code == 204:
        return None
    response.raise_for_status()
    return response.json()


def _query(day: date, symbols: list[str]) -> list[dict] | None:
    rows: list[dict] = []
    for start in range(0, len(symbols), 1000):
        chunk = symbols[start:start + 1000]
        offset = 0
        while True:
            page = _post({
                "limit": PAGE, "offset": offset,
                "compareFilters": [{"compareType": "EQUAL", "fieldName": "settlementDate", "fieldValue": day.isoformat()}],
                "domainFilters": [{"fieldName": "symbolCode", "values": chunk}],
            })
            if page is None:
                return None if not rows else rows
            rows.extend(page)
            if len(page) < PAGE:
                break
            offset += PAGE
    return rows


class _NotPublished(Exception):
    """No rows for this date: not a settlement date, or not published yet.
    Raised inside the cache callback so that an empty answer is never kept --
    a round still pending tonight is published next week."""


def fetch_round(nominal: date, symbols: list[str], *, use_cache: bool = True, max_back: int = 4) -> pd.DataFrame:
    """One reporting round for ``symbols`` (FINRA spelling). Steps back from
    the nominal date to the settlement date actually used. Empty when the
    round is not published yet."""
    digest = hashlib.sha1(",".join(sorted(symbols)).encode()).hexdigest()[:12]
    for back in range(max_back + 1):
        day = nominal - timedelta(days=back)
        if day.weekday() >= 5:
            continue

        def fetch(day=day) -> str:
            rows = _query(day, symbols)
            if not rows:
                raise _NotPublished(day.isoformat())
            return json.dumps(rows)

        try:
            text = cache.fetch_text(NAMESPACE, f"si-{day.isoformat()}-{digest}", fetch,
                                    kind="reference_data", suffix=".json", use_cache=use_cache)
        except _NotPublished:
            continue
        frame = pd.DataFrame(json.loads(text)).rename(columns=FIELDS)
        frame = frame[[c for c in FIELDS.values() if c in frame]]
        frame["settlement_date"] = pd.to_datetime(frame["settlement_date"])
        return frame
    return pd.DataFrame(columns=list(FIELDS.values()))
