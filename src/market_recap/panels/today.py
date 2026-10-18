"""TODAY: what just came out, what is due in the next three sessions, and what is unusual now.

Nothing here is a new data source. Every list is cut from the artifacts this
build has already written for the same session: the calendar (CATALYSTS), each
stock's move against its own volatility (MOVES), the market-state and risk
readings, the anchor exposure, the put/call ratio and buyback blackout
(POSITIONING), the MONITOR queue, the hand-kept catalyst log, theme data due
dates, and the options-implied moves (EVIDENCE and the per-name event cards).

A missing input leaves its lists empty and is named in ``unavailable``; it
never stops the build. The page and the MCP tool read the result as it is,
so the ordering below is final.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
from urllib.parse import urljoin

from ..compute import catalysts as C
from ..compute.risk import breach
from ..config import EVENTS_ARTIFACT_DIR
from ..sources.http import get_text
from ..util import describe_error

# Panels TODAY reads, all required to be from this session (build passes them as inputs).
INPUTS = ("catalysts", "moves", "market_state", "risk", "anchor", "positioning", "monitor", "catalyst_log", "themes", "evidence")
IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}
# Calendar event types shown under their own kind; every other macro type is "macro".
EVENT_KINDS = {"central_bank": "fed", "treasury_auction": "auction"}
# A move this many times its own volatility is "high" importance; the threshold itself is in [moves].
BIG_MOVE_SIGMA = 3.0
# The previous published TODAY is an optional read; a slow host must not hold up the build.
PREVIOUS_STATE_TIMEOUT = 10.0
SESSIONS_AHEAD = 3
# Sessions counted back, including the session itself, for "just came out" catalyst-log items.
RECENT_LOG_SESSIONS = 3


# --- small value helpers -----------------------------------------------------

def _number(value) -> float | None:
    """A finite float, or None: NaN and infinity are not valid JSON."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ratio(numerator, denominator) -> float | None:
    top, bottom = _number(numerator), _number(denominator)
    if top is None or not bottom:
        return None
    return top / bottom


def _fmt(value, unit=None, decimals=None) -> str:
    """A value as the page prints it. A probability is shown as a percent."""
    number = _number(value)
    if number is None:
        return "n/a"
    if unit == "p":
        return f"{number * 100:.0f}%"
    places = 1 if decimals is None else int(decimals)
    joiner = "" if unit in (None, "%") else " "
    return f"{number:.{places}f}{joiner}{unit or ''}"


def _signed(value) -> str:
    number = _number(value)
    return "n/a" if number is None else f"{number:+.1f}%"


def _spx_weight(event: dict) -> float:
    """S&P 500 index weight in percent, zero when the event carries none."""
    return _number((event.get("index_weights") or {}).get("SPX")) or 0.0


def _session_back(day: date, count: int) -> date:
    """The session ``count`` NYSE sessions before ``day``."""
    out = day
    for _ in range(count):
        out -= timedelta(days=1)
        while not C.is_session(out):
            out -= timedelta(days=1)
    return out


def _percentile_in(sample: list[float], value: float) -> float:
    """Share of the sample below the value, ties counted half: the way the page ranks put/call."""
    below = sum(1 for v in sample if v < value)
    same = sum(1 for v in sample if v == value)
    return 100 * (below + same / 2) / len(sample)


def _item(kind: str, subject: str, day: str, title: str, *, link: str, importance: str = "medium",
          detail: str | None = None, value=None, unit: str | None = None, z=None, new: bool = False,
          time: str | None = None, timing: str | None = None, since: str | None = None,
          days: int | None = None, evidence: str = "description", extra: dict | None = None) -> dict:
    """One list entry in the contract's shape. The key is kind:subject:date, stable across rebuilds."""
    return {
        "key": f"{kind}:{subject}:{day}", "kind": kind, "date": day, "time": time, "timing": timing,
        "subject": subject, "title": title, "detail": detail, "value": _number(value), "unit": unit,
        "z": _number(z), "importance": importance, "new": bool(new), "since": since, "days": days,
        "evidence": evidence, "link": link, "extra": extra or {},
    }


