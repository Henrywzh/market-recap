"""EVENTS: one card per earnings report, and one timeline per name.

Built from what this session already has -- CATALYSTS' report dates and
Nasdaq consensus, EVIDENCE's past reactions, ratings and Form 4s, the options
snapshot, the members' closes -- plus Yahoo's current-quarter revenue and EPS
range. Nothing is scored: the card lists what the report is priced for
(implied move against the name's own past moves), what it is worth to each
index, where the stock stands going in, and which names have moved with it
on its past reports (compute.events says how).

Two outputs:

- ``events.json``: the cards the CATALYSTS page leads with -- reports in the
  next few days from names heavy enough to move an index (or on the
  watchlist), and the reports the last session traded on, with the outcome;
  plus the high-importance macro dates every timeline shares.
- ``events/{ticker}.json``: per name, its card (when a report is on the
  calendar), its read-through in both directions, and its timeline events.
"""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import time

import numpy as np
import pandas as pd

from ..compute import events as E
from ..compute import evidence as V
from ..config import EVENTS_ARTIFACT_DIR
from .. import cache
from ..sources import estimates, finnhub, nasdaq, releases, sec, snapshot_store
from ..util import SourceRecord, clean_float, describe_error, prune_stale, write_json
from .catalysts import _universe
from .financials import cik_for

# Same-session artifacts this panel reads (build.optional_panel).
INPUTS = ("catalysts", "evidence", "themes")


def _issuers(symbols: list[str]) -> dict[str, set[str]]:
    """Other share classes of each symbol's issuer, by SEC CIK."""
    try:
        cik_map = sec.fetch_ticker_cik_map()
    except Exception:
        return {}
    by_cik: dict[int, set[str]] = {}
    for symbol in symbols:
        cik = cik_for(symbol, cik_map)
        if cik:
            by_cik.setdefault(cik, set()).add(symbol)
    return {s: group - {s} for group in by_cik.values() for s in group if len(group) > 1}


def _sessions_of(reactions: list[dict]) -> list[str]:
    return [r["session"] for r in reactions or [] if r.get("session")]


def _links(symbol: str, industry: dict[str, str], membership: dict[str, list[dict]]) -> dict[str, str]:
    """Peers with an economic tie to ``symbol``: its GICS industry, or a theme
    it belongs to; peer -> the reason, a theme first."""
    out: dict[str, str] = {}
    mine = industry.get(symbol)
    if mine and mine != "-":
        out.update({s: f"same industry ({mine})" for s, i in industry.items() if i == mine and s != symbol})
    themes = {m["key"]: m["label"] for m in membership.get(symbol) or []}
    for peer, rows in membership.items():
        shared = [themes[m["key"]] for m in rows if m["key"] in themes]
        if shared and peer != symbol:
            out[peer] = f"theme: {shared[0]}"
    return out


def _readthrough(symbol: str, excess: pd.DataFrame, corr: pd.DataFrame, reactions: dict[str, list[dict]],
                 next_report: dict[str, dict], meta: dict, sector_etf: str | None, issuers: dict[str, set[str]],
                 settings: dict, links: dict[str, str] | None = None) -> dict:
    """Who has moved on this name's reports, and whose reports have moved it:
    peers with a reason to (``links``, or a strong correlation), kept only
    where the report-day beta clears ``readthrough_min_t``."""
    min_reports = int(settings.get("readthrough_min_reports", 4))
    show = int(settings.get("readthrough_show", 5))
    min_t = float(settings.get("readthrough_min_t", 2.0))
    picks = E.candidates(corr, symbol, count=int(settings.get("readthrough_candidates", 12)),
                         same_issuer=issuers.get(symbol, set()), linked=links,
                         strong_corr=float(settings.get("readthrough_strong_corr", 0.45)))
    own_sessions = _sessions_of(reactions.get(symbol))
    own = E.moves_on(excess, symbol, own_sessions)
    moves_with, moves_it = [], []
    # Same direction only: a read-through is a peer moving with the report. A
    # negative beta among a dozen candidates on eight reports is chance far
    # more often than a share shift.
    reliable = lambda stats: stats and stats["t"] is not None and stats["t"] >= min_t  # noqa: E731
    for peer, correlation, reason in picks:
        base = {"symbol": peer, "name": meta.get(peer, {}).get("name"), "corr": round(correlation, 2), "link": reason}
        stats = E.co_move(own, E.moves_on(excess, peer, own_sessions), min_reports=min_reports)
        if reliable(stats):
            moves_with.append({**base, **stats})
        peer_sessions = _sessions_of(reactions.get(peer))
        stats = E.co_move(E.moves_on(excess, peer, peer_sessions), E.moves_on(excess, symbol, peer_sessions),
                          min_reports=min_reports)
        if reliable(stats):
            upcoming = next_report.get(peer)
            moves_it.append({**base, **stats, "next": upcoming["date"] if upcoming else None,
                             "timing": upcoming.get("timing") if upcoming else None})
    moves_with.sort(key=lambda r: -r["t"])
    moves_it.sort(key=lambda r: -r["t"])
    out = {"reports": len(own_sessions), "with": moves_with[:show], "into": moves_it[:show], "candidates": len(picks)}
    if sector_etf and sector_etf in excess.columns:
        stats = E.co_move(own, E.moves_on(excess, sector_etf, own_sessions), min_reports=min_reports)
        if stats:
            out["sector_etf"] = {"symbol": sector_etf, **stats}
    return out


