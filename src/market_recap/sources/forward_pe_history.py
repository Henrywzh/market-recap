"""Yahoo's own history of the forward P/E: one point per month end, as of that day.

Every other forward multiple on the page is recorded by this project, so it
starts the day recording began. Yahoo keeps its own: the fundamentals-timeseries
service behind the valuation table on a quote page returns, for each company,

* ``monthly``   calendar month ends, about the last fifteen;
* ``quarterly`` fiscal quarter ends, which add points the monthly series lacks
  (a July 31 quarter end for a company whose year ends in October);
* ``annual``    fiscal year ends, the last four.

Three facts decide how the points may be used, and the first two were measured
on the whole S&P 500 universe (see README, "Yahoo's forward P/E history"):

1. **Point in time.** The EPS behind a point (close / P/E) rises through the
   year as estimates were revised -- Goldman 44.3 in June 2025, 58.9 a year
   later, not today's 72 -- so a point is what the market was told that day.
2. **Not a twelve-month multiple.** The EPS is a fiscal year's consensus that
   moves on to the next year about three months before the year ends, so the
   horizon swings between 4 and 15 months through the year. That is
   :func:`market_recap.compute.valuation.forward_horizon_months`; the page's
   NTM multiple is a different measure and the two are never joined.
3. **One series per request.** Asking for several in one call makes Yahoo return
   only the last four monthly points; one type per request returns all fifteen.

Optional for every consumer. A company with no history, or a series that could
not be read, is named; it is never read as zero or as unchanged.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import threading
import time
from typing import Any

from .. import cache
from ..util import ERROR_DETAIL_CHARS

NAMESPACE = "forward-pe-history"
URL = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
# Series name -> Yahoo's type. Order matters only for the log.
SERIES = {"monthly": "monthlyForwardPeRatio", "quarterly": "quarterlyForwardPeRatio", "annual": "annualForwardPeRatio"}
PERIOD_START = 1577836800  # 2020-01-01: earlier than Yahoo keeps, so nothing it has is cut off
WORKERS = 4
ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 1.5
# Consecutive companies for which no series could be read, after which the rest
# of the universe is not asked: one refusal is noise, eight in a row is Yahoo
# refusing the client.
GIVE_UP_AFTER = 8
# The reason recorded for a company Yahoo simply has no history for (a new
# listing); the panel tells it apart from a fetch that failed.
NO_HISTORY = "Yahoo has no forward P/E history for this name"


def parse_series(payload: Any, type_name: str) -> list[dict] | None:
    """``[{date, pe}]`` oldest first; ``[]`` when Yahoo has none for the name.

    ``None`` when the answer is not a timeseries at all. A non-finite or
    non-positive multiple is dropped: Yahoo publishes none on a forecast loss,
    and a zero or negative one would only be a unit error.
    """
    try:
        result = payload["timeseries"]["result"]
    except (KeyError, TypeError):
        return None
    if not result:
        return []
    block = next((r for r in result if isinstance(r, dict) and type_name in r), None)
    if block is None:
        return []
    out = []
    for point in block[type_name] or []:
        try:
            date, value = point["asOfDate"], float(point["reportedValue"]["raw"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(date, str) and math.isfinite(value) and value > 0:
            out.append({"date": date, "pe": value})
    return sorted(out, key=lambda p: p["date"])


def _request(symbol: str, type_name: str) -> str:
    """One answer, retried on a refusal. yfinance holds the cookie Yahoo asks for."""
    from yfinance.data import YfData

    params = {"symbol": symbol, "type": type_name, "merge": "false", "padTimeSeries": "true",
              "period1": PERIOD_START, "period2": int(time.time()), "corsDomain": "finance.yahoo.com"}
    error = "no attempt"
    for attempt in range(ATTEMPTS):
        try:
            response = YfData().get(URL.format(symbol=symbol), params=params)
            if response.status_code == 200:
                return response.text
            error = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001 - a transport error is retried like a refusal
            error = str(exc)[:ERROR_DETAIL_CHARS] or type(exc).__name__
        if attempt + 1 < ATTEMPTS:
            time.sleep(RETRY_PAUSE_SECONDS * (attempt + 1))
    raise RuntimeError(error)


def fetch_series(symbols: list[str], *, use_cache: bool = True) -> tuple[dict[str, dict], dict[str, str]]:
    """``(found, failed)``.

    ``found[symbol]`` has a points list under each of ``monthly``, ``quarterly``
    and ``annual`` (empty when Yahoo has none), and ``unread`` naming any series
    that could not be fetched. ``failed[symbol]`` is the reason for a company
    with nothing at all: no series readable, or Yahoo has no history for it.
    """
    found: dict[str, dict] = {}
    failed: dict[str, str] = {}
    lock = threading.Lock()
    streak = {"n": 0}

    def one(symbol: str) -> None:
        with lock:
            if streak["n"] >= GIVE_UP_AFTER:
                failed[symbol] = "not asked: Yahoo refused the preceding requests"
                return
        points: dict[str, list[dict]] = {}
        unread: dict[str, str] = {}
        for name, type_name in SERIES.items():
            try:
                text = cache.fetch_text(NAMESPACE, f"{symbol.replace('/', '_')}-{name}", lambda: _request(symbol, type_name),
                                        kind="reference_data", suffix=".json", use_cache=use_cache)
                parsed = parse_series(json.loads(text), type_name)
            except Exception as exc:  # noqa: BLE001 - one series must not fail the rest
                unread[name] = str(exc)[:ERROR_DETAIL_CHARS] or type(exc).__name__
                continue
            if parsed is None:
                unread[name] = "answer is not a timeseries"
            else:
                points[name] = parsed
        with lock:
            if not points:
                streak["n"] += 1
                failed[symbol] = "; ".join(f"{n}: {why}" for n, why in unread.items()) or "no series"
                return
            streak["n"] = 0
            if not any(points.values()):
                failed[symbol] = NO_HISTORY
                return
            found[symbol] = {name: points.get(name, []) for name in SERIES} | ({"unread": sorted(unread)} if unread else {})

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, symbols))
    return found, failed
