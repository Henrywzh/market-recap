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
import math

from .. import cache
from ..util import utc_now_iso
from .http import session

HOME_URL = "https://tradedata.go.kr/cts/index.do"
TRADE_URL = "https://tradedata.go.kr/cts/hmpg/retrieveTrade.do"
NAMESPACE = "korea_customs"
HS_IC = "8542"
PAGE_ROWS = 15
HEADERS = {
    "Referer": HOME_URL,
    "X-Requested-With": "XMLHttpRequest",
    "isAjax": "true",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


def _to_float(value) -> float | None:
    text = str(value if value is not None else "").replace(",", "").strip()
    try:
        number = float(text) if text else None
        return number if number is not None and math.isfinite(number) else None
    except ValueError:
        return None


def group_column(code: str) -> str:
    """The site's HS column for a 4, 6 or 10 digit code."""
    if not code.isdigit() or len(code) not in (4, 6, 10):
        raise ValueError(f"HS code must be 4, 6 or 10 digits, not {code!r}")
    return f"HS{len(code)}_SGN"


def parse_rows(items: list[dict]) -> list[dict]:
    """Monthly exports. The total row is dropped.

    exports_k is USD thousands. weight_t is metric tons, or None when a
    month's weight was missing so a unit value would be invented. usd_per_kg
    is exports_k / weight_t: a thousand dollars per metric ton is one dollar
    per kilogram. Mix and density move it, so it is not a spot price.
    """
    bucket: dict[str, dict] = {}
    for item in items:
        period = str(item.get("priodTitle") or "").strip()
        if len(period) != 7 or period[4] != ".":
            continue
        try:
            date.fromisoformat(period.replace(".", "-") + "-01")
        except ValueError:
            continue
        exports = _to_float(item.get("expUsdAmt"))
        month = period.replace(".", "-")
        slot = bucket.setdefault(month, {"exports_k": 0.0, "exports_ok": True, "weight_t": 0.0, "weight_ok": True})
        if exports is None:
            slot["exports_ok"] = False
        else:
            slot["exports_k"] += exports
        weight = _to_float(item.get("expTtwg"))
        if weight is None:
            slot["weight_ok"] = False
        else:
            slot["weight_t"] += weight
    out = []
    for month in sorted(bucket):
        slot = bucket[month]
        weight = slot["weight_t"] if slot["weight_ok"] and slot["weight_t"] > 0 else None
        exports = slot["exports_k"] if slot["exports_ok"] else None
        out.append({"month": month, "exports_k": exports, "weight_t": weight,
                    "usd_per_kg": (exports / weight) if weight and exports is not None else None})
    return out


def parse(items: list[dict]) -> dict[str, float | None]:
    """{'2026-08': exports in USD thousand}; the total row is dropped."""
    return {row["month"]: row["exports_k"] for row in parse_rows(items)}


def _query(start: str, end: str, hs: str) -> str:
    column = group_column(hs)
    with session(headers=HEADERS, timeout=60.0) as client:
        client.get(HOME_URL)      # the session cookie the query needs
        items, page = [], 1
        previous_batch = None
        while True:
            body = {"tradeKind": "ETS_MNK_1020000A", "priodKind": "MON",
                    "priodFr": start.replace("-", "") + " ", "priodTo": end.replace("-", "") + " ",
                    "statsBase": "acptDd", "ttwgTpcd": "1000", "showPagingLine": str(PAGE_ROWS),
                    "sortColumn": "", "sortOrder": "", "hsSgnGrpCol": column, "hsSgnWhrCol": column,
                    "hsSgn": hs, "selectPaging": str(page)}
            response = client.post(TRADE_URL, data=body)
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise RuntimeError("Korea Customs query did not return an items list")
            batch = payload["items"]
            if batch and batch == previous_batch:
                raise RuntimeError("Korea Customs repeated a page; refusing duplicate totals")
            items.extend(batch)
            if len(batch) < PAGE_ROWS:
                break
            page += 1
            if page > 100:
                raise RuntimeError("Korea Customs pagination exceeded 100 pages")
            previous_batch = batch
    return json.dumps({"items": items, "fetched": utc_now_iso()})


def fetch_code(today: date, code: str, months: int = 48, *, use_cache: bool = True) -> tuple[list[dict], str]:
    """One HS code, oldest first, and when the answer was fetched.

    first_seen per month is carried from the previous cache file so a month
    keeps the date it first appeared. HS 8542 keeps its old cache name; every
    other code has its own.
    """
    end = f"{today.year:04d}-{today.month:02d}"
    if months < 1:
        raise ValueError("months must be positive")
    start_year, offset = divmod(today.year * 12 + today.month - months, 12)
    start_month = offset + 1
    start = f"{start_year:04d}-{start_month:02d}"
    seen_name = "ic-exports-seen" if code == HS_IC else f"ic-exports-seen-{code}"
    cache_name = f"ic-exports-{start}-{end}" if code == HS_IC else f"ic-exports-{code}-{start}-{end}"
    previous = cache.path_for(NAMESPACE, seen_name, ".json")
    try:
        seen = json.loads(previous.read_text())
    except (OSError, ValueError):
        seen = {}
    text_body = cache.fetch_text(NAMESPACE, cache_name, lambda: _query(start, end, code),
                                  kind="daily_file", suffix=".json", use_cache=use_cache)
    payload = json.loads(text_body)
    rows = parse_rows(payload.get("items") or [])
    fetched = payload.get("fetched") or utc_now_iso()
    for row in rows:
        seen.setdefault(row["month"], fetched[:10])
        row["first_seen"] = seen.get(row["month"])
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_text(json.dumps(seen), encoding="utf-8")
    return rows, fetched


def fetch_exports(today: date, months: int = 36, *, use_cache: bool = True) -> tuple[list[dict], str]:
    """Monthly IC exports (HS 8542), oldest first, and when the answer was fetched."""
    rows, fetched = fetch_code(today, HS_IC, months, use_cache=use_cache)
    kept = [{"month": row["month"], "exports_k": row["exports_k"], "first_seen": row.get("first_seen")} for row in rows]
    return kept, fetched
