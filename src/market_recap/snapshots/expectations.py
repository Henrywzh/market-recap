"""Intraday snapshot of what rates and event markets are pricing.

Every run writes its long-format rows (one per contract per source) to
``expectations/YYYY/YYYY-MM-DD/HHMMSSZ.csv.gz`` and appends one line to
``expectations/YYYY/YYYY-MM-DD-runs.jsonl`` saying what answered. A file per
run, compressed, because one run is about 900 rows: appended as plain text
that would add over 300 MB a year to the branch; this way it is about 35 MB. The inputs
are stored, not derived probabilities: the meeting-by-meeting probabilities
are computed from these rows later (MARKET -> Priced Path), so a change in
that method never requires re-recording.

- Fed funds futures (``ZQ<month><yy>.CBT``): the next ``fed_funds_months``
  monthly contracts. Implied average rate = 100 - price.
- Three-month SOFR futures (``SR3<month><yy>.CME``): the next
  ``sofr_quarters`` quarterly contracts.
- Kalshi: every open market in each configured series.
- Polymarket: every open market under each configured tag.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Any, Iterable, Mapping
from urllib.parse import urlencode

from ..config import load_config
from ..sources.expectations import KALSHI_URL, POLY_URL
from ..sources.http import FetchError, get_text
from . import store

COLUMNS = (
    "fetched_at", "source", "series", "event", "contract", "label", "close_time",
    "price", "bid", "ask", "open_interest", "volume", "quote_time", "detail",
)
MONTH_CODES = "FGHJKMNQUVXZ"
QUARTER_MONTHS = (3, 6, 9, 12)
KALSHI_PAGES = 5


def _add_months(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + (day.month - 1) + months
    return index // 12, index % 12 + 1


def fed_funds_symbols(today: date, count: int) -> list[tuple[str, str]]:
    """(symbol, contract month) from the current month on. The current month
    trades until its last business day, so it is included."""
    out = []
    for step in range(count):
        year, month = _add_months(today, step)
        out.append((f"ZQ{MONTH_CODES[month - 1]}{year % 100:02d}.CBT", f"{year}-{month:02d}"))
    return out


def sofr_symbols(today: date, count: int) -> list[tuple[str, str]]:
    """(symbol, reference quarter start) for the next quarterly contracts. A
    quarterly SR3 references the three months that begin in its month, so the
    contract whose quarter has already started is still listed."""
    out = []
    # Start from the quarterly month on or before this one (December of last
    # year in January and February).
    if today.month < QUARTER_MONTHS[0]:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, max(m for m in QUARTER_MONTHS if m <= today.month)
    while len(out) < count:
        out.append((f"SR3{MONTH_CODES[month - 1]}{year % 100:02d}.CME", f"{year}-{month:02d}"))
        year, month = (year + 1, 3) if month == 12 else (year, month + 3)
    return out


def _float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def yahoo_futures_row(fetched_at: str, series: str, symbol: str, label: str, payload: Mapping) -> dict:
    meta = payload["chart"]["result"][0]["meta"]
    stamp = meta.get("regularMarketTime")
    return {
        "fetched_at": fetched_at, "source": "yahoo", "series": series, "event": None,
        "contract": symbol, "label": label, "close_time": None,
        "price": _float(meta.get("regularMarketPrice")), "bid": None, "ask": None,
        "open_interest": None, "volume": _float(meta.get("regularMarketVolume")),
        "quote_time": datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp else None,
        "detail": {"previous_close": _float(meta.get("chartPreviousClose") or meta.get("previousClose"))},
    }


def kalshi_rows(fetched_at: str, series: str, events: Iterable[Mapping]) -> list[dict]:
    rows = []
    for event in events:
        for market in event.get("markets") or []:
            rows.append({
                "fetched_at": fetched_at, "source": "kalshi", "series": series,
                "event": event.get("event_ticker"), "contract": market.get("ticker"),
                "label": market.get("yes_sub_title") or market.get("subtitle"),
                "close_time": market.get("close_time"),
                "price": _float(market.get("last_price_dollars")),
                "bid": _float(market.get("yes_bid_dollars")), "ask": _float(market.get("yes_ask_dollars")),
                "open_interest": _float(market.get("open_interest_fp")), "volume": _float(market.get("volume_fp")),
                "quote_time": market.get("updated_time"),
                "detail": {
                    "title": event.get("title"), "strike_type": market.get("strike_type"),
                    "floor_strike": market.get("floor_strike"), "cap_strike": market.get("cap_strike"),
                    "custom_strike": market.get("custom_strike"), "status": market.get("status"),
                },
            })
    return rows


def polymarket_rows(fetched_at: str, tag: str, events: Iterable[Mapping]) -> list[dict]:
    rows = []
    for event in events:
        for market in event.get("markets") or []:
            if market.get("closed"):
                continue
            try:
                outcomes = json.loads(market.get("outcomes") or "[]")
                prices = json.loads(market.get("outcomePrices") or "[]")
            except (TypeError, ValueError):
                outcomes, prices = [], []
            yes = dict(zip(outcomes, prices)).get("Yes")
            rows.append({
                "fetched_at": fetched_at, "source": "polymarket", "series": tag,
                "event": event.get("slug"), "contract": market.get("id"),
                "label": market.get("groupItemTitle") or market.get("question"),
                "close_time": market.get("endDate"),
                "price": _float(yes), "bid": _float(market.get("bestBid")), "ask": _float(market.get("bestAsk")),
                "open_interest": None, "volume": _float(market.get("volume")),
                "quote_time": market.get("updatedAt"),
                "detail": {"question": market.get("question"), "liquidity": _float(market.get("liquidity")),
                           "last_trade": _float(market.get("lastTradePrice"))},
            })
    return rows


def _fetch_kalshi(series: str) -> list[dict]:
    events, cursor = [], ""
    for _ in range(KALSHI_PAGES):
        params = {"series_ticker": series, "status": "open", "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        payload = json.loads(get_text(f"{KALSHI_URL}?{urlencode(params)}", timeout=30.0, retries=1,
                                      headers={"Accept": "application/json"}))
        events.extend(payload.get("events") or [])
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    return events


def _fetch_polymarket(tag: str) -> list[dict]:
    query = urlencode({"closed": "false", "limit": "100", "tag_slug": tag})
    payload = json.loads(get_text(f"{POLY_URL}?{query}", timeout=30.0, retries=1,
                                  headers={"Accept": "application/json"}))
    return payload if isinstance(payload, list) else []


def _fetch_chart(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
    return json.loads(get_text(url, timeout=20.0, retries=1))


def run(*, root=None, now: datetime | None = None) -> dict:
    settings: Mapping[str, Any] = load_config().get("snapshots", {}).get("expectations", {})
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(store.NEW_YORK)
    fetched_at = store.utc_stamp(now)
    rows: list[dict] = []
    failed: dict[str, str] = {}
    answered: dict[str, int] = {}

    futures = [("fed_funds", s, m) for s, m in fed_funds_symbols(local.date(), int(settings.get("fed_funds_months", 12)))]
    futures += [("sofr_3m", s, m) for s, m in sofr_symbols(local.date(), int(settings.get("sofr_quarters", 8)))]
    for series, symbol, label in futures:
        try:
            rows.append(yahoo_futures_row(fetched_at, series, symbol, label, _fetch_chart(symbol)))
            answered[series] = answered.get(series, 0) + 1
        except (FetchError, ValueError, KeyError, IndexError, TypeError) as exc:
            failed[symbol] = str(exc)[:200]

    for series in settings.get("kalshi_series", []):
        try:
            batch = kalshi_rows(fetched_at, series, _fetch_kalshi(series))
            rows += batch
            answered[f"kalshi {series}"] = len(batch)
        except (FetchError, ValueError, TypeError) as exc:
            failed[f"kalshi {series}"] = str(exc)[:200]

    seen: set = set()
    for tag in settings.get("polymarket_tags", []):
        try:
            # Tags overlap (a Fed market is often under both); keep the first.
            batch = [row for row in polymarket_rows(fetched_at, tag, _fetch_polymarket(tag))
                     if row["contract"] not in seen]
            seen.update(row["contract"] for row in batch)
            rows += batch
            answered[f"polymarket {tag}"] = len(batch)
        except (FetchError, ValueError, TypeError) as exc:
            failed[f"polymarket {tag}"] = str(exc)[:200]

    folder = store.day_dir(store.root_dir(root), "expectations", local)
    if rows:
        run_dir = folder / f"{local:%Y-%m-%d}"
        run_dir.mkdir(exist_ok=True)
        store.write_csv(run_dir / f"{now.astimezone(timezone.utc):%H%M%S}Z.csv.gz", rows, COLUMNS, compress=True)
    record = {"fetched_at": fetched_at, "rows": len(rows), "answered": answered, "failed": failed}
    store.append_jsonl(folder / f"{local:%Y-%m-%d}-runs.jsonl", record)
    status = "failed" if not rows else ("partial" if failed else "ok")
    return {"status": status, **record}