def _order(items: list[dict]) -> list[dict]:
    """New before ongoing, then importance, then the largest size (|z|), then time of day."""
    return sorted(items, key=lambda i: (
        not i["new"],
        IMPORTANCE_RANK.get(i["importance"], 3),
        -abs(i["z"]) if i["z"] is not None else 0.0,
        i["time"] or "99:99",
    ))


# --- just out ----------------------------------------------------------------

def _event_kind(event: dict) -> str:
    if event.get("rule") in C.EXPIRY_RULES_SHOWN:
        return "expiry"
    return EVENT_KINDS.get(event.get("event_type"), "macro")


def _just_out_macro(event: dict) -> dict:
    prints = event.get("prints") or []
    lead = prints[0] if prints else {}
    if _event_kind(event) == "expiry":
        title = f"{event['title']} settled this session"
    elif lead.get("label"):
        title = f"{event['title']}: {lead['label']} {_fmt(lead.get('value'), lead.get('unit'), lead.get('decimals'))}"
    else:
        title = f"{event['title']} came out"
    return _item(_event_kind(event), event["title"], event["date"], title, link="#catalysts",
                 importance=event.get("importance") or "low", time=event.get("time"),
                 detail=f"For {lead['period']}" if lead.get("period") else None,
                 # Rounded as the title prints it, so the row does not show 0.7% and 0.66%.
                 value=_rounded(lead.get("value"), lead.get("decimals")), unit=lead.get("unit"), new=True,
                 extra={"prints": prints, "expectations": event.get("expectations") or []})


def _rounded(value, decimals):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or decimals is None:
        return value
    return round(value, int(decimals))


def _earnings_item(row: dict, moves_by: dict, *, after_close: bool) -> dict:
    symbol = row["symbol"]
    ret = _number(row.get("return_1d"))
    z = _ratio(ret, (moves_by.get(symbol) or {}).get("sigma_pct"))
    extra = {"weight": _spx_weight(row), "eps": row.get("eps"), "eps_forecast": row.get("eps_forecast"),
             "surprise_pct": row.get("surprise_pct"), "return_1d": ret}
    if after_close:
        return _item("earnings", symbol, row["date"], f"{symbol} reports after the close", link=f"#ticker/{symbol}",
                     importance=row.get("importance") or "low", timing=row.get("timing"), extra=extra)
    surprise = _number(row.get("surprise_pct"))
    verdict = "reported" if surprise is None else "beat" if surprise > 0 else "missed" if surprise < 0 else "matched"
    title = f"{symbol} {verdict} expected EPS: {_fmt(row.get('eps'), decimals=2)} against {_fmt(row.get('eps_forecast'), decimals=2)}"
    return _item("earnings", symbol, row["date"], title, link=f"#ticker/{symbol}",
                 importance=row.get("importance") or "low", detail=f"Shares {_signed(ret)} on the session",
                 value=surprise, unit="%", z=z, new=True, extra=extra)


def _just_out_earnings(reacted: list, after_close: list, moves_by: dict) -> list[dict]:
    """Reported names first, largest index weight first (the page's order)."""
    rows = [_earnings_item(r, moves_by, after_close=False) for r in reacted if _number(r.get("eps")) is not None]
    rows += [_earnings_item(r, moves_by, after_close=True) for r in after_close if r.get("symbol")]
    return sorted(rows, key=lambda i: (-(i["extra"]["weight"] or 0.0), i["subject"]))


# --- coming up ---------------------------------------------------------------

def _expectation_text(expectations: list) -> str | None:
    """The first two expectations, as "Source Label value", for the row's second line."""
    shown = [" ".join(part for part in (e.get("source_label") or e.get("source"), e.get("label"),
                                        _fmt(e.get("value"), e.get("unit"), e.get("decimals"))) if part)
             for e in expectations[:2] if _number(e.get("value")) is not None]
    return f"Expected: {'; '.join(shown)}" if shown else None


