"""Scheduled US macro events from the agencies' own calendars.

Each agency publishes its release schedule with the time of day, which a
data vendor's calendar reduces to a date: BLS and BEA as iCalendar feeds,
Census as a table, the Federal Reserve as a JSON calendar that carries FOMC
statements, press conferences, minutes and Board speeches, and Treasury as an
API of announced auctions. Nothing here is inferred -- a release time is the
agency's -- and every event keeps the URL it came from.

An event is a plain dict: ``source_id``, ``title``, ``date`` (ISO), ``time``
("HH:MM" New York, or None), ``reference_period`` and ``url``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import re
from zoneinfo import ZoneInfo

from .. import cache
from ..config import MARKET_TIMEZONE
from .http import get_text

NAMESPACE = "calendars"
NEW_YORK = ZoneInfo(MARKET_TIMEZONE)

BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
CENSUS_URL = "https://www.census.gov/economic-indicators/calendar-listview.html"
FED_URL = "https://www.federalreserve.gov/json/calendar.json"
TREASURY_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/"
    "upcoming_auctions?sort=-auction_date&page%5Bsize%5D=100"
)

BLS_PAGE = "https://www.bls.gov/schedule/news_release/"
BEA_PAGE = "https://www.bea.gov/news/schedule"
FED_PAGE = "https://www.federalreserve.gov/newsevents/calendar.htm"
TREASURY_PAGE = "https://www.treasurydirect.gov/auctions/upcoming/"

# Coupon auctions only: bills are auctioned several times a week and would
# bury the calendar. Competitive bidding closes at 1:00 p.m. for these.
COUPON_TYPES = {"Note", "Bond", "TIPS", "FRN"}
COUPON_AUCTION_CLOSE = "13:00"


# A calendar is small and either answers promptly or is refusing this client;
# an edge that holds a refused connection open would otherwise cost the full
# retry ladder on every build.
CALENDAR_TIMEOUT_SECONDS = 30.0
CALENDAR_RETRIES = 1


def _text(name: str, url: str, *, use_cache: bool) -> str:
    return cache.fetch_text(
        NAMESPACE, name,
        lambda: get_text(url, timeout=CALENDAR_TIMEOUT_SECONDS, retries=CALENDAR_RETRIES),
        kind="daily_file", suffix=".txt", use_cache=use_cache,
    )


def _event(source_id: str, title: str, when: datetime | None, day: str | None, url: str,
           reference_period: str | None = None, **extra) -> dict:
    if when is not None:
        local = when.astimezone(NEW_YORK)
        day, time = local.date().isoformat(), local.strftime("%H:%M")
    else:
        time = None
    return {"source_id": source_id, "title": title, "date": day, "time": time,
            "reference_period": reference_period, "url": url, **extra}


# --- iCalendar (BLS, BEA) ------------------------------------------------------

_VEVENT = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.S)


def _ics_field(block: str, name: str) -> tuple[str, str] | None:
    """(parameters, value) of the first ``name`` property in a VEVENT block."""
    match = re.search(rf"^{name}([^:\n]*):(.*)$", block, re.M)
    return (match.group(1), match.group(2).strip()) if match else None


def _ics_time(params: str, value: str) -> datetime | None:
    """A DTSTART in UTC (``...Z``) or in the feed's Eastern zone."""
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if "T" in value:
            return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=NEW_YORK)
    except ValueError:
        return None
    return None


def parse_ics(text: str, source_id: str, page: str) -> list[dict]:
    # Unfold continuation lines (RFC 5545: CRLF followed by a space).
    text = re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n")
    events = []
    for block in _VEVENT.findall(text):
        start, summary = _ics_field(block, "DTSTART"), _ics_field(block, "SUMMARY")
        if not start or not summary:
            continue
        when = _ics_time(*start)
        if when is None:
            continue
        title = summary[1].replace("\\,", ",").replace("\\;", ";").strip()
        # BEA writes "Personal Income and Outlays, August 2026": the period after the last comma.
        period = None
        match = re.match(r"^(.*),\s*((?:January|February|March|April|May|June|July|August|September|October|"
                         r"November|December|\d(?:st|nd|rd|th) Quarter)\b.*)$", title)
        if match:
            title, period = match.group(1).strip(), match.group(2).strip()
        events.append(_event(source_id, title, when, None, page, period))
    return events


