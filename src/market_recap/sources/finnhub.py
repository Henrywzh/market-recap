"""Company news headlines from Finnhub, for explaining a stock's large moves.

The free tier keeps about a year of company news and allows 60 requests a
minute. The key is ``FINNHUB_API_KEY`` from the environment (a GitHub secret
in CI), or locally a ``.config`` line in this repository or the sibling
alternative-data checkout. Without one, moves are explained from filings,
ratings, peers' reports and industry data alone.

The key travels only in the request; no URL this module reports, and no error
it raises, carries it.
"""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import re
import threading
import time

from .. import cache
from .http import FetchError, get_text

NAMESPACE = "finnhub"
API_URL = "https://finnhub.io/api/v1/company-news"
PAGE_URL = "https://finnhub.io/docs/api/company-news"
KEY_NAME = "FINNHUB_API_KEY"
# The free tier: 60 a minute. One request a little over every second keeps a
# long backfill under it without counting.
MIN_INTERVAL_S = 1.05
# News for a day this old does not change; a nearer day is asked again.
SETTLED_DAYS = 3
_KEY_IN_TEXT = re.compile(r"token=[^&\s'\"]+")
_REPO = Path(__file__).resolve().parents[3]
_lock = threading.Lock()
_last = {"t": 0.0}


def _read_one(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() == KEY_NAME:
            return value.strip().strip('"').strip("'")
    return ""


def api_key() -> str:
    value = os.environ.get(KEY_NAME, "").strip()
    if value:
        return value
    for path in (_REPO / ".config", _REPO.parent / "alternative-data" / ".config"):
        value = _read_one(path)
        if value:
            return value
    return ""


def available() -> bool:
    return bool(api_key())


def _get(symbol: str, start: date, end: date) -> str:
    key = api_key()
    if not key:
        raise FetchError(f"Finnhub needs {KEY_NAME}")
    with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last["t"])
        if wait > 0:
            time.sleep(wait)
        _last["t"] = time.monotonic()
    url = f"{API_URL}?symbol={symbol}&from={start.isoformat()}&to={end.isoformat()}&token={key}"
    try:
        return get_text(url, timeout=30.0, retries=1)
    except FetchError as exc:
        raise FetchError(_KEY_IN_TEXT.sub("token=REDACTED", str(exc)), not_found=exc.not_found) from None
    except Exception as exc:  # noqa: BLE001 -- its message may carry the URL
        raise FetchError(_KEY_IN_TEXT.sub("token=REDACTED", f"{type(exc).__name__}: {exc}")) from None


def is_cached(symbol: str, start: date, end: date, today: date) -> bool:
    kind = "archive" if (today - end).days > SETTLED_DAYS else "daily_file"
    return cache.is_fresh(cache.path_for(NAMESPACE, f"{symbol}-{start}-{end}", ".json.gz"), kind)


def company_news(symbol: str, start: date, end: date, today: date) -> list[dict]:
    """Every headline Finnhub tags with ``symbol`` from ``start`` to ``end``:
    {datetime (unix), headline, source, url, summary}."""
    kind = "archive" if (today - end).days > SETTLED_DAYS else "daily_file"
    text = cache.fetch_text(NAMESPACE, f"{symbol}-{start}-{end}", lambda: _get(symbol, start, end),
                            kind=kind, suffix=".json", compress=True)
    rows = json.loads(text)
    return rows if isinstance(rows, list) else []
