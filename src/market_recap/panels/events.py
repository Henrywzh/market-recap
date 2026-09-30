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

import pandas as pd

from ..compute import events as E
from ..compute import evidence as V
from ..config import EVENTS_ARTIFACT_DIR
from ..sources import estimates, sec, snapshot_store
from ..util import SourceRecord, clean_float, describe_error, prune_stale, write_json
from .catalysts import _universe
from .financials import cik_for

# Same-session artifacts this panel reads (build.optional_panel).
INPUTS = ("catalysts", "evidence")


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


def _readthrough(symbol: str, excess: pd.DataFrame, corr: pd.DataFrame, reactions: dict[str, list[dict]],
                 next_report: dict[str, dict], meta: dict, sector_etf: str | None, issuers: dict[str, set[str]],
                 settings: dict) -> dict:
    """Who has moved on this name's reports, and whose reports have moved it."""
    min_reports = int(settings.get("readthrough_min_reports", 4))
    show = int(settings.get("readthrough_show", 5))
    picks = E.candidates(corr, symbol, count=int(settings.get("readthrough_candidates", 12)),
                         same_issuer=issuers.get(symbol, set()))
    own_sessions = _sessions_of(reactions.get(symbol))
    own = E.moves_on(excess, symbol, own_sessions)
    moves_with, moves_it = [], []
    for peer, correlation in picks:
        base = {"symbol": peer, "name": meta.get(peer, {}).get("name"), "corr": round(correlation, 2)}
        stats = E.co_move(own, E.moves_on(excess, peer, own_sessions), min_reports=min_reports)
        if stats:
            moves_with.append({**base, **stats})
        peer_sessions = _sessions_of(reactions.get(peer))
        stats = E.co_move(E.moves_on(excess, peer, peer_sessions), E.moves_on(excess, symbol, peer_sessions),
                          min_reports=min_reports)
        if stats:
            upcoming = next_report.get(peer)
            moves_it.append({**base, **stats, "next": upcoming["date"] if upcoming else None,
                             "timing": upcoming.get("timing") if upcoming else None})
    moves_with.sort(key=lambda r: -r["beta"])
    moves_it.sort(key=lambda r: -r["beta"])
    out = {"reports": len(own_sessions), "with": moves_with[:show], "into": moves_it[:show]}
    if sector_etf and sector_etf in excess.columns:
        stats = E.co_move(own, E.moves_on(excess, sector_etf, own_sessions), min_reports=min_reports)
        if stats:
            out["sector_etf"] = {"symbol": sector_etf, **stats}
    return out


def _implied_before(history: pd.DataFrame, symbol: str, report: date, timing: str | None, session: date) -> dict | None:
    """The implied move the options snapshot priced the afternoon before a report."""
    if history.empty:
        return None
    day = E.pre_event_day(report, timing).isoformat()
    rows = history[(history["underlying"] == symbol) & (history["day"] == day)]
    if rows.empty:
        return None
    implied = V.implied_move(rows, session)
    return {**implied, "snapshot_day": day} if implied else None


def _card(symbol: str, event: dict, entry: dict, info: dict, trend: dict | None, snapshot: tuple | None,
          ctx, sector_etf: str | None) -> dict:
    """What one coming report is priced for, and what it would be worth."""
    next_info = entry.get("next") or {}
    session = next_info.get("reaction_session")
    implied = None
    if snapshot and session:
        rows = snapshot[1][snapshot[1]["underlying"] == symbol]
        if not rows.empty:
            implied = V.implied_move(rows, date.fromisoformat(session))
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

    earnings = [e for e in catalysts.get("events") or [] if e.get("event_type") == "earnings" and e.get("symbol")]
    next_report: dict[str, dict] = {}
    for e in sorted(earnings, key=lambda e: e["date"]):
        if e["date"] > ctx.as_of:
            next_report.setdefault(e["symbol"], e)

    card_days = int(settings.get("card_horizon_days", 30))
    card_end = (as_of + timedelta(days=card_days)).isoformat()
    carded = sorted(s for s, e in next_report.items() if e["date"] <= card_end)
    trends, missing = estimates.fetch_trends(carded) if carded else ({}, {})
    ctx.log.add(SourceRecord("yahoo_estimates_quarter", "Current-quarter EPS and revenue estimates (Yahoo earningsTrend)",
                             estimates.URL.format(symbol="{symbol}"), ctx.as_of, rows=len(trends),
                             status="ok" if len(missing) <= 0.2 * max(len(carded), 1) else "partial",
                             error=f"{len(missing)} of {len(carded)} without estimates" if missing else None))

    snapshot = snapshot_store.latest_options_summary(as_of)
    history = snapshot_store.options_summaries(as_of - timedelta(days=400), as_of) if snapshot else pd.DataFrame()

    recent_events = (catalysts.get("recent") or {}).get("earnings_reacted") or []
    recent_symbols = {e["symbol"] for e in recent_events}
    written, cards, outcomes = [], [], []
    for symbol in sorted(set(ctx.closes.columns) & set(meta)):
        info = meta[symbol]
        entry = names.get(symbol) or {}
        sector_etf = sector_etfs.get(info.get("sector") or "")
        try:
            readthrough = _readthrough(symbol, excess, corr, reactions, next_report, meta, sector_etf, issuers, settings)
        except Exception as exc:  # one name must not fail the rest
            readthrough = {"unavailable": describe_error(exc)}
        payload = {
            "symbol": symbol, "as_of": ctx.as_of, "name": info.get("name"), "sector": info.get("sector"),
            "weights": {k: clean_float(v, 3) for k, v in (info.get("weights") or {}).items()},
            "watchlist": bool(info.get("watchlist")),
            "readthrough": readthrough,
            "timeline": _timeline(entry, history, symbol),
        }
        event = next_report.get(symbol)
        if event and symbol in carded:
            payload["card"] = _card(symbol, event, entry, info, trends.get(symbol), snapshot, ctx, sector_etf)
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
    prune_stale(EVENTS_ARTIFACT_DIR, written)

    cards.sort(key=lambda c: (c["card"]["date"], {"bmo": 0, "intraday": 1, "amc": 2}.get(c["card"]["timing"], 3),
                              -max(c["weights"].values(), default=0)))
    outcomes.sort(key=lambda c: -max(c["weights"].values(), default=0))
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
