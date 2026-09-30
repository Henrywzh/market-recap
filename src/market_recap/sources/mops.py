"""Taiwan monthly revenue from MOPS (the TWSE's Market Observation Post System).

Listed Taiwanese companies must publish the previous month's revenue by the
10th. One JSON request per company and month returns that month's revenue,
the same month a year earlier and the year to date. Ported from
alternative-data's ``taiwan_semiconductor_revenue_data`` MOPS source.

A published month never changes and is cached as an archive; a month not yet
published (MOPS answers code 406) is asked again next build rather than
remembered as absent. The response carries no publication date, so the date
this build first saw a month is recorded instead (``first_seen``): it is when
the figure was known here, not when the company filed it.
"""

from __future__ import annotations

from datetime import date
import json

import httpx

from .. import cache
from ..util import utc_now_iso

URL = "https://mops.twse.com.tw/mops/api/t05st10_ifrs"
PAGE_URL = "https://mops.twse.com.tw/mops/#/web/t05st10_ifrs"
NAMESPACE = "mops"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://mops.twse.com.tw",
    "Referer": PAGE_URL,
}
ROC_OFFSET = 1911
NOT_PUBLISHED = 406


class NotPublished(RuntimeError):
    """MOPS has no figure for that company and month yet."""


def _number(text) -> float | None:
    if text is None:
        return None
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return None


def _pct(text) -> float | None:
    value = _number(text)
    return None if value is not None and value >= 999999.99 else value   # MOPS: "cannot compute"


def parse(payload: dict) -> dict:
    """One company-month: revenue (NT$ thousand), year-ago, y/y and YTD."""
    if payload.get("code") == NOT_PUBLISHED:
        raise NotPublished(payload.get("message") or "not published")
    if payload.get("code") != 200:
        raise RuntimeError(f"MOPS answered {payload.get('code')}: {payload.get('message')}")
    result = payload.get("result") or {}
    values: dict[str, str] = {}
    pct_seen = 0
    for label, value, *_ in result.get("data") or []:
        if label == "增減百分比":
            values["yoy_pct" if pct_seen == 0 else "ytd_yoy_pct"] = value
            pct_seen += 1
        else:
            values.setdefault(label, value)
    yymm = str(result.get("yymm") or "")
    month = f"{int(yymm[:-2]) + ROC_OFFSET:04d}-{int(yymm[-2:]):02d}" if len(yymm) >= 4 else None
    return {
        "month": month,
        "revenue_k": _number(values.get("本月")),
        "year_ago_k": _number(values.get("去年同期")),
        "yoy_pct": _pct(values.get("yoy_pct")),
        "ytd_k": _number(values.get("本年累計")),
        "ytd_yoy_pct": _pct(values.get("ytd_yoy_pct")),
        "note": (values.get("備註/營收變化原因說明") or "").strip() or None,
    }


def _post(code: str, year: int, month: int) -> str:
    body = {"companyId": code, "dataType": "2", "month": str(month), "year": str(year - ROC_OFFSET),
            "subsidiaryCompanyId": ""}
    response = httpx.post(URL, headers=HEADERS, json=body, timeout=30.0)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") == NOT_PUBLISHED:
        raise NotPublished(payload.get("message") or "not published")
    return json.dumps({**payload, "first_seen": utc_now_iso()[:10]})


def fetch_month(code: str, month: str, *, use_cache: bool = True) -> dict:
    """One company-month, or NotPublished."""
    year, number = (int(p) for p in month.split("-"))
    text = cache.fetch_text(NAMESPACE, f"{code}-{month}", lambda: _post(code, year, number),
                            kind="archive", suffix=".json", use_cache=use_cache)
    payload = json.loads(text)
    return {**parse(payload), "first_seen": payload.get("first_seen")}


def months_back(today: date, count: int) -> list[str]:
    """The ``count`` calendar months before ``today``'s month, newest first."""
    out, year, month = [], today.year, today.month
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        out.append(f"{year:04d}-{month:02d}")
    return out


def fetch_history(code: str, today: date, months: int, *, use_cache: bool = True) -> list[dict]:
    """Published months, oldest first. The newest month is skipped quietly
    until the company files it (by the 10th)."""
    rows = []
    for month in months_back(today, months):
        try:
            rows.append(fetch_month(code, month, use_cache=use_cache))
        except NotPublished:
            continue
    return sorted(rows, key=lambda r: r["month"] or "")