# A straddle is a report's implied move only if it expires soon after the
# session that trades on it; one running weeks past (the snapshot's 30-day
# expiry, for a name reporting in nine sessions) prices a month, not a report.
EVENT_EXPIRY_DAYS = 7


def _event_implied(rows: pd.DataFrame, session: date) -> dict | None:
    implied = V.implied_move(rows, session)
    if implied and (date.fromisoformat(implied["expiry"]) - session).days > EVENT_EXPIRY_DAYS:
        return None
    return implied


def _implied_before(history: pd.DataFrame, symbol: str, report: date, timing: str | None, session: date) -> dict | None:
    """The implied move the options snapshot priced the afternoon before a report."""
    if history.empty:
        return None
    day = E.pre_event_day(report, timing).isoformat()
    rows = history[(history["underlying"] == symbol) & (history["day"] == day)]
    if rows.empty:
        return None
    implied = _event_implied(rows, session)
    return {**implied, "snapshot_day": day} if implied else None


def _card(symbol: str, event: dict, entry: dict, info: dict, trend: dict | None, snapshot: tuple | None,
          ctx, sector_etf: str | None) -> dict:
    """What one coming report is priced for, and what it would be worth."""
    next_info = entry.get("next") or {}
    session = next_info.get("reaction_session") if next_info.get("date") == event["date"] else None
    if session is None:
        # EVIDENCE only looks from tomorrow; a report after today's close
        # trades on the next weekday (a holiday is the one miss).
        day = date.fromisoformat(event["date"])
        if event.get("timing") == "amc":
            day += timedelta(days=1)
            while day.weekday() >= 5:
                day += timedelta(days=1)
        session = day.isoformat()
    implied = None
    if snapshot and session:
        rows = snapshot[1][snapshot[1]["underlying"] == symbol]
        if not rows.empty:
            implied = _event_implied(rows, date.fromisoformat(session))
            if implied:
                implied["snapshot_day"] = snapshot[0].isoformat()
    moves = [abs(r["move_pct"]) for r in entry.get("reactions") or []]
    mean_abs = entry.get("mean_abs_move")
    median_abs = round(sorted(moves)[len(moves) // 2], 2) if moves else None
    basis = implied["straddle_pct"] if implied else mean_abs
    close = ctx.closes[symbol] if symbol in ctx.closes.columns else pd.Series(dtype=float)
    sector_close = ctx.etf_closes[sector_etf] if sector_etf and sector_etf in ctx.etf_closes.columns else None
    return {
        "date": event["date"], "timing": event.get("timing"), "reaction_session": session,
        "consensus": E.consensus(trend, event),
        "priced": {
            "implied": implied,
            "mean_abs": mean_abs,
            "median_abs": median_abs,
            "reports": len(moves),
            "beat_implied": sum(m > implied["straddle_pct"] for m in moves) if implied else None,
            "up": sum(r["move_pct"] > 0 for r in entry.get("reactions") or []),
        },
        "impact": {"basis": "implied" if implied else ("average" if mean_abs else None), "move_pct": basis,
                   "indices": E.index_impact(info.get("weights") or {}, basis)},
        "setup": {**E.setup(close, sector_close), "sector_etf": sector_etf},
    }


def _outcome(symbol: str, event: dict, entry: dict, history: pd.DataFrame, excess: pd.DataFrame,
             readthrough: dict) -> dict | None:
    """How a report the last session traded on came out."""
    reaction = next((r for r in entry.get("reactions") or [] if r["date"] == event["date"]), None)
    if reaction is None:
        return None
    session = date.fromisoformat(reaction["session"])
    implied = _implied_before(history, symbol, date.fromisoformat(event["date"]), event.get("timing"), session)
    peers = []
    for peer in readthrough.get("with") or []:
        move = E.moves_on(excess, peer["symbol"], [reaction["session"]])[0]
        expected = None if reaction.get("excess_pct") is None else round(peer["beta"] * reaction["excess_pct"], 2)
        peers.append({"symbol": peer["symbol"], "beta": peer["beta"], "expected_pct": expected,
                      "excess_pct": None if move is None else round(move, 2)})
    return {
        "date": event["date"], "timing": event.get("timing"), "session": reaction["session"],
        "eps": event.get("eps"), "eps_forecast": event.get("eps_forecast"), "surprise_pct": event.get("surprise_pct"),
        "move_pct": reaction["move_pct"], "excess_pct": reaction.get("excess_pct"), "index_pct": reaction.get("index_pct"),
        "implied": implied,
        "vs_implied": round(abs(reaction["move_pct"]) / implied["straddle_pct"], 2) if implied and implied["straddle_pct"] else None,
        "peers": peers,
    }


def _timeline(entry: dict, history: pd.DataFrame, symbol: str) -> list[dict]:
    """Dated events on the name's own history: reports, ratings, insider buys."""
    items = []
    for r in entry.get("reactions") or []:
        implied = _implied_before(history, symbol, date.fromisoformat(r["date"]), r.get("timing"),
                                  date.fromisoformat(r["session"])) if r.get("session") else None
        items.append({"kind": "earnings", "date": r["session"], "report": r["date"], "timing": r.get("timing"),
                      "move_pct": r["move_pct"], "excess_pct": r.get("excess_pct"),
                      "implied_pct": implied["straddle_pct"] if implied else None})
    for r in (entry.get("ratings") or {}).get("recent") or []:
        action = r.get("action")
        target, prior = r.get("target"), r.get("prior_target")
        tone = ("up" if action == "up" else "down" if action == "down" else
                "up" if target and prior and target > prior else "down" if target and prior and target < prior else "dim")
        if tone == "dim" and action not in ("init",):
            continue  # a reiteration at the same target is not an event
        items.append({"kind": "rating", "date": r["date"], "firm": r.get("firm"), "action": action,
                      "from": r.get("from"), "to": r.get("to"), "target": target, "prior_target": prior, "tone": tone})
    for r in (entry.get("insiders") or {}).get("strict_purchases") or []:
        items.append({"kind": "insider_buy", "date": r["date"], "owner": r.get("owner"), "value": r.get("value"),
                      "url": r.get("filing_url")})
    return sorted(items, key=lambda i: i["date"])


# --- Deeper card: history, guidance, filings, the industry since the last report ---

def _calendars(dates: set[str], as_of: date, budget: int) -> tuple[dict[str, dict[str, dict]], int]:
    """{report date: {symbol: Nasdaq row}} for past report dates, and how many
    dates were left for a later build. A past day's calendar never changes and
    is kept for good; one saved before the results were in (no EPS on any row)
    is read again. At most ``budget`` days are fetched per build, so a cold
    cache fills over a few nights instead of in one burst."""
    out, fetched, left = {}, 0, 0
    for day in sorted(dates, reverse=True):
        if day >= as_of.isoformat():
            continue
        cached = cache.path_for(nasdaq.NAMESPACE, f"earnings-{day}", ".json").exists()
        rows = None
        if cached:
            try:
                rows = nasdaq.fetch_earnings(day, kind="archive")
            except Exception:
                rows = None
            if rows is not None and not any(r.get("eps") is not None for r in rows):
                rows = None
        if rows is None:
            if fetched >= budget:
                left += 1
                continue
            fetched += 1
            try:
                rows = nasdaq.fetch_earnings(day, kind="archive", use_cache=False)
            except Exception:
                continue
        out[day] = {r["symbol"]: r for r in rows}
    return out, left


# A release names its business items; these are the ones a card lists.
FILING_ITEMS = {
    "1.01": "material agreement", "1.02": "agreement ended", "2.01": "acquisition or disposal",
    "2.03": "new debt", "2.05": "restructuring costs", "2.06": "impairment", "3.02": "equity sale",
    "4.02": "restatement", "5.02": "officer or director change", "5.03": "bylaws change", "5.07": "shareholder vote",
    "7.01": "Reg FD disclosure", "8.01": "other event",
}


def _filings(block: dict | None, since: str, cik: int | None, limit: int = 12) -> list[dict]:
    """8-Ks other than earnings releases filed since ``since``, newest first."""
    if not block or not cik:
        return []
    out = []
    forms, items = block.get("form") or [], block.get("items") or []
    for i, form in enumerate(forms):
        filed = block["filingDate"][i]
        if filed < since:
            break
        if form not in ("8-K", "8-K/A"):
            continue
        codes = [c.strip() for c in str(items[i] if i < len(items) else "").split(",") if c.strip()]
        if "2.02" in codes:
            continue
        labels = [FILING_ITEMS[c] for c in codes if c in FILING_ITEMS]
        if not labels:
            continue
        acc = block["accessionNumber"][i]
        out.append({"date": filed, "form": form, "items": codes, "labels": labels,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.html"})
        if len(out) >= limit:
            break
    return out


# The 8-K items worth a marker on the price: what changes the company, not the
# routine (Reg FD slides, bylaws, the annual vote, a new note).
MARKER_ITEMS = ("1.01", "1.02", "1.05", "2.01", "2.05", "2.06", "3.02", "4.02", "5.02")
FILING_ITEMS["1.05"] = "cybersecurity incident"


def _filing_markers(block: dict | None, cik: int | None, since: str) -> list[dict]:
    """Material 8-Ks since ``since`` (as far back as the filer's recent block
    reaches), for the timeline: one marker per filing."""
    if not block or not cik:
        return []
    out = []
    forms, items = block.get("form") or [], block.get("items") or []
    for i, form in enumerate(forms):
        filed = block["filingDate"][i]
        if filed < since:
            break
        if form not in ("8-K", "8-K/A"):
            continue
        codes = [c.strip() for c in str(items[i] if i < len(items) else "").split(",") if c.strip()]
        material = [c for c in codes if c in MARKER_ITEMS]
        if not material:
            continue
        acc = block["accessionNumber"][i]
        out.append({"kind": "filing", "date": filed, "items": material, "labels": [FILING_ITEMS[c] for c in material],
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.html"})
    return out


def _theme_dates(groups: list[dict], keys: list[str], as_of: str, days: int) -> list[dict]:
    """The coming data releases and macro dates of the name's themes -- what
    moves the industry it trades with -- one row per date and title."""
    end = (date.fromisoformat(as_of) + timedelta(days=days)).isoformat()
    seen, out = set(), []
    for g in groups:
        if g.get("key") not in keys:
            continue
        for e in g.get("calendar") or []:
            if e.get("kind") not in ("data", "macro") or not as_of < e["date"] <= end:
                continue
            key = (e["date"], e.get("title"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"date": e["date"], "kind": e["kind"], "title": e.get("title"), "time": e.get("time"),
                        "theme": g.get("label"), "late": bool(e.get("late"))})
    return sorted(out, key=lambda e: e["date"])


# Industry series whose points are market prints, not releases: a point every
# session (or every fifth) would "explain" every move.
NOT_RELEASES = ("px_", "fred_t10y", "fred_bamlh", "openrouter", "pcpp_")


# One publication carries several series: EIA's weekly report, the Fed's H.8.
PUBLICATIONS = (("eia_gas_storage", "EIA natural gas storage report"), ("eia_", "EIA weekly petroleum status report"),
                ("fred_totll", "Fed H.8 (bank loans and deposits)"), ("fred_dpsacbw027sbog", "Fed H.8 (bank loans and deposits)"),
                ("fred_houst", "Census housing starts and permits"), ("fred_permit", "Census housing starts and permits"))


def _releases_by_day(drivers: list[dict], keys: list[str]) -> dict[str, list[str]]:
    """{day: [publications released that day]} for the name's themes."""
    out: dict[str, list[str]] = {}
    for d in drivers:
        if d["key"].startswith(NOT_RELEASES) or not set(d["themes"]) & set(keys):
            continue
        name = next((label for prefix, label in PUBLICATIONS if d["key"].startswith(prefix)), d["label"])
        for p in d["points"]:
            day = out.setdefault(p["available"], [])
            if name not in day:
                day.append(name)
    return out


def _news_window(excess_index: pd.DatetimeIndex, day: str) -> tuple[date, date, float, float]:
    """The request dates and the timestamps between the previous session's
    close and this one's (16:00 New York): the news a close-to-close move saw."""
    at = excess_index.searchsorted(pd.Timestamp(day))
    prev = excess_index[at - 1] if at > 0 else pd.Timestamp(day) - pd.Timedelta(days=1)
    close = lambda d: pd.Timestamp(d.strftime("%Y-%m-%d") + " 16:00", tz="America/New_York").timestamp()  # noqa: E731
    return prev.date(), date.fromisoformat(day), close(prev), close(pd.Timestamp(day))


def rotation_due(symbol: str, day: date, every: int) -> bool:
    """Whether ``symbol`` is asked on session ``day`` when each name is asked
    once every ``every`` weekdays: a stable hash of the name picks its slot,
    and weekdays are counted so a weekend does not skip a slot."""
    if every <= 1:
        return True
    weekdays = int(np.busday_count(date(2000, 1, 3), day))
    slot = int(hashlib.md5(symbol.encode("utf-8")).hexdigest(), 16) % every   # md5 spreads short names evenly; crc32 did not
    return slot == weekdays % every


def _kept_events(entries: list[dict], as_of: str) -> list[dict]:
    """The config's hand-kept company and industry events still ahead, each
    with its source: {date, kind, text, url, symbols, themes, origin}."""
    out = []
    for e in entries:
        day = str(e.get("date") or "")
        if day <= as_of or not e.get("title"):
            continue
        out.append({"date": day, "kind": e.get("kind", "event"), "text": e["title"], "url": e.get("url"),
                    "source": e.get("source"), "symbols": list(e.get("symbols") or []), "themes": list(e.get("themes") or []),
                    "origin": "kept"})
    return out


def _revenue_before(quarters: tuple, day: str) -> float | None:
    """The last quarterly revenue filed by ``day``: the scale a guide is checked against."""
    known = [q for q in quarters if q["filed"] <= day and q.get("value")]
    return known[-1]["value"] if known else None


def _guides(symbol: str, cik: int | None, reactions: list[dict], calendar: dict[str, dict[str, dict]],
            count: int, budget: dict) -> dict[str, dict]:
    """{report date: checked guide} from the releases of the last ``count``
    reports. ``budget["left"]`` caps releases read for the first time."""
    if not cik or not reactions:
        return {}
    try:
        data = sec.filer(cik)
        # The current registrant first, then any predecessor (Exxon, 2026).
        blocks = [(c, sec.submissions_recent(c)) for c in data.ciks]
    except Exception:
        return {}
    out = {}
    for r in reactions[:count]:
        day = r["date"]
        found = None
        for filer_cik, block in blocks:
            try:
                found = releases.release_on(filer_cik, day, block, fetch=budget["left"] > 0)
            except Exception:
                found = None
            if found:
                break
        if found is None:
            continue
        url, text, fresh = found
        if fresh:
            budget["left"] -= 1
        eps_ref = ((calendar.get(day) or {}).get(symbol) or {}).get("eps")
        guide = E.checked_guide(releases.outlook(text), _revenue_before(data.quarterly_revenue, day), eps_ref)
        if guide:
            out[day] = guide | {"url": url}
    return out


def _since(drivers: list[dict], themes: list[str], day: str | None) -> list[dict]:
    """Each industry series of the name's themes: where it stood when the
    company last reported, where it is now, and how many releases since."""
    if not day:
        return []
    out = []
    for d in drivers:
        if not set(d["themes"]) & set(themes):
            continue
        points = d["points"]
        before = [p for p in points if p["available"] <= day]
        after = [p for p in points if p["available"] > day]
        if not after or not before:
            continue
        then, now = before[-1], points[-1]
        row = {"key": d["key"], "label": d["label"], "kind": d["kind"], "unit": d["unit"],
               "then": then, "now": now, "releases": len(after)}
        if d["kind"] == "level" and then["value"]:
            row["change_pct"] = round((now["value"] / then["value"] - 1) * 100, 1)
        else:
            # A rate moves in hundredths: the card shows it in basis points.
            row["change_pp"] = round(now["value"] - then["value"], 2 if d["unit"] == "rate" else 1)
        out.append(row)
    return out


def _macro(catalysts: dict, as_of: str, days: int) -> list[dict]:
    end = (date.fromisoformat(as_of) + timedelta(days=days)).isoformat()
    keep = []
    for e in catalysts.get("events") or []:
        if e.get("lane") != "macro" or not as_of < e["date"] <= end:
            continue
        if e.get("importance") == "high" or (e.get("event_type") == "market_structure" and e["title"].lower().startswith("monthly options expir")):
            keep.append({"date": e["date"], "time": e.get("time"), "title": e["title"], "type": e.get("event_type"),
                         "importance": e.get("importance")})
    return keep


def build(ctx, *, inputs: dict | None = None) -> dict:
    inputs = inputs or {}
    catalysts, evidence = inputs.get("catalysts"), inputs.get("evidence")
    if not catalysts or not evidence:
        raise RuntimeError("EVENTS needs this session's CATALYSTS and EVIDENCE")
    settings = dict(ctx.config.get("events", {}))
    as_of = date.fromisoformat(ctx.as_of)
    # Seconds by step, for the manifest: EVENTS is most of a build's time.
    steps: dict[str, float] = {}
    clock = {"t": time.monotonic()}

    def lap(step: str) -> None:
        now = time.monotonic()
        steps[step] = round(steps.get(step, 0.0) + now - clock["t"], 1)
        clock["t"] = now
    names = evidence.get("names") or {}
    meta = _universe(ctx)
    meta = {info["symbol"]: info for info in meta.values()}
    sector_etfs = ctx.sector_etfs

    index_close = ctx.index_closes[ctx.primary.symbol]
    frames = [ctx.closes] + ([ctx.etf_closes[[s for s in set(sector_etfs.values()) if s in ctx.etf_closes.columns]]]
                             if not ctx.etf_closes.empty else [])
    excess = E.daily_excess(pd.concat(frames, axis=1), index_close)
    lookback = int(settings.get("readthrough_lookback_sessions", 252))
    member_excess = excess[[s for s in ctx.closes.columns]].iloc[-lookback:]
    corr = member_excess.corr(min_periods=int(0.6 * lookback))
    issuers = _issuers(list(ctx.closes.columns))
    reactions = {s: n.get("reactions") or [] for s, n in names.items()}

    # CATALYSTS lists tomorrow onward; today's after-close reports are kept
    # apart (they have not traded yet) and are still ahead of the card.
    after_close = (catalysts.get("recent") or {}).get("earnings_after_close") or []
    earnings = [e for e in [*(catalysts.get("events") or []), *after_close]
                if e.get("event_type") == "earnings" and e.get("symbol")]
    next_report: dict[str, dict] = {}
    for e in sorted(earnings, key=lambda e: e["date"]):
        # A report after today's close is still ahead: the session it trades
        # on is tomorrow's, and today's closing straddle is its implied move.
        if e["date"] > ctx.as_of or (e["date"] == ctx.as_of and e.get("timing") == "amc"):
            next_report.setdefault(e["symbol"], e)

    card_days = int(settings.get("card_horizon_days", 30))
    card_end = (as_of + timedelta(days=card_days)).isoformat()
    carded = sorted(s for s, e in next_report.items() if e["date"] <= card_end)
    # Every name's trend: the revisions table is on every ticker page, and
    # EARNINGS has already read the whole universe's this session (cached).
    everyone = sorted(set(ctx.closes.columns) & set(meta))
    lap("setup")
    trends, missing = estimates.fetch_trends(everyone) if everyone else ({}, {})
    lap("yahoo_estimates")
    ctx.log.add(SourceRecord("yahoo_estimates_quarter", "EPS and revenue estimates and revisions (Yahoo earningsTrend)",
                             estimates.URL.format(symbol="{symbol}"), ctx.as_of, rows=len(trends),
                             status="ok" if len(missing) <= 0.2 * max(len(everyone), 1) else "partial",
                             error=f"{len(missing)} of {len(everyone)} without estimates" if missing else None))

    # Past reports: each date's Nasdaq calendar (consensus, actual, surprise).
    report_dates = {r["date"] for rs in reactions.values() for r in rs if r.get("date")}
    calendars, dates_left = _calendars(report_dates, as_of, int(settings.get("history_new_dates", 120)))
    lap("nasdaq_history")
    ctx.log.add(SourceRecord("nasdaq_earnings_history", "Nasdaq earnings calendar on past report dates (EPS vs consensus)",
                             nasdaq.EARNINGS_URL.format(date="{date}"), ctx.as_of, rows=len(calendars),
                             status="ok" if not dates_left else "partial",
                             error=f"{dates_left} report dates left for later builds" if dates_left else None))
    try:
        cik_map = sec.fetch_ticker_cik_map()
    except Exception:
        cik_map = {}
    focus = set(evidence.get("focus") or [])
    guide_budget = {"left": int(settings.get("guide_new_releases", 200))}
    themes = inputs.get("themes") or {}
    drivers = themes.get("drivers") if isinstance(themes.get("drivers"), list) else []
    membership = themes.get("membership") or {}
    industry = {row.yahoo_symbol: str(row.sub_sector) for frame in ctx.members.values()
                for row in frame.itertuples() if hasattr(row, "sub_sector")}
    since_day = (as_of - timedelta(days=int(settings.get("filings_days", 120)))).isoformat()
    marker_since = (as_of - timedelta(days=int(settings.get("timeline_filings_days", 730)))).isoformat()
    theme_groups = themes.get("groups") if isinstance(themes.get("groups"), list) else []
    bellwethers = {g["key"]: list(g.get("bellwethers") or []) for g in ctx.config.get("themes", {}).get("groups", [])}
    recent_events = (catalysts.get("recent") or {}).get("earnings_reacted") or []
    recent_symbols = {e["symbol"] for e in recent_events}

    # Guidance is read from each release once and kept; a build reads at most
    # ``guide_new_releases`` new ones, soonest reporters first, then the focus
    # names, then the heaviest -- so the cards that matter fill first.
    def priority(symbol: str) -> tuple:
        event = next_report.get(symbol)
        soon = event["date"] if event and symbol in carded else "9999"
        weight = max((meta[symbol].get("weights") or {}).values(), default=0) or 0
        return (soon, symbol not in focus, -weight, symbol)

    deep = [s for s in everyone if s in carded or s in focus or s in recent_symbols
            or _heavy({"weights": meta[s].get("weights") or {}}, settings) or meta[s].get("watchlist")]
    guides_by_symbol = {}
    for symbol in sorted(deep, key=priority):
        rows = {d: {symbol: r} for d, rs in calendars.items() if (r := rs.get(symbol) or rs.get(symbol.replace("-", ".")))}
        guides_by_symbol[symbol] = _guides(symbol, cik_for(symbol, cik_map) if cik_map else None, reactions.get(symbol) or [],
                                           rows, int(settings.get("guide_reports", 4)), guide_budget)

    lap("sec_guidance")
    # Large moves: found for every name; headlines asked for within a budget,
    # the names whose cards matter first and the newest moves first. A day's
    # news is kept a year once settled, so the backlog clears over a few builds.
    move_since = (as_of - timedelta(days=int(settings.get("moves_days", 730)))).isoformat()
    news_since = (as_of - timedelta(days=int(settings.get("news_days", 365)))).isoformat()
    moves_by_symbol = {s: E.big_moves(excess[s], since=move_since, skip=set(_sessions_of(reactions.get(s))))
                       for s in everyone if s in excess.columns}
    news: dict[tuple[str, str], list[dict]] = {}
    news_state = {"asked": 0, "failed": 0, "budget": int(settings.get("news_budget", 250)), "keyed": finnhub.available()}
    if news_state["keyed"]:
        wanted = sorted(((priority(s), m["date"], s) for s, ms in moves_by_symbol.items() for m in ms if m["date"] >= news_since),
                        key=lambda x: (x[0][1], x[0][2], -int(x[1].replace("-", "")), x[0][3]))
        for _, day, symbol in wanted:
            start, end, start_ts, end_ts = _news_window(excess.index, day)
            asked = symbol.replace("-", ".")
            if not finnhub.is_cached(asked, start, end, as_of):
                if news_state["asked"] >= news_state["budget"]:
                    continue
                news_state["asked"] += 1
            try:
                rows = finnhub.company_news(asked, start, end, as_of)
            except Exception:
                news_state["failed"] += 1
                continue
            news[(symbol, day)] = E.rank_headlines(rows, symbol, meta.get(symbol, {}).get("name"), start_ts, end_ts)

    lap("finnhub_moves")
    # Company events announced ahead: the deep names' last weeks of headlines,
    # read for a dated investor day, product event, FDA date, meeting or
    # ruling; plus the hand-kept list in the config.
    announced: dict[str, list[dict]] = {}
    event_state = {"asked": 0, "failed": 0, "reused": 0, "budget": int(settings.get("event_news_budget", 150))}
    if news_state["keyed"]:
        event_days = int(settings.get("event_news_days", 45))
        lookback = as_of - timedelta(days=event_days)
        rotation = max(1, int(settings.get("event_news_rotation_days", 3)))
        for symbol in sorted(deep, key=priority):
            asked = symbol.replace("-", ".")
            # Each name is asked every `rotation` sessions; between, its last
            # window is read again (an announcement is weeks ahead of its date).
            if not rotation_due(symbol, as_of, rotation):
                rows = finnhub.recent_window(asked, as_of, event_days, max_age=2 * rotation + 4)
                if rows is not None:
                    event_state["reused"] += 1
                    announced[symbol] = E.announced_events(rows, symbol, meta.get(symbol, {}).get("name"), as_of)
                    continue
            if not finnhub.is_cached(asked, lookback, as_of, as_of):
                if event_state["asked"] >= event_state["budget"]:
                    continue
                event_state["asked"] += 1
            try:
                rows = finnhub.company_news(asked, lookback, as_of, as_of)
            except Exception:
                event_state["failed"] += 1
                continue
            announced[symbol] = E.announced_events(rows, symbol, meta.get(symbol, {}).get("name"), as_of)
    kept_events = _kept_events(settings.get("company_events") or [], ctx.as_of)

    lap("finnhub_events")
    snapshot = snapshot_store.latest_options_summary(as_of)
    history = snapshot_store.options_summaries(as_of - timedelta(days=400), as_of) if snapshot else pd.DataFrame()

    written, cards, outcomes = [], [], []
    for symbol in sorted(set(ctx.closes.columns) & set(meta)):
        info = meta[symbol]
        entry = names.get(symbol) or {}
        sector_etf = sector_etfs.get(info.get("sector") or "")
        try:
            readthrough = _readthrough(symbol, excess, corr, reactions, next_report, meta, sector_etf, issuers, settings,
                                       _links(symbol, industry, membership))
        except Exception as exc:  # one name must not fail the rest
            readthrough = {"unavailable": describe_error(exc)}
        payload = {
            "symbol": symbol, "as_of": ctx.as_of, "name": info.get("name"), "sector": info.get("sector"),
            "weights": {k: clean_float(v, 3) for k, v in (info.get("weights") or {}).items()},
            "watchlist": bool(info.get("watchlist")),
            "readthrough": readthrough,
            "timeline": _timeline(entry, history, symbol),
        }
        cik = cik_for(symbol, cik_map) if cik_map else None
        own = entry.get("reactions") or []
        nasdaq_symbol = symbol.replace("-", ".")
        calendar = {d: rows.get(symbol) or rows.get(nasdaq_symbol) for d, rows in calendars.items()}
        guides = guides_by_symbol.get(symbol) or {}
        close = ctx.closes[symbol] if symbol in ctx.closes.columns else pd.Series(dtype=float)
        payload["history"] = E.report_history(own, {d: r for d, r in calendar.items() if r}, guides, close, index_close)
        payload["history_summary"] = E.history_summary(payload["history"])
        payload["revisions"] = E.revision_table(trends.get(symbol))
        try:
            block = sec.submissions_recent(cik) if cik else None
        except Exception:
            block = None
        payload["filings"] = _filings(block, since_day, cik)
        payload["timeline"] = sorted(payload["timeline"] + _filing_markers(block, cik, marker_since), key=lambda i: i["date"])
        theme_keys = [m["key"] for m in membership.get(symbol) or []]
        payload["theme_dates"] = _theme_dates(theme_groups, theme_keys, ctx.as_of, int(settings.get("timeline_days_ahead", 45)))
        payload["company_events"] = sorted(
            [{**e, "origin": "announced"} for e in announced.get(symbol, [])]
            + [e for e in kept_events if symbol in e["symbols"] or set(e["themes"]) & set(theme_keys)],
            key=lambda e: e["date"])
        # Peers whose reports have moved it (REPORTS THAT MOVE IT), and the
        # bellwethers of its themes -- not every name in its industry.
        movers = {r["symbol"] for r in readthrough.get("into") or []} | {
            b for g in theme_groups if g.get("key") in theme_keys for b in bellwethers.get(g["key"], [])}
        peer_reports = {p: _sessions_of(reactions.get(p)) for p in movers - {symbol} if reactions.get(p)}
        releases_on = _releases_by_day(drivers, theme_keys)
        payload["moves"] = [{**m, "reasons": E.move_reasons(m["date"], payload["timeline"], peer_reports, releases_on),
                             "news": news.get((symbol, m["date"]), []), "news_checked": (symbol, m["date"]) in news}
                            for m in moves_by_symbol.get(symbol, [])]
        payload["since"] = _since(drivers, [m["key"] for m in membership.get(symbol) or []], own[0]["date"] if own else None)
        event = next_report.get(symbol)
        if event and symbol in carded:
            payload["card"] = _card(symbol, event, entry, info, trends.get(symbol), snapshot, ctx, sector_etf)
            # Only the guide the last report before this one gave is about
            # the quarter now due (a release filed today guides the next).
            before = [r for r in payload["history"] if r["date"] < payload["card"]["date"]]
            last_guide = before[0].get("guide") if before else None
            payload["card"]["vs_guide"] = E.against_guide(last_guide, payload["card"]["consensus"])
        if symbol in recent_symbols:
            event = next(e for e in recent_events if e["symbol"] == symbol)
            outcome = _outcome(symbol, event, entry, history, excess, readthrough)
            if outcome:
                payload["outcome"] = outcome
        write_json(EVENTS_ARTIFACT_DIR / f"{symbol}.json", payload)
        written.append(symbol)
        if "card" in payload and _leads(payload, settings, as_of):
            cards.append(_summary(payload))
        if "outcome" in payload and (_heavy(payload, settings) or payload["watchlist"]):
            outcomes.append(_summary(payload))
    lap("per_name")
    prune_stale(EVENTS_ARTIFACT_DIR, written)

    cards.sort(key=lambda c: (c["card"]["date"], {"bmo": 0, "intraday": 1, "amc": 2}.get(c["card"]["timing"], 3),
                              -max(c["weights"].values(), default=0)))
    outcomes.sort(key=lambda c: -max(c["weights"].values(), default=0))
    ctx.log.add(SourceRecord(
        "finnhub_news", "Company news headlines on large-move days (Finnhub)", finnhub.PAGE_URL,
        ctx.as_of if news else None, rows=len(news),
        status="skipped" if not news_state["keyed"] else ("partial" if news_state["failed"] or news_state["asked"] >= news_state["budget"] else "ok"),
        error=("no FINNHUB_API_KEY: moves explained without headlines" if not news_state["keyed"]
               else f"{news_state['failed']} failed; budget {news_state['asked']}/{news_state['budget']} new requests" if news_state["failed"] or news_state["asked"] >= news_state["budget"] else None),
        policy="daily_close"))
    ctx.log.add(SourceRecord("sec_releases_guidance", "Guidance stated in earnings releases (8-K Item 2.02, EX-99)",
                             "https://www.sec.gov/cgi-bin/browse-edgar", ctx.as_of,
                             rows=sum(1 for s in written if (s in carded or s in focus)),
                             status="ok" if guide_budget["left"] > 0 else "partial",
                             error=None if guide_budget["left"] > 0 else "release budget spent; the rest are read next build"))
    lap("tail")
    if hasattr(ctx, "diagnostics"):
        # How the Finnhub budget went: asked tonight, read from the cache (a
        # settled day, or a name off its turn in the rotation), and failed.
        ctx.diagnostics["events"] = {
            "seconds": steps,
            "finnhub_moves": {"asked": news_state["asked"], "budget": news_state["budget"], "failed": news_state["failed"],
                              "from_cache": max(0, len(news) - news_state["asked"])},
            "finnhub_events": {"names": len(deep), "asked": event_state["asked"], "budget": event_state["budget"],
                               "reused_off_turn": event_state["reused"], "failed": event_state["failed"],
                               "from_cache": max(0, len(announced) - event_state["asked"] - event_state["reused"])},
        }
    return {
        "as_of": ctx.as_of,
        "options_snapshot": snapshot[0].isoformat() if snapshot else None,
        "lead_days": int(settings.get("lead_days", 7)),
        "thresholds": {"SPX": settings.get("lead_min_spx_weight"), "NDX": settings.get("lead_min_ndx_weight")},
        "upcoming": cards,
        "reported": outcomes,
        "macro": _macro(catalysts, ctx.as_of, int(settings.get("timeline_days_ahead", 45))),
        "covered": len(written),
        "carded": len(carded),
    }


def _heavy(payload: dict, settings: dict) -> bool:
    w = payload["weights"]
    return ((w.get("SPX") or 0) >= float(settings.get("lead_min_spx_weight", 0.25))
            or (w.get("NDX") or 0) >= float(settings.get("lead_min_ndx_weight", 0.5)))


def _leads(payload: dict, settings: dict, as_of: date) -> bool:
    """A card the CATALYSTS page leads with: soon, and heavy or watched."""
    end = (as_of + timedelta(days=int(settings.get("lead_days", 7)))).isoformat()
    return payload["card"]["date"] <= end and (_heavy(payload, settings) or payload["watchlist"])


def _summary(payload: dict) -> dict:
    """The per-name file without its timeline, for the lead strip."""
    return {k: v for k, v in payload.items() if k != "timeline"}