def _coming_macro(event: dict) -> dict:
    kind = _event_kind(event)
    expectations = event.get("expectations") or []
    lead = next((e for e in expectations if e.get("kind") == "survey"), expectations[0] if expectations else {})
    importance = "high" if event.get("expiry_watch") else (event.get("importance") or "low")
    extra = {"expiry_watch": event.get("expiry_watch")} if event.get("expiry_watch") else {}
    if kind == "expiry":
        return _item(kind, event["title"], event["date"], event["title"], link="#catalysts", importance=importance,
                     time=event.get("time"), detail=event.get("detail"), extra={"rule": event.get("rule"), **extra})
    title = event["title"] + (f" at {event['time']}" if event.get("time") else "")
    return _item(kind, event["title"], event["date"], title, link="#catalysts", importance=importance,
                 time=event.get("time"), detail=_expectation_text(expectations), value=lead.get("value"),
                 unit=lead.get("unit"), extra={"expectations": expectations, **extra})


def _implied(symbol: str, evidence: dict, events_dir: Path) -> tuple[float | None, dict]:
    """The options-implied move in percent, and the option block it came from.

    Evidence holds the options snapshot for the focus names; a per-name event card
    holds the same figure for the names it was built for. Absent in both, None.
    """
    options = ((evidence.get("names") or {}).get(symbol) or {}).get("options") or {}
    implied = options.get("implied_move") or _card_implied(events_dir, symbol)
    if not implied:
        return None, {}
    return _number(implied.get("straddle_pct")), {"implied_expiry": implied.get("expiry"),
                                                   "snapshot_day": implied.get("snapshot_day") or options.get("snapshot_day")}


