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

from collections.abc import Callable
from datetime import date
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


# Nasdaq posts a reporter's actual hours after the release: Delta's EPS from
# the morning of 2026-10-09 was still blank at 18:35 that evening. A cached
# day that still lacks a result is asked for again, once per build, while it
# is this many days old; one never filled after that stays visibly pending.
RECHECK_DAYS = 7
_asked: set[str] = set()


def result_due(row: dict, day: str, as_of: str) -> bool:
    """Whether the calendar says this company had reported by ``as_of``'s close.

    A past date has; on ``as_of`` itself only a before-the-open report has, as
    an after-the-close or unstated time may still be ahead of the build.
    """
    return day < as_of or (day == as_of and row.get("timing") == "bmo")


def awaiting(rows: list[dict], day: str, as_of: str,
             tracked: Callable[[str], bool] | None = None) -> list[dict]:
    """Rows that should carry an actual by now and do not."""
    return [r for r in rows if r.get("eps") is None and result_due(r, day, as_of)
            and (tracked is None or tracked(r["symbol"]))]


def fetch_reported(day: str, as_of: str, *, tracked: Callable[[str], bool] | None = None,
                   use_cache: bool = True, kind: str = "daily_file") -> list[dict]:
    """:func:`fetch_earnings`, asked again when the cached copy of a recent day
    is still missing a (tracked) reporter's actual. A failed re-ask keeps the
    cached rows."""
    path = cache.path_for(NAMESPACE, f"earnings-{day}", ".json")
    from_cache = use_cache and cache.is_fresh(path, kind)
    rows = fetch_earnings(day, use_cache=use_cache, kind=kind)
    if not from_cache or day in _asked:
        _asked.add(day)
        return rows
    recent = (date.fromisoformat(as_of) - date.fromisoformat(day)).days <= RECHECK_DAYS
    if not recent or not awaiting(rows, day, as_of, tracked):
        return rows
    _asked.add(day)
    try:
        return fetch_earnings(day, use_cache=False, kind=kind)
    except Exception:  # noqa: BLE001 - the cached day stands; the result stays pending
        return rows


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


SHORT_INTEREST_URL = "https://api.nasdaq.com/api/quote/{symbol}/short-interest?assetClass=stocks"


def fetch_short_interest(symbol: str, *, use_cache: bool = True) -> list[dict]:
    """Exchange-reported short interest, one row per settlement date (twice a
    month), newest first: settlement date, shares short, average daily volume,
    days to cover. FINRA publishes it about a week and a half after settlement."""
    text = cache.fetch_text(
        NAMESPACE, f"short-interest-{symbol}",
        lambda: get_text(SHORT_INTEREST_URL.format(symbol=symbol.replace("-", ".")), timeout=20.0, retries=1,
                         user_agent=USER_AGENT, headers={"Accept": "application/json"}),
        kind="reference_data", suffix=".json", use_cache=use_cache,
    )
    payload = json.loads(text)
    rows = (((payload.get("data") or {}).get("shortInterestTable") or {}).get("rows")) or []
    out = []
    for row in rows:
        try:
            month, day, year = str(row["settlementDate"]).split("/")
            out.append({
                "date": f"{year}-{month}-{day}",
                "interest": float(str(row["interest"]).replace(",", "")),
                "avg_volume": float(str(row.get("avgDailyShareVolume") or "nan").replace(",", "")),
                "days_to_cover": float(row["daysToCover"]) if row.get("daysToCover") not in (None, "") else None,
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out
