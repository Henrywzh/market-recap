"""Korean integrated-circuit exports from the Korea Customs Service.

Monthly exports of HS 8542 (electronic integrated circuits -- memory chips
are most of it) in thousands of US dollars, on the customs-acceptance date
basis, from the public trade-statistics site. Ported from alternative-data's
``semiconductor_proxy_data`` Korea source, with certificate verification left
on: the site's chain verifies, so there is no reason to turn it off.

The confirmed month is published around the middle of the following month.
The response carries no publication date, so ``first_seen`` records when this
build first saw each month.
"""

from __future__ import annotations

from datetime import date
import json

import httpx

from .. import cache
from ..util import utc_now_iso

HOME_URL = "https://tradedata.go.kr/cts/index.do"
TRADE_URL = "https://tradedata.go.kr/cts/hmpg/retrieveTrade.do"
NAMESPACE = "korea_customs"
HS_IC = "8542"
PAGE_ROWS = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": HOME_URL,
    "X-Requested-With": "XMLHttpRequest",
    "isAjax": "true",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def _to_float(value) -> float | None:
    text = str(value or "").replace(",", "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def parse(items: list[dict]) -> dict[str, float]:
    """{'2026-08': exports in USD thousand}; the '총계' (total) row is dropped."""
    out: dict[str, float] = {}
    for item in items:
        period = str(item.get("priodTitle") or "").strip()
        if len(period) != 7 or period[4] != ".":
            continue
        value = _to_float(item.get("expUsdAmt"))
        if value is not None:
            out[period.replace(".", "-")] = out.get(period.replace(".", "-"), 0.0) + value
    return out


def _query(start: str, end: str, hs: str) -> str:
    with httpx.Client(headers=HEADERS, timeout=60.0, follow_redirects=True) as client:
        client.get(HOME_URL).raise_for_status()      # the session cookie the query needs
        items, page = [], 1
        while True:
            body = {"tradeKind": "ETS_MNK_1020000A", "priodKind": "MON",
                    "priodFr": start.replace("-", "") + " ", "priodTo": end.replace("-", "") + " ",
                    "statsBase": "acptDd", "ttwgTpcd": "1000", "showPagingLine": str(PAGE_ROWS),
                    "sortColumn": "", "sortOrder": "", "hsSgnGrpCol": "HS4_SGN", "hsSgnWhrCol": "HS4_SGN",
                    "hsSgn": hs, "selectPaging": str(page)}
            response = client.post(TRADE_URL, data=body)
            response.raise_for_status()
            batch = response.json().get("items") or []
            items.extend(batch)
            if len(batch) < PAGE_ROWS:
                break
            page += 1
    return json.dumps({"items": items, "fetched": utc_now_iso()})


def fetch_exports(today: date, months: int = 36, *, use_cache: bool = True) -> tuple[list[dict], str]:
    """Monthly IC exports, oldest first, and when the answer was fetched.

    ``first_seen`` per month is carried from the previous day's cache file so
    a month keeps the date it first appeared rather than today's."""
    end = f"{today.year:04d}-{today.month:02d}"
    start_year, start_month = today.year - months // 12, today.month
    start = f"{start_year:04d}-{start_month:02d}"
    previous = cache.path_for(NAMESPACE, "ic-exports-seen", ".json")
    try:
        seen = json.loads(previous.read_text())
    except (OSError, ValueError):
        seen = {}
    text = cache.fetch_text(NAMESPACE, f"ic-exports-{start}-{end}", lambda: _query(start, end, HS_IC),
                            kind="daily_file", suffix=".json", use_cache=use_cache)
    payload = json.loads(text)
    values = parse(payload.get("items") or [])
    fetched = payload.get("fetched") or utc_now_iso()
    for month in values:
        seen.setdefault(month, fetched[:10])
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_text(json.dumps(seen), encoding="utf-8")
    rows = [{"month": m, "exports_k": v, "first_seen": seen.get(m)} for m, v in sorted(values.items())]
    return rows, fetched