def _card_implied(events_dir: Path, symbol: str) -> dict | None:
    try:
        card = json.loads((events_dir / f"{symbol}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return ((card.get("card") or {}).get("priced") or {}).get("implied")


def _coming_earnings(event: dict, evidence: dict, events_dir: Path) -> dict:
    symbol = event["symbol"]
    implied_pct, implied_extra = _implied(symbol, evidence, events_dir)
    when = {"bmo": "before the open", "amc": "after the close"}.get(event.get("timing"))
    title = f"{symbol} reports {when}" if when else f"{symbol} reports"
    detail = f"EPS forecast {_fmt(event.get('eps_forecast'), decimals=2)}" if _number(event.get("eps_forecast")) is not None else None
    if implied_pct is not None:
        detail = f"{detail}; options price a {implied_pct:.1f}% move" if detail else f"Options price a {implied_pct:.1f}% move"
    return _item("earnings", symbol, event["date"], title, link=f"#ticker/{symbol}",
                 importance=event.get("importance") or "low", timing=event.get("timing"), detail=detail,
                 value=implied_pct, unit="%" if implied_pct is not None else None,
                 extra={"eps_forecast": event.get("eps_forecast"), "weight": _spx_weight(event),
                        "watchlist": bool(event.get("watchlist")), "estimates": event.get("estimates"),
                        **implied_extra})


def _calendar_item(event: dict, cfg: dict, evidence: dict, events_dir: Path) -> dict | None:
    """One calendar event as a TODAY item, or None when it is not listed."""
    if event.get("lane") == "macro":
        listed = event.get("rule") in C.EXPIRY_RULES_SHOWN or event.get("importance") in ("high", "medium")
        return _coming_macro(event) if listed else None
    if event.get("event_type") != "earnings" or not event.get("symbol"):
        return None
    if _spx_weight(event) < cfg["earnings_min_weight"] and not event.get("watchlist"):
        return None
    return _coming_earnings(event, evidence, events_dir)


def _theme_items(themes: dict, sessions: list[str]) -> dict[str, list[dict]]:
    """Theme data releases due each session, one per title (groups repeat each other's)."""
    out = {day: [] for day in sessions}
    seen: set[str] = set()
    for group in themes.get("groups") or []:
        key = group.get("key") or ""
        for entry in group.get("calendar") or []:
            title = entry.get("title") or entry.get("symbol")
            day = entry.get("date")
            if entry.get("kind") != "data" or day not in out or not title or title in seen:
                continue
            seen.add(title)
            detail = f"{group.get('label') or key}" + ("; overdue" if entry.get("late") else "")
            out[day].append(_item("theme_data", title, day, title, link=f"#themes/{key.upper()}.DATA",
                                  detail=detail, extra={"group": key}))
    return out


def _coming_up(catalysts: dict, themes: dict, evidence: dict, sessions: list[str], cfg: dict,
               as_of: str, events_dir: Path) -> dict:
    events = [e for e in catalysts.get("events") or [] if e.get("date")]
    by_day: dict[str, list[dict]] = {day: [] for day in sessions}
    for event in events:
        if event["date"] in by_day:
            item = _calendar_item(event, cfg, evidence, events_dir)
            if item:
                by_day[event["date"]].append(item)
    for day, items in _theme_items(themes, sessions).items():
        by_day[day].extend(items)

    until = (date.fromisoformat(as_of) + timedelta(days=cfg["later_days"])).isoformat()
    last_session = sessions[-1]
    later = []
    for event in events:
        if last_session < event["date"] <= until and event.get("importance") == "high":
            item = _calendar_item(event, cfg, evidence, events_dir)
            if item:
                later.append(item)
    later.sort(key=lambda i: (i["date"], i["time"] or "99:99"))
    return {
        "days": [{"date": day, "items": _order(by_day[day])} for day in sessions],
        "later": later,
        "later_until": until,
    }


# --- unusual: moves ----------------------------------------------------------

def _tested(row: dict, states: list[dict]) -> bool:
    """Whether the frozen research table has a row this shock falls in (same direction, same tags)."""
    direction = row.get("direction")
    if not direction:
        return False
    tags = row.get("tags") or {}
    return any(
        state.get("direction") == direction
        and all(tags.get(k) == v for k, v in (state.get("match") or {}).items())
        for state in states
    )


def _move_item(row: dict, states: list[dict], as_of: str) -> dict | None:
    ticker = row.get("ticker")
    ret, z, z_own = _number(row.get("ret_pct")), _number(row.get("z")), _number(row.get("z_own"))
    if not ticker or ret is None or z is None:
        return None
    own, market, sector = _number(row.get("own_pct")), _number(row.get("market_pct")), _number(row.get("sector_pct"))
    detail_parts = ["reports this session" if row.get("reported") else None,
                    f"own part {_signed(own)}" if own is not None else None,
                    f"market {_signed(market)}, sector {_signed(sector)}" if market is not None and sector is not None else None]
    biggest = max(abs(z), abs(z_own or 0.0))
    verb = "fell" if ret < 0 else "rose"
    return _item("move", ticker, as_of, f"{ticker} {verb} {abs(ret):.1f}%, {abs(z):.1f} times its usual move",
                 link=f"#ticker/{ticker}", importance="high" if biggest >= BIG_MOVE_SIGMA else "medium",
                 detail="; ".join(p for p in detail_parts if p) or None, z=z, new=True,
                 evidence="tested" if _tested(row, states) else "description",
                 extra={"ret_pct": ret, "own_pct": own, "z_own": z_own, "market_pct": market,
                        "sector_pct": sector, "direction": row.get("direction"), "reported": row.get("reported"),
                        "sigma_pct": _number(row.get("sigma_pct"))})


def _sector_item(selloff: dict, sector: str, as_of: str) -> dict | None:
    if not selloff or not selloff.get("active"):
        return None
    fund = selloff.get("fund") or "sector fund"
    spy_z = _number(selloff.get("spy_z"))
    detail = f"The market was at {spy_z:.1f} times its usual move" if spy_z is not None else None
    return _item("sector_selloff", fund, as_of, f"{sector} sold off on its own: {fund} down while the broad market was not",
                 link="#sectors", importance="high", detail=detail, z=selloff.get("z"), new=True,
                 evidence="tested", extra={"losers": selloff.get("losers") or []})


def _move_items(moves: dict, cfg: dict, sector: str, as_of: str) -> list[dict]:
    states = (moves.get("move_states") or {}).get("rows") or []
    rows = {r.get("ticker"): r for r in moves.get("rows") or [] if r.get("ticker")}
    names = [item for item in (_move_item(rows[t], states, as_of) for t in moves.get("unusual") or [] if t in rows) if item]
    names = _order(names)[: cfg["max_moves"]]
    sector_item = _sector_item(moves.get("sector_selloff") or {}, sector, as_of)
    return _order(names + ([sector_item] if sector_item else []))


# --- unusual: states, risk, anchor, positioning ------------------------------

def _market_items(market_state: dict, as_of: str, previous_active: set[str] | None) -> tuple[list, list, set[str]]:
    """(started or ended this session, ongoing, active keys). Ended needs yesterday's active set."""
    changed, ongoing, active = [], [], set()
    for state in (market_state or {}).get("states") or []:
        key, label = state["key"], state.get("label") or state["key"]
        days_now = int(state.get("days_now") or 0)
        if state.get("active_now"):
            active.add(key)
            extra = {"state": key, "active": True}
            if days_now == 1:
                changed.append(_item("market_state", label, as_of, f"{label.capitalize()} started this session",
                                     link="#markets", detail=state.get("rule"), since=as_of, days=1,
                                     new=True, evidence="tested", extra=extra))
            elif days_now > 1:
                since = _session_back(date.fromisoformat(as_of), days_now - 1).isoformat()
                ongoing.append(_item("market_state", label, as_of, f"{label.capitalize()} has held for {days_now} sessions",
                                     link="#markets", detail=state.get("rule"), since=since, days=days_now,
                                     evidence="tested", extra=extra))
        elif previous_active is not None and key in previous_active:
            changed.append(_item("market_state", label, as_of, f"{label.capitalize()} ended this session",
                                 link="#markets", detail=state.get("rule"), new=True, evidence="tested",
                                 extra={"state": key, "active": False}))
    return changed, ongoing, active


def _risk_tiles(risk: dict) -> list[dict]:
    return [tile for section in (risk or {}).get("sections") or [] for tile in section.get("tiles") or []]


def _yesterday_breach(tile: dict) -> bool | None:
    """Whether the day before was past the line. Extreme tiles need a percentile history, so none here."""
    if tile.get("risk_when") == "extreme":
        return None
    values = (tile.get("recent") or {}).get("values") or []
    if len(values) < 2:
        return None
    return breach(_number(values[-2]), risk_when=tile.get("risk_when"), threshold=_number(tile.get("threshold")))


def _risk_item(tile: dict, as_of: str, now: bool, *, new: bool) -> dict:
    label = tile.get("label") or tile["key"]
    value, unit, line = _number(tile.get("value")), tile.get("unit"), _number(tile.get("threshold"))
    if tile.get("risk_when") == "extreme":
        detail = f"{_fmt(value, unit)} now; the line is a tail of its own history"
    else:
        side = "above" if tile.get("risk_when") == "high" else "below"
        detail = f"{_fmt(value, unit)} now; line {side} {_fmt(line, unit)}" if line is not None else f"{_fmt(value, unit)} now"
    if new:
        title = f"{label} moved {'into' if now else 'back out of'} its risk zone"
    else:
        title = f"{label} is still in its risk zone"
    return _item("risk", label, as_of, title, link="#risk", detail=detail, value=value, unit=unit,
                 new=new, extra={"tile": tile["key"]})


def _risk_items(risk: dict, as_of: str) -> tuple[list, list]:
    """(flips since yesterday, breaches still on). A breach only counts as a flip when yesterday is known."""
    flips, ongoing = [], []
    for tile in _risk_tiles(risk):
        now = tile.get("breach")
        if now is None:
            continue
        before = _yesterday_breach(tile)
        if before is not None and before != now:
            flips.append(_risk_item(tile, as_of, now, new=True))
        elif now:
            ongoing.append(_risk_item(tile, as_of, now, new=False))
    return flips, ongoing


def _anchor_items(anchor: dict, as_of: str) -> tuple[list, list]:
    """(exposure changed this session, exposure below full while unchanged)."""
    exposure = (anchor or {}).get("history", {}).get("exposure") or []
    if len(exposure) < 1 or _number(exposure[-1]) is None:
        return [], []
    now = _number(exposure[-1])
    before = _number(exposure[-2]) if len(exposure) >= 2 else None
    if before is not None and now != before:
        title = f"Anchor exposure moved from {_fmt(before * 100, '%', 0)} to {_fmt(now * 100, '%', 0)}"
        return [_item("anchor", "Anchor exposure", as_of, title, link="#risk", importance="medium",
                      value=now * 100, unit="%", new=True)], []
    if now < 1:
        return [], [_item("anchor", "Anchor exposure", as_of, f"Anchor exposure is {now * 100:.0f}% of a full position",
                          link="#risk", value=now * 100, unit="%")]
    return [], []


def _put_call_items(positioning: dict, cfg: dict, as_of: str) -> list[dict]:
    """The S&P 500 put/call ratio's daily reading, listed on the session it moved into either tail of its history."""
    series = next((s for s in (positioning.get("index_put_call") or {}).get("series") or []
                   if s.get("key") == "spx"), None)
    values = [_number(v) for v in ((series or {}).get("windows") or {}).get("1D", {}).get("values") or []]
    sample = [v for v in values if v is not None]
    if len(sample) < 2 or values[-1] is None:
        return []
    latest = values[-1]
    pct = _percentile_in(sample, latest)
    before = _percentile_in(sample, values[-2]) if values[-2] is not None else None
    high, low = cfg["put_call_high_pct"], cfg["put_call_low_pct"]
    now_extreme = pct >= high or pct <= low
    was_extreme = None if before is None else (before >= high or before <= low)
    if not now_extreme or was_extreme:
        return []
    title = ("Options traders are buying unusually many puts" if pct >= high
             else "Options traders are buying unusually few puts")
    return [_item("put_call", "S&P 500 put/call ratio", as_of, title, link="#positioning",
                  detail=f"Ratio {latest:.2f}, at the {pct:.0f}th percentile of its own history",
                  value=latest, unit="x", new=True, extra={"percentile": round(pct)})]


def _blackout_item(positioning: dict, as_of: str) -> dict | None:
    blackout = positioning.get("blackout") or {}
    now = _number(blackout.get("now_pct"))
    if now is None:
        return None
    windows = (blackout.get("momentum") or {}).get("windows") or []
    ahead = next((_number(w.get("ahead_delta_pp")) for w in windows if w.get("key") == "7D"), None)
    detail = f"Share changes by {ahead:+.1f} pp over the next 7 days" if ahead is not None else None
    return _item("blackout", "Buyback blackout", as_of, f"Buyback blackout covers {now:.0f}% of S&P 500 weight",
                 link="#positioning", detail=detail, value=now, unit="%", extra={"ahead_delta_pp": ahead})


# --- unusual: events ---------------------------------------------------------

def _monitor_items(monitor: dict, cfg: dict, as_of: str) -> list[dict]:
    """Names new to the MONITOR queue as one line: a dozen entries on a busy day would
    otherwise crowd out everything else under EVENTS. The tickers ride in `extra`."""
    entered = [c for c in monitor.get("changes") or [] if c.get("kind") == "entered" and c.get("ticker")]
    if not entered:
        return []
    names = [c["ticker"] for c in entered]
    shown = ", ".join(names[: cfg["max_events"]]) + (f" and {len(names) - cfg['max_events']} more"
                                                      if len(names) > cfg["max_events"] else "")
    since = monitor.get("previous_as_of")
    title = f"MONITOR queue: {len(names)} {'name' if len(names) == 1 else 'names'} entered: {shown}"
    detail = f"Compared with the build of {since}" if since else None
    return [_item("monitor", "MONITOR queue", as_of, title, link="#monitor", new=True, detail=detail,
                  value=len(names), extra={"tickers": names,
                                           "reasons": {c["ticker"]: c.get("text") for c in entered}})]


def _catalyst_items(log: dict, floor: str, as_of: str) -> list[dict]:
    out = []
    for entry in log.get("items") or []:
        day = entry.get("date")
        if not day or not entry.get("title") or not floor <= day <= as_of:
            continue
        out.append(_item("catalyst", entry.get("key") or entry["title"], day, entry["title"], link="#catalysts",
                         detail=entry.get("source"), new=day == as_of, extra={"url": entry.get("url")}))
    return out


def _reaction_items(reacted: list, moves_by: dict, cfg: dict, day: str) -> list[dict]:
    out = []
    for row in reacted:
        symbol = row.get("symbol")
        ret = _number(row.get("return_1d"))
        z = _ratio(ret, (moves_by.get(symbol) or {}).get("sigma_pct"))
        if not symbol or z is None or abs(z) < cfg["reaction_sigma"]:
            continue
        verb = "fell" if ret < 0 else "rose"
        out.append(_item("reaction", symbol, day, f"{symbol} {verb} {abs(ret):.1f}% after its report, {abs(z):.1f} times its usual move",
                         link=f"#ticker/{symbol}", importance="high" if abs(z) >= BIG_MOVE_SIGMA else "medium",
                         value=ret, unit="%", z=z, new=True,
                         extra={"surprise_pct": row.get("surprise_pct"), "eps": row.get("eps")}))
    return out


# --- previous state and history ----------------------------------------------

def _previous_payload(published_base_url: str) -> tuple[dict | None, str | None]:
    """Yesterday's published TODAY, read only when CI sets TODAY_PUBLISHED_STATE=1. Returns (payload, why not)."""
    if os.environ.get("TODAY_PUBLISHED_STATE") != "1":
        return None, "TODAY_PUBLISHED_STATE is not 1, so the published TODAY was not read"
    url = urljoin(published_base_url.rstrip("/") + "/", "artifacts/today.json")
    try:
        return json.loads(get_text(url, timeout=PREVIOUS_STATE_TIMEOUT, retries=0)), None
    except Exception as exc:
        return None, describe_error(exc)


def _previously_active(previous: dict) -> set[str]:
    """Market states active at the previous session: their started, ongoing items say so in extra."""
    unusual = previous.get("unusual") or {}
    items = (unusual.get("states") or []) + (unusual.get("ongoing") or [])
    return {i["extra"]["state"] for i in items
            if i.get("kind") == "market_state" and (i.get("extra") or {}).get("active") and i["extra"].get("state")}


def _history(previous: dict | None, as_of: str, unusual: dict, cap: int) -> list[dict]:
    """Newest first, one entry per session; this session replaces its own entry on a rebuild."""
    def slim(item: dict) -> dict:
        return {k: item.get(k) for k in ("key", "kind", "z", "new")}

    today = {"as_of": as_of, "items": [slim(i) for group in unusual.values() for i in group]}
    past = [h for h in (previous or {}).get("history") or []
            if isinstance(h, dict) and h.get("as_of") and h.get("as_of") != as_of]
    past = [{"as_of": h["as_of"], "items": [slim(i) for i in h.get("items") or []]} for h in past]
    return sorted([today] + past, key=lambda h: h["as_of"], reverse=True)[:cap]


# --- live block and assembly -------------------------------------------------

def _live(config: dict) -> dict:
    moves = config["moves"]
    return {
        "threshold_sigma": moves["threshold_sigma"],
        "market": moves["market"],
        "sector_funds": dict(config["universe"]["sectors"]),
        "max_items": config["today"]["live_max_items"],
    }


def build(ctx, *, inputs: dict, events_dir: Path = EVENTS_ARTIFACT_DIR) -> dict:
    cfg = dict(ctx.config["today"])
    as_of = ctx.as_of
    sessions = [day.isoformat() for day in C.next_sessions(date.fromisoformat(as_of), SESSIONS_AHEAD)]
    unavailable, notes = [], []
    for name in INPUTS:
        if inputs.get(name) is None:
            unavailable.append({"part": name, "reason": f"the {name} panel did not build this session"})
    src = {name: inputs.get(name) or {} for name in INPUTS}
    catalysts, moves, evidence = src["catalysts"], src["moves"], src["evidence"]
    moves_by = {r["ticker"]: r for r in moves.get("rows") or [] if r.get("ticker")}
    recent = catalysts.get("recent") or {}
    session = recent.get("session") or as_of

    previous, why_not = _previous_payload(cfg.get("published_base_url") or ctx.config["monitor"]["published_base_url"])
    previous_active = None
    if previous is None:
        unavailable.append({"part": "previous published TODAY", "reason": why_not})
        notes.append("History starts fresh: the previous published TODAY was not read, and ended states are not listed.")
    elif previous.get("as_of") == as_of:
        unavailable.append({"part": "ended states", "reason": "the published TODAY is this session's own, so yesterday is unknown"})
    else:
        previous_active = _previously_active(previous)

    sector = (ctx.config.get("moves", {}).get("sector_selloff") or {}).get("sector") or "Sector"
    market_changed, market_ongoing, _active = _market_items(src["market_state"], as_of, previous_active)
    risk_flips, risk_ongoing = _risk_items(src["risk"], as_of)
    anchor_changed, anchor_ongoing = _anchor_items(src["anchor"], as_of)
    positioning = src["positioning"]
    blackout = _blackout_item(positioning, as_of) if inputs.get("positioning") is not None else None
    floor = _session_back(date.fromisoformat(as_of), RECENT_LOG_SESSIONS - 1).isoformat()

    unusual = {
        "moves": _move_items(moves, cfg, sector, as_of),
        "states": _order(market_changed + risk_flips + anchor_changed + _put_call_items(positioning, cfg, as_of)),
        "events": _order(_monitor_items(src["monitor"], cfg, as_of)
                         + _catalyst_items(src["catalyst_log"], floor, as_of)
                         + _reaction_items(recent.get("earnings_reacted") or [], moves_by, cfg, session)),
        "ongoing": _order(market_ongoing + risk_ongoing + anchor_ongoing + ([blackout] if blackout else [])),
    }

    return {
        "as_of": as_of,
        "sessions": sessions,
        "just_out": {
            "session": session,
            "macro": _order([_just_out_macro(e) for e in recent.get("macro") or [] if e.get("date")]),
            "earnings": _just_out_earnings(recent.get("earnings_reacted") or [],
                                           recent.get("earnings_after_close") or [], moves_by),
        },
        "coming_up": _coming_up(catalysts, src["themes"], evidence, sessions, cfg, as_of, events_dir),
        "unusual": unusual,
        "live": _live(ctx.config),
        "history": _history(previous, as_of, unusual, cfg["history_days"]),
        "settings": cfg,
        "unavailable": unavailable,
        "notes": notes + [
            "Scheduled items carry new=false: they are on the calendar and have not happened yet.",
            "Later lists high-importance items from the fourth session to as_of plus later_days.",
        ],
    }
