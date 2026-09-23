"""CATALYSTS tab: what is scheduled next, and what the last session brought.

Two lanes. MACRO & BROAD INDEX: agency releases (BLS, BEA, Census) at the
time the agency publishes, Federal Reserve events from the Board's calendar,
announced Treasury coupon auctions, events that follow a fixed rule (options
expiry, jobless claims, ISM) and events kept by hand in the config. SINGLE
NAME: earnings of every S&P 500 / Nasdaq-100 member and watchlist name, with
the session timing, the consensus and the company's weight in each index.

Every event carries its source and how it is known -- an agency's published
schedule, a vendor calendar, a rule, or a hand-kept entry -- because "CPI at
8:30 on the 14th" and "ISM on the first business day" are different claims.
The event fields follow the research control tower's event contract
(``event_key``, ``scope``, ``event_type``, ``certainty_class``,
``date_precision``, ``reference_period``...) so the two can share events.
"""

from __future__ import annotations

from datetime import date, timedelta
import re

import pandas as pd

from ..compute import catalysts as C
from ..compute.returns import period_return
from ..compute.xray import ticker_key
from ..sources import calendars, fred, nasdaq, treasury
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float

# How each source's dates are known.
CERTAINTY = {
    "bls": "official_schedule", "bea": "official_schedule", "census": "official_schedule",
    "fed": "official_schedule", "treasury": "official_announcement", "rule": "rule",
    "manual": "manual", "nasdaq": "vendor_calendar",
}
EVENT_TYPE = {
    "bls": "economic_release", "bea": "economic_release", "census": "economic_release",
    "fed": "central_bank", "treasury": "treasury_auction", "rule": "market_structure",
}
RULE_TYPES = {"jobless_claims": "economic_release", "ism_manufacturing": "economic_release",
              "ism_services": "economic_release", "eia_petroleum": "industry_data"}
SOURCE_LABELS = {
    "bls": ("BLS release schedule", calendars.BLS_URL),
    "bea": ("BEA release schedule", calendars.BEA_URL),
    "census": ("Census economic indicator calendar", calendars.CENSUS_URL),
    "fed": ("Federal Reserve Board calendar", calendars.FED_URL),
    "treasury": ("Treasury announced auctions", calendars.TREASURY_URL),
}
TEN_YEAR = "10Y"
NASDAQ_GIVE_UP_AFTER = 2
BP_PER_PCT = 100


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _expected_missing(everything: list[dict], releases: list[dict], start: date) -> list[str]:
    """Releases that recur within ``expect_within_days`` but have no match that
    far ahead in their agency's calendar: the title changed, or the pattern broke."""
    missing = []
    fetched = {e["source_id"] for e in everything}
    for release in releases:
        days = release.get("expect_within_days")
        if not days or release["source"] not in fetched:
            continue
        until = (start + timedelta(days=int(days))).isoformat()
        if not any(e["source_id"] == release["source"] and start.isoformat() <= (e["date"] or "") <= until
                   and re.search(release["match"], e["title"]) for e in everything):
            missing.append(f"{release['label'] or release['match']} ({release['source']}, none within {days} days)")
    return missing


def _macro_events(ctx, start: date, end: date, use_cache: bool) -> tuple[list[dict], dict[str, str], list[dict]]:
    """Events from every macro source within the horizon, the sources that
    failed, and everything the sources returned (for the recurrence check)."""
    raw, failed, everything = [], {}, []
    fetchers = {
        "bls": lambda: calendars.fetch_bls(use_cache=use_cache),
        "bea": lambda: calendars.fetch_bea(use_cache=use_cache),
        "census": lambda: calendars.fetch_census(use_cache=use_cache),
        "fed": lambda: calendars.fetch_fed(use_cache=use_cache),
        "treasury": lambda: calendars.fetch_treasury(since=start.isoformat(), use_cache=use_cache),
    }
    for source, fetch in fetchers.items():
        try:
            events = fetch()
        except Exception as exc:
            failed[source] = str(exc)[:ERROR_DETAIL_CHARS]
            continue
        everything.extend(events)
        label, url = SOURCE_LABELS[source]
        kept = [e for e in events if e["date"] and start.isoformat() <= e["date"] <= end.isoformat()]
        ctx.log.add(SourceRecord(f"catalysts_{source}", label, url, rows=len(kept),
                                 observed_date=ctx.as_of, policy="daily_close"))
        raw.extend(kept)
    raw.extend(C.rule_events(start, end))
    return raw, failed, everything


