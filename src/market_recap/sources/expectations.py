"""Free forecasts for the releases CATALYSTS already lists.

Each feed is optional. A refusal, an empty Nasdaq page, or a thin book is a
gap on that event, not a failed build. The joins live in compute.expectations;
this module only fetches and records what came back.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from urllib.parse import urlencode

from .. import cache
from ..compute import expectations as E
from ..util import ERROR_DETAIL_CHARS
from .http import FetchError, get_text
from .nasdaq import USER_AGENT as NASDAQ_UA

NAMESPACE = "expectations"
TV_URL = "https://economic-calendar.tradingview.com/events"
NASDAQ_URL = "https://api.nasdaq.com/api/calendar/economicevents"
KALSHI_URL = "https://api.elections.kalshi.com/trade-api/v2/events"
CLEVELAND_MONTH = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json"
CLEVELAND_YEAR = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_year.json"
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
POLY_URL = "https://gamma-api.polymarket.com/events"


class EmptyPage(RuntimeError):
    """HTTP 200 whose payload carried no calendar. Seen from Nasdaq overnight."""


def _clip(exc: Exception) -> str:
    return str(exc)[:ERROR_DETAIL_CHARS]


def _json(url: str, *, headers: dict | None = None, timeout: float = 30.0, retries: int = 1,
          user_agent: str | None = None):
    return json.loads(get_text(url, headers=headers, timeout=timeout, retries=retries, user_agent=user_agent))


def fetch_tradingview(start: date, end: date, *, use_cache: bool = True) -> list[dict]:
    query = urlencode({
        "from": f"{start.isoformat()}T00:00:00.000Z",
        "to": f"{end.isoformat()}T23:59:59.000Z",
        "countries": "US",
    })
    text = cache.fetch_text(
        NAMESPACE, f"tradingview-{start.isoformat()}-{end.isoformat()}",
        lambda: get_text(f"{TV_URL}?{query}", timeout=30.0, retries=1,
                         headers={"Origin": "https://www.tradingview.com", "Accept": "application/json"}),
        kind="daily_file", suffix=".json", use_cache=use_cache,
    )
    return json.loads(text).get("result") or []


def fetch_nasdaq_page(day: date, *, use_cache: bool = True) -> list[dict]:
    query = urlencode({"date": day.isoformat()})

    def fetch() -> str:
        # A null page is not cached: the same endpoint answered an hour later.
        text = get_text(
            f"{NASDAQ_URL}?{query}", timeout=20.0, retries=1, user_agent=NASDAQ_UA,
            headers={"Accept": "application/json"},
        )
        if not isinstance(json.loads(text).get("data"), dict):
            raise EmptyPage(f"HTTP 200 with no data for {day.isoformat()}")
        return text

    text = cache.fetch_text(
        NAMESPACE, f"nasdaq-econ-{day.isoformat()}", fetch,
        kind="daily_file", suffix=".json", use_cache=use_cache,
    )
    return json.loads(text)["data"].get("rows") or []


def fetch_kalshi(series: str, *, use_cache: bool = True) -> list[dict]:
    def fetch() -> str:
        events, cursor = [], ""
        for _ in range(5):
            params = {"series_ticker": series, "status": "open", "with_nested_markets": "true"}
            if cursor:
                params["cursor"] = cursor
            payload = _json(f"{KALSHI_URL}?{urlencode(params)}", timeout=30.0, retries=1,
                            headers={"Accept": "application/json"})
            events.extend(payload.get("events") or [])
            cursor = payload.get("cursor") or ""
            if not cursor:
                break
        return json.dumps(events)

    text = cache.fetch_text(
        NAMESPACE, f"kalshi-{series}", fetch, kind="intraday_snapshot", suffix=".json", use_cache=use_cache,
    )
    return json.loads(text)


def fetch_cleveland(basis: str, *, use_cache: bool = True) -> list[dict]:
    url = CLEVELAND_YEAR if basis == "yoy" else CLEVELAND_MONTH
    text = cache.fetch_text(
        NAMESPACE, f"cleveland-{basis}",
        lambda: get_text(url, timeout=90.0, retries=1),
        kind="macro_series", suffix=".json", use_cache=use_cache,
    )
    return json.loads(text)


def fetch_forexfactory(*, use_cache: bool = True) -> list[dict]:
    text = cache.fetch_text(
        NAMESPACE, "forexfactory-thisweek",
        lambda: get_text(FF_URL, timeout=15.0, retries=0),
        kind="daily_file", suffix=".json", use_cache=use_cache,
    )
    return json.loads(text)


def fetch_polymarket(*, use_cache: bool = True) -> list[dict]:
    def fetch() -> str:
        events = []
        for tag in ("fed", "fed-rates"):
            query = urlencode({"closed": "false", "limit": "100", "tag_slug": tag})
            payload = _json(f"{POLY_URL}?{query}", timeout=30.0, retries=1, headers={"Accept": "application/json"})
            if isinstance(payload, list):
                events.extend(payload)
        return json.dumps(events)

    text = cache.fetch_text(
        NAMESPACE, "polymarket-fed", fetch, kind="intraday_snapshot", suffix=".json", use_cache=use_cache,
    )
    return json.loads(text)


def _uses_nasdaq(key: str) -> bool:
    if key in E.NASDAQ_EXACT.values():
        return True
    return key in {item for pair in E.NASDAQ_PAIRS.values() for item in pair}


def load(events: list[dict], *, use_cache: bool = True) -> tuple[dict, dict[str, str]]:
    """One book for the horizon, plus the feeds that did not answer.

    A source that no listed release asks for is not fetched.
    """
    book, failed = E.empty_book(), {}
    keys = {key for event in events for key in (event.get("_expect") or []) if key in E.CATALOG}
    days = {event["date"] for event in events if event.get("_expect")}
    if not keys or not days:
        return book, failed
    dates = sorted(date.fromisoformat(day) for day in days)

    if any(E.CATALOG[key].get("tv") for key in keys):
        try:
            rows = fetch_tradingview(dates[0], dates[-1] + timedelta(days=1), use_cache=use_cache)
            for (day, key), point in E.tradingview_points(rows).items():
                book["points"][("tradingview", day, key)] = point
        except (FetchError, ValueError, KeyError, TypeError) as exc:
            failed["tradingview"] = _clip(exc)

    nasdaq_days = sorted({
        date.fromisoformat(event["date"]) for event in events
        if any(_uses_nasdaq(key) for key in (event.get("_expect") or []))
    })
    if nasdaq_days:
        missed = []
        for release in nasdaq_days:
            page = release + timedelta(days=1)
            try:
                rows = fetch_nasdaq_page(page, use_cache=use_cache)
            except (FetchError, EmptyPage, ValueError, TypeError) as exc:
                missed.append(f"{page.isoformat()}: {_clip(exc)}")
                continue
            for (day, key), point in E.nasdaq_points(page, rows).items():
                book["points"][("nasdaq", day, key)] = point
        if missed:
            failed["nasdaq"] = "; ".join(missed[:3])

    if any(E.CATALOG[key].get("ff") for key in keys):
        try:
            points = E.forexfactory_points(fetch_forexfactory(use_cache=use_cache))
            for (day, key), point in points.items():
                book["points"][("forexfactory", day, key)] = point
        except (FetchError, ValueError, TypeError) as exc:
            failed["forexfactory"] = _clip(exc)

    series: dict[str, list[str]] = {}
    for key in keys:
        ticker = (E.CATALOG[key].get("kalshi") or {}).get("series")
        if ticker:
            series.setdefault(ticker, []).append(key)
    for ticker, tick_keys in series.items():
        try:
            contracts = fetch_kalshi(ticker, use_cache=use_cache)
        except (FetchError, ValueError, TypeError) as exc:
            failed[f"kalshi {ticker}"] = _clip(exc)
            continue
        for key in tick_keys:
            book["markets"].update(E.index_kalshi(contracts, key))

    if any(E.CATALOG[key].get("cleveland") for key in keys):
        for basis in ("yoy", "mom"):
            try:
                book["models"].update(E.cleveland_models(fetch_cleveland(basis, use_cache=use_cache), basis))
            except (FetchError, ValueError, TypeError) as exc:
                failed[f"cleveland {basis}"] = _clip(exc)

    if "fomc" in keys:
        try:
            book["polymarket"] = fetch_polymarket(use_cache=use_cache)
        except (FetchError, ValueError, TypeError) as exc:
            failed["polymarket"] = _clip(exc)

    return book, failed
