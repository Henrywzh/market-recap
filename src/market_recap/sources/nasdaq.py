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


def fetch_earnings(date: str, *, use_cache: bool = True) -> list[dict]:
    text = cache.fetch_text(
        NAMESPACE, f"earnings-{date}",
        lambda: get_text(EARNINGS_URL.format(date=date), timeout=30.0, user_agent=USER_AGENT,
                         headers={"Accept": "application/json"}),
        kind="daily_file", suffix=".json", use_cache=use_cache,
    )
    return parse_earnings(text)