def _match(event: dict, releases: list[dict]) -> dict | None:
    for release in releases:
        if release["source"] == event["source_id"] and re.search(release["match"], event["title"]):
            return release
    return None


def _prints(specs: list[dict], use_cache: bool, cache: dict) -> list[dict]:
    out = []
    for spec in specs or []:
        series = spec["series"]
        if series not in cache:
            try:
                cache[series] = fred.fetch_series(series, use_cache=use_cache)[0]
            except Exception:
                cache[series] = None
        frame = cache[series]
        latest = C.latest_print(frame, spec["transform"]) if frame is not None else None
        scale = float(spec.get("scale", 1.0))
        out.append({
            "label": spec["label"], "series": series, "unit": spec.get("unit", ""),
            "decimals": int(spec.get("decimals", 1)), "transform": C.TRANSFORMS[spec["transform"]],
            "value": clean_float(latest["value"] * scale, 4) if latest else None,
            "period": latest["period"] if latest else None,
        })
    return out


def _macro(ctx, settings: dict, start: date, end: date, use_cache: bool) -> tuple[list[dict], dict[str, str], list[str]]:
    raw, failed, everything = _macro_events(ctx, start, end, use_cache)
    series_cache: dict = {}
    events, seen = [], set()
    for event in raw:
        release = _match(event, settings["releases"])
        if release is None:
            continue
        title = release["label"] or event["title"]
        key = f"{event['source_id']}:{event['date']}:{_slug(title)}"
        if key in seen:
            continue
        seen.add(key)
        detail = event.get("detail") or event.get("description")
        events.append({
            "event_key": key,
            "lane": "macro",
            "scope": "us_macro",
            "event_type": RULE_TYPES.get(event.get("rule"), EVENT_TYPE.get(event["source_id"], "other")),
            "title": title,
            "source_title": event["title"],
            "date": event["date"],
            "time": event["time"],
            "date_precision": "datetime" if event["time"] else "day",
            "certainty_class": CERTAINTY[event["source_id"]],
            "importance": release["importance"],
            "source_id": event["source_id"],
            "source_url": event["url"],
            "reference_period": event.get("reference_period"),
            "detail": detail,
            "prints": _prints(release.get("prints"), use_cache, series_cache),
        })
    for item in settings.get("manual") or []:
        if start.isoformat() <= item["date"] <= end.isoformat():
            events.append({
                "event_key": f"manual:{item['date']}:{_slug(item['title'])}",
                "lane": "macro", "scope": "us_macro", "event_type": item.get("event_type", "other"),
                "title": item["title"], "source_title": item["title"], "date": item["date"],
                "time": item.get("time"), "date_precision": item.get("date_precision", "day"),
                "certainty_class": "manual", "importance": item.get("importance", "medium"),
                "source_id": "manual", "source_url": item.get("source_url"),
                "reference_period": None, "detail": item.get("detail"), "prints": [],
            })
    return events, failed, _expected_missing(everything, settings["releases"], start)


def _universe(ctx) -> dict[str, dict]:
    """Every index member and watchlist name, by ticker key, with its weights."""
    names: dict[str, dict] = {}
    for key, frame in ctx.members.items():
        for row in frame.drop_duplicates("yahoo_symbol").itertuples():
            entry = names.setdefault(ticker_key(row.yahoo_symbol), {
                "symbol": row.yahoo_symbol, "name": str(row.name).title(), "sector": row.sector,
                "weights": {}, "watchlist": False,
            })
            entry["weights"][key] = float(row.weight)
    for row in ctx.watchlist.itertuples():
        entry = names.setdefault(ticker_key(row.ticker), {
            "symbol": row.ticker, "name": row.label or row.name, "sector": row.sector,
            "weights": {}, "watchlist": True,
        })
        entry["watchlist"] = True
    return names