def fetch_bls(*, use_cache: bool = True) -> list[dict]:
    return parse_ics(_text("bls", BLS_URL, use_cache=use_cache), "bls", BLS_PAGE)


def fetch_bea(*, use_cache: bool = True) -> list[dict]:
    return parse_ics(_text("bea", BEA_URL, use_cache=use_cache), "bea", BEA_PAGE)


# --- Census ----------------------------------------------------------------------

def parse_census(text: str) -> list[dict]:
    """The indicator calendar table: title, date, time, period covered."""
    events = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 4:
            continue
        try:
            when = datetime.strptime(f"{cells[1]} {cells[2]}", "%B %d, %Y %I:%M %p").replace(tzinfo=NEW_YORK)
        except ValueError:
            continue
        events.append(_event("census", cells[0], when, None, CENSUS_URL, cells[3] or None))
    return events


def fetch_census(*, use_cache: bool = True) -> list[dict]:
    return parse_census(_text("census", CENSUS_URL, use_cache=use_cache))


# --- Federal Reserve ----------------------------------------------------------------

def _fed_time(value: str) -> str | None:
    match = re.match(r"(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", (value or "").strip(), re.I)
    if not match:
        return None
    hour = int(match.group(1)) % 12 + (12 if match.group(3).lower() == "p" else 0)
    return f"{hour:02d}:{match.group(2)}"


def parse_fed(text: str) -> list[dict]:
    """The Board's calendar feed. ``days`` is one day, a list, or a range; a
    range (a conference) is dated by its first day."""
    events = []
    for item in json.loads(text.lstrip("﻿")).get("events", []):
        month, days = item.get("month") or "", str(item.get("days") or "")
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            continue
        description = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(item.get("description") or ""))).strip()
        for day in re.findall(r"\d{1,2}", days.split("-")[0] if "-" in days else days):
            events.append({
                "source_id": "fed", "title": (item.get("title") or "").strip(), "date": f"{month}-{int(day):02d}",
                "time": _fed_time(item.get("time") or ""), "reference_period": None, "url": FED_PAGE,
                "fed_type": item.get("type"), "description": re.sub(r"\s+", " ", description) or None,
            })
    return events


def fetch_fed(*, use_cache: bool = True) -> list[dict]:
    return parse_fed(_text("fed", FED_URL, use_cache=use_cache))


# --- Treasury auctions ----------------------------------------------------------------

def parse_treasury(text: str, *, since: str) -> list[dict]:
    """Announced coupon auctions from ``since`` on. Treasury announces each a
    few days ahead, so this reaches about a week out and no further."""
    events = []
    for row in json.loads(text).get("data", []):
        if row.get("security_type") not in COUPON_TYPES or (row.get("auction_date") or "") < since:
            continue
        amount = row.get("offering_amt")
        size = f"${float(amount) / 1e9:,.0f}bn" if amount not in (None, "", "null") else "size not yet announced"
        reopening = " reopening" if row.get("reopening") == "Yes" else ""
        events.append({
            "source_id": "treasury",
            "title": f"{row['security_term']} {row['security_type']} auction{reopening}",
            "date": row["auction_date"], "time": COUPON_AUCTION_CLOSE,
            "reference_period": None, "url": TREASURY_PAGE,
            "detail": f"{size}; announced {row.get('announcemt_date') or 'n/a'}",
        })
    return events


def fetch_treasury(*, since: str, use_cache: bool = True) -> list[dict]:
    return parse_treasury(_text("treasury_auctions", TREASURY_URL, use_cache=use_cache), since=since)
