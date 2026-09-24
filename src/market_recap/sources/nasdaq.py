"""Nasdaq's earnings calendar: which companies report on a date, and when.

One request per date returns every reporter with its session timing (before
the open / after the close / not supplied), the consensus EPS forecast and the
number of estimates behind it, and for a past date the reported EPS and
surprise. It is an unofficial JSON endpoint behind nasdaq.com's calendar page,
not a published API: the page says so, and a date that fails is reported as a
gap rather than as a day with no earnings. Nasdaq does not say whether a date
is company-confirmed or its own estimate.
"""

from __future__ import annotations

import json
import re

from .. import cache
from .http import get_text

NAMESPACE = "nasdaq"
EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings?date={date}"
HISTORY_URL = (
    "https://api.nasdaq.com/api/quote/{symbol}/historical?assetclass={asset}"
    "&fromdate={start}&todate={end}&limit=100"
)
HISTORY_PAGE = "https://www.nasdaq.com/market-activity/quotes/historical"
PAGE_URL = "https://www.nasdaq.com/market-activity/earnings"

# Nasdaq's edge resets any request whose User-Agent carries a contact address
# (the project-wide one does, for SEC); the project's name alone is accepted.
USER_AGENT = "market-recap/0.1"

TIMING = {"time-pre-market": "bmo", "time-after-hours": "amc", "time-not-supplied": None}


def _money(value) -> float | None:
    text = re.sub(r"[$,\s]", "", str(value or ""))
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def parse_earnings(text: str) -> list[dict]:
    rows = ((json.loads(text).get("data") or {}).get("rows")) or []
    out = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        estimates = str(row.get("noOfEsts") or "").strip()
        out.append({
            "symbol": symbol,
            "name": row.get("name"),
            "timing": TIMING.get(row.get("time")),
            "eps_forecast": _money(row.get("epsForecast")),
            "estimates": int(estimates) if estimates.isdigit() else None,
            "last_year_eps": _money(row.get("lastYearEPS")),
            "fiscal_quarter": row.get("fiscalQuarterEnding"),
            "eps": _money(row.get("eps")),
            "surprise_pct": _money(row.get("surprise")),
        })
    return out


def fetch_earnings(date: str, *, use_cache: bool = True, kind: str = "daily_file") -> list[dict]:
    """One day's calendar. A day well in the past no longer changes, so the
    season scoreboard reads those with ``kind="archive"``."""
    text = cache.fetch_text(
        NAMESPACE, f"earnings-{date}",
        lambda: get_text(EARNINGS_URL.format(date=date), timeout=20.0, retries=1, user_agent=USER_AGENT,
                         headers={"Accept": "application/json"}),
        kind=kind, suffix=".json", use_cache=use_cache,
    )
    return parse_earnings(text)


def parse_history(text: str) -> dict[str, float]:
    """{ISO date: close} from a historical-quotes response; empty if the
    symbol is not listed under the asset class asked for."""
    payload = json.loads(text)
    if (payload.get("status") or {}).get("rCode") not in (None, 200):
        errors = (payload.get("status") or {}).get("bCodeMessage") or []
        # "Symbol not exists" is an answer; anything else is a bad request, not a fact to cache.
        if not any(e.get("code") == 1001 for e in errors):
            raise ValueError(f"Nasdaq history: {errors}")
    data = payload.get("data") or {}
    rows = ((data.get("tradesTable") or {}).get("rows")) or []
    out = {}
    for row in rows:
        month, day, year = (row.get("date") or "//").split("/")
        close = _money(row.get("close"))
        if year and close is not None:
            out[f"{year}-{month}-{day}"] = close
    return out


def fetch_history(symbol: str, start: str, end: str, *, asset: str, use_cache: bool = True) -> dict[str, float]:
    """Daily closes as the exchange reports them (not dividend-adjusted).
    ``asset`` is Nasdaq's class: stocks, etf or index."""
    name = f"history-{asset}-{symbol}-{start}-{end}"
    text = cache.fetch_text(
        NAMESPACE, name,
        lambda: get_text(HISTORY_URL.format(symbol=symbol, asset=asset, start=start, end=end), timeout=20.0,
                         retries=1, user_agent=USER_AGENT, headers={"Accept": "application/json"}),
        kind="daily_file", suffix=".json", use_cache=use_cache,
    )
    try:
        return parse_history(text)
    except ValueError:
        cache.path_for(NAMESPACE, name, ".json").unlink(missing_ok=True)
        raise