def _earnings(ctx, settings: dict, dates: list[date], use_cache: bool) -> tuple[list[dict], list[str]]:
    names = _universe(ctx)
    events, failed = [], []
    misses = 0
    for day in dates:
        # Two misses in a row means the endpoint is refusing this client, not
        # having a bad date: the rest are listed as not fetched instead of each
        # waiting out its own timeout.
        if misses >= NASDAQ_GIVE_UP_AFTER:
            failed.append(day.isoformat())
            continue
        try:
            rows = nasdaq.fetch_earnings(day.isoformat(), use_cache=use_cache)
            misses = 0
        except Exception:
            failed.append(day.isoformat())
            misses += 1
            continue
        for row in rows:
            entry = names.get(ticker_key(row["symbol"]))
            if entry is None:
                continue
            weight = max(entry["weights"].values(), default=None)
            importance = C.earnings_importance(
                weight, settings["earnings_high_weight"], settings["earnings_medium_weight"])
            events.append({
                "event_key": f"nasdaq:{day.isoformat()}:{entry['symbol']}",
                "lane": "single_name", "scope": "us_equity", "event_type": "earnings",
                "title": f"{entry['symbol']} earnings", "symbol": entry["symbol"], "name": entry["name"],
                "sector": entry["sector"], "date": day.isoformat(), "time": None, "timing": row["timing"],
                "date_precision": "session" if row["timing"] else "day",
                "certainty_class": "vendor_calendar", "importance": importance,
                "source_id": "nasdaq", "source_url": nasdaq.PAGE_URL,
                "index_weights": {k: clean_float(v, 3) for k, v in entry["weights"].items()},
                "watchlist": entry["watchlist"],
                "eps_forecast": row["eps_forecast"], "estimates": row["estimates"],
                "last_year_eps": row["last_year_eps"], "fiscal_quarter": row["fiscal_quarter"],
                "eps": row["eps"], "surprise_pct": row["surprise_pct"],
            })
    return events, failed


def _ten_year_change(use_cache: bool) -> dict | None:
    """The 10-year par yield's latest daily change, in basis points."""
    try:
        curve, _ = treasury.fetch_par_yield_curve()
    except Exception:
        return None
    ten = curve[curve["tenor"] == TEN_YEAR].sort_values("date")
    if len(ten) < 2:
        return None
    last, before = ten.iloc[-1], ten.iloc[-2]
    return {"date": pd.Timestamp(last["date"]).strftime("%Y-%m-%d"), "level": clean_float(last["yield_pct"], 2),
            "change_bp": clean_float((last["yield_pct"] - before["yield_pct"]) * BP_PER_PCT, 1)}


def _recent(ctx, macro: list[dict], earnings: list[dict], session: date, previous: date, use_cache: bool) -> dict:
    """The last session: what was released, who reported, how they traded."""
    today, prior = session.isoformat(), previous.isoformat()

    def one_day(symbol):
        return clean_float(period_return(ctx.closes[symbol], 1), 2) if symbol in ctx.closes.columns else None

    reacted, after_close = [], []
    for event in earnings:
        if (event["date"] == today and event["timing"] != "amc") or (event["date"] == prior and event["timing"] == "amc"):
            reacted.append({**event, "return_1d": one_day(event["symbol"])})
        elif event["date"] == today and event["timing"] == "amc":
            after_close.append(event)
    spx = ctx.index_closes["^GSPC"] if "^GSPC" in ctx.index_closes.columns else None
    return {
        "session": today,
        "previous_session": prior,
        "macro": [e for e in macro if e["date"] == today],
        "earnings_reacted": sorted(reacted, key=lambda e: -max(e["index_weights"].values(), default=0)),
        "earnings_after_close": sorted(after_close, key=lambda e: -max(e["index_weights"].values(), default=0)),
        "market": {
            "spx_1d": clean_float(period_return(spx, 1), 2) if spx is not None else None,
            "ten_year": _ten_year_change(use_cache),
        },
    }


def _week(sessions: list[date], events: list[dict], start: date) -> list[dict]:
    """The strip: each coming session, plus any holiday between them."""
    days, end = [], sessions[-1]
    day = start + timedelta(days=1)
    while day <= end:
        holidays = C.nyse_holidays(day.year)
        early = C.nyse_early_closes(day.year)
        if day.weekday() < C.SATURDAY:
            on_day = [e for e in events if e["date"] == day.isoformat()]
            days.append({
                "date": day.isoformat(),
                "status": "holiday" if day in holidays else "early_close" if day in early else "open",
                "note": holidays.get(day) or early.get(day),
                "macro": sum(e["lane"] == "macro" for e in on_day),
                "macro_high": sum(e["lane"] == "macro" and e["importance"] == "high" for e in on_day),
                "earnings": sum(e["lane"] == "single_name" for e in on_day),
                "earnings_high": sum(e["lane"] == "single_name" and e["importance"] == "high" for e in on_day),
            })
        day += timedelta(days=1)
    return days


def build(ctx, *, use_cache: bool = True) -> dict:
    settings = ctx.config["catalysts"]
    session = date.fromisoformat(ctx.as_of)
    previous = next(d for d in (session - timedelta(days=k) for k in range(1, 10)) if C.is_session(d))
    end = session + timedelta(days=int(settings["horizon_days"]))

    macro, failed, expected_missing = _macro(ctx, settings, session, end, use_cache)
    earnings_dates = [previous] + C.sessions(session, end)
    earnings, earnings_failed = _earnings(ctx, settings, earnings_dates, use_cache)
    ctx.log.add(SourceRecord(
        "catalysts_nasdaq_earnings", "Nasdaq earnings calendar (unofficial)", nasdaq.PAGE_URL,
        rows=len(earnings), observed_date=ctx.as_of, policy="daily_close",
        status="ok" if not earnings_failed else ("error" if len(earnings_failed) == len(earnings_dates) else "partial"),
        error=f"dates not fetched: {', '.join(earnings_failed)}" if earnings_failed else None,
    ))

    upcoming = sorted(
        [e for e in macro + earnings if e["date"] > session.isoformat()],
        key=lambda e: (e["date"], e.get("time") or "99:99", e["lane"], e["title"]),
    )
    week_sessions = C.next_sessions(session, int(settings["week_sessions"]))
    return {
        "as_of": ctx.as_of,
        "horizon_end": end.isoformat(),
        "week_sessions": [d.isoformat() for d in week_sessions],
        "week": _week(week_sessions, upcoming, session),
        "events": upcoming,
        "recent": _recent(ctx, macro, earnings, session, previous, use_cache),
        "expected_missing": expected_missing,
        "failed_sources": {**failed, **({"nasdaq": f"dates not fetched: {', '.join(earnings_failed)}"} if earnings_failed else {})},
        "certainty_labels": {
            "official_schedule": "agency's published schedule",
            "official_announcement": "announced by Treasury",
            "rule": "computed from a fixed rule",
            "manual": "kept by hand",
            "vendor_calendar": "Nasdaq calendar; not marked company-confirmed",
        },
        "note": (
            "Times are New York. Agency releases are at the time each agency publishes; Treasury "
            "announces coupon auctions about a week ahead, so auctions further out are not listed yet. "
            "Events marked 'rule' are computed (options expiry on the third Friday, claims every "
            "Thursday, ISM on the first and third business day) with the holiday shifts the rule "
            "defines. Earnings dates are Nasdaq's calendar, an unofficial source that does not say "
            "whether a date is company-confirmed. Previous prints are FRED's latest observation for "
            "the period shown -- until FRED updates after a release, that is the print before it. "
            "Importance for earnings is the company's weight in either index."
        ),
    }
