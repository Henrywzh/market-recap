"""The agent feed: two small files an outside research agent reads first.

``agent-index.json`` (at most ``INDEX_MAX_BYTES``) is the daily entry point:
the market's state in a few numbers, what changed, the research candidates in
a fixed order, the next week's catalysts and every data-quality alert.
``agent-brief.json`` (at most ``BRIEF_MAX_BYTES``) is the detail behind it,
section by section along the page's own chain -- risk budget, market,
sectors, names, timing, review -- and every candidate in full.

Both are condensed from the artifacts this build already wrote and validated,
so nothing becomes public that the site does not already publish, and nothing
is recomputed: each number is copied from an artifact, and each section and
candidate names the artifact it came from.

A candidate is raised by a fixed rule and carries a neutral research
question, never a verdict. Whether it matters is the reader's call. Three
kinds:

* ``condition`` -- true or not on any day (a risk tile past its threshold).
  Tracked against the previous published feed: ``new``, ``continuing``,
  ``resolved`` (a valid new reading shows it ended) or ``unknown`` (no valid
  reading this build, so it is not called resolved).
* ``event`` -- happened in this session (a name entered the queue). ``new``.
* ``scheduled`` -- a catalyst ahead. ``scheduled``.

The ledger behind the states is carried in the brief itself and read back from
the published site, so a rerun of a session compares with the build before
that session, not with itself (the same rule as MONITOR's ledger).
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
from typing import Any, Callable

from .config import ARTIFACT_DIR, load_config

SCHEMA = "market_recap.agent_feed.v1"
INDEX_FILE = "agent-index.json"
BRIEF_FILE = "agent-brief.json"
INDEX_MAX_BYTES = 16_000
BRIEF_MAX_BYTES = 150_000
DETAIL_DAYS = 7        # catalysts in full
CALENDAR_DAYS = 30     # catalysts as one line each
TOP_CANDIDATES = 15    # in the index; the rest are counted and in the brief
RESOLVED_KEEP_DAYS = 30

# One neutral question per rule: what the reader has to find out, not what to
# conclude. Kinds as in the module docstring.
RULES: dict[str, dict[str, str]] = {
    "risk.breach": {"kind": "condition", "question":
        "What is pushing this measure past its threshold, and is it showing up in other risk channels or in prices yet?"},
    "vol.divergence": {"kind": "condition", "question":
        "Why do bond and equity volatility disagree, and what would make them converge?"},
    "sector.event": {"kind": "condition", "question":
        "Is the sector's move about its earnings outlook, its rate or macro exposure, or positioning?"},
    "sector.estimates_cut": {"kind": "condition", "question":
        "Are estimates being cut faster than the price has fallen?"},
    "sector.sold_off": {"kind": "condition", "question":
        "Has the sell-off moved further than the sector's fundamentals have changed?"},
    "monitor.entered": {"kind": "event", "question":
        "Why is it lagging -- the company, its sector or the market -- and has the earnings outlook changed with it?"},
    "monitor.stabilising": {"kind": "event", "question":
        "Is the recovery backed by estimates and results, or by price alone?"},
    "monitor.weakening": {"kind": "event", "question": "What broke the recovery?"},
    "monitor.evidence_down": {"kind": "event", "question":
        "Does the new evidence change the earnings outlook, or confirm what the price already shows?"},
    "monitor.evidence_up": {"kind": "event", "question": "Is the improvement in the evidence priced yet?"},
    "monitor.reported": {"kind": "event", "question": "Did the result change the outlook, and how did the price take it?"},
    "review.earnings": {"kind": "event", "question":
        "Did the price reaction match the result and the guidance, and what does that say about what was expected?"},
    "catalyst.earnings": {"kind": "scheduled", "question":
        "What is expected and priced, and what result would change the view?"},
    "catalyst.macro": {"kind": "scheduled", "question":
        "What is priced for this release, and which assets are most exposed to a surprise?"},
}
# The index lists candidates in this order: state first, then the rule. An
# ordering, not a score.
STATE_ORDER = ("new", "continuing", "unknown", "resolved", "scheduled")
RULE_ORDER = tuple(RULES)

def _load(root: Path, name: str) -> dict | None:
    try:
        return json.loads((root / f"{name}.json").read_text())
    except (OSError, ValueError):
        return None


def _pick(row: dict | None, *keys: str) -> dict:
    row = row or {}
    return {k: row.get(k) for k in keys}


def _returns(row: dict) -> dict:
    return {k: row[k] for k in ("1D", "1W", "1M", "YTD") if k in row}


class _Feed:
    """The artifacts one build wrote, with the URL each is published at."""

    def __init__(self, root: Path, site: str) -> None:
        self.root, self.site = root, site.rstrip("/")
        self.cache: dict[str, dict | None] = {}
        self.unavailable: dict[str, str] = {}

    def get(self, name: str) -> dict | None:
        if name not in self.cache:
            self.cache[name] = _load(self.root, name)
        return self.cache[name]

    def url(self, name: str) -> str:
        return f"{self.site}/artifacts/{name}.json"

    def section(self, key: str, build: Callable[[], Any]) -> Any:
        """A section that could not be built is named, never left looking empty."""
        try:
            return build()
        except Exception as exc:  # noqa: BLE001 - one broken section must not hide the rest
            self.unavailable[key] = f"{type(exc).__name__}: {str(exc)[:200]}"
            return None


# --- sections ---------------------------------------------------------------

def _risk_budget(f: _Feed) -> dict:
    overview, risk = f.get("overview"), f.get("risk")
    positioning, scenarios, priced = f.get("positioning"), f.get("scenarios"), f.get("priced")
    out: dict[str, Any] = {}
    if risk:
        tiles = [t for s in risk["sections"] for t in s["tiles"]]
        core = [t for t in tiles if t.get("core")]
        out["risk_dashboard"] = {
            "core_tiles": len(core), "core_in_breach": sum(1 for t in core if t.get("breach")),
            "breaches": risk.get("breaches") or [], "crossed_this_session": risk.get("crossed") or [],
            # Every tile, compact: a daily one's 1D is since its own previous
            # observation, and its date can be a session behind the build.
            "tiles": [{**_pick(t, "key", "label", "section", "core", "unit", "frequency", "value", "date",
                               "change_1d", "change_1w", "change_1m", "pct_1y", "pct_long", "risk_when",
                               "threshold", "breach", "crossed"), "section": s.get("key")}
                      for s in risk["sections"] for t in s["tiles"]],
            "source": f.url("risk"),
        }
        out["sentiment"] = {**_pick(risk.get("sentiment"), "score", "rating", "date", "week_ago", "month_ago", "year_ago"),
                            "source": f.url("risk")}
        # The RISK matrix, one line per cell: a grey placeholder keeps its row and column, with no lead.
        out["risk_matrix"] = [_pick(c, "row", "column", "label", "value", "unit", "percentile", "state", "scale", "bands", "since",
                                    "evidence", "caution")
                              for c in (risk.get("matrix") or {}).get("cells") or []]
    if overview and overview.get("vol"):
        out["volatility"] = {**overview["vol"], "source": f.url("overview")}
    if positioning:
        out["trend"] = [{**_pick(t, "key", "state", "score", "close", "as_of"),
                         "flips": [_pick(x, "lookback", "flip_level", "distance_pct") for x in t.get("flips") or []]}
                        for t in positioning.get("trend") or []]
    if scenarios and scenarios.get("regime"):
        out["stock_bond_regime"] = {**scenarios["regime"], "source": f.url("scenarios")}
    if priced or overview:
        meeting = ((priced or {}).get("meetings") or [None])[0]
        fed = (overview or {}).get("fed") or {}
        out["fed"] = {
            "next_meeting": meeting and {**_pick(meeting, "date", "change_bp", "change_1w_bp", "futures_p_hike"),
                                         "ranges": meeting.get("ranges")},
            "year_end": fed.get("year_end"),
            "kalshi_p_hike": fed.get("kalshi_p_hike"), "polymarket_p_hike": fed.get("polymarket_p_hike"),
            "source": f.url("priced"),
        }
    return out


def _market(f: _Feed) -> dict:
    o = f.get("overview")
    if o is None:
        raise ValueError("overview artifact missing")
    return {
        "indices": [{**_pick(r, "key", "label", "last", "date", "from_high_pct", "high_date"), **_returns(r)}
                    for r in o["stocks"]],
        "breadth": [_pick(b, "key", "members", "1D", "1W", "1M", "above_50d", "above_200d", "new_highs", "new_lows")
                    for b in o.get("breadth") or []],
        "equal_minus_cap_pp": (o.get("equal_vs_cap") or {}).get("gap_pp"),
        "rates": [_pick(r, "key", "label", "unit", "value", "date", "change_1d_bp", "change_1w_bp", "change_1m_bp")
                  for r in o.get("rates") or []],
        "cross_asset": [{**_pick(r, "key", "label", "unit", "last", "date"), **_returns(r)}
                        for r in o.get("cross_asset") or []],
        "latest_prints": o.get("prints") or [],
        "index_contribution": o.get("contributions"),
        # Bank groups on tangible book, against their own ten years, with ROTCE.
        "bank_book": o.get("bank_book") or [],
        "source": f.url("overview"),
    }


def _sectors(f: _Feed) -> list[dict]:
    o, monitor, industries = f.get("overview"), f.get("monitor"), f.get("industries")
    if o is None:
        raise ValueError("overview artifact missing")
    mon = {s["sector"]: s for s in (monitor or {}).get("sectors") or []}
    ind = {s["sector"]: s for s in (industries or {}).get("sectors") or []}
    out = []
    for s in o["sectors"]:
        m, i = mon.get(s["sector"]), ind.get(s["sector"])
        out.append({
            "sector": s["sector"], "etf": s["etf"], "weight_pct": s.get("weight_pct"),
            "etf_returns": _returns(s),
            "members_median_excess_1m_pct": (m or {}).get("median_excess_pct"),
            "members_down_share_1m": (m or {}).get("down_share"),
            "queue_candidates": (m or {}).get("candidates"),
            "sector_event": (m or {}).get("event"),
            "above_200d_pct": (i or {}).get("above_ma"),
            "fy1_eps_revision_pct": (i or {}).get("revision"),
            "median_forward_pe": ((i or {}).get("forward_pe") or {}).get("median"),
            "forward_pe_percentile_vs_own_history": ((i or {}).get("pe_percentile") or {}).get("median"),
            "evidence_flags": (i or {}).get("evidence"),
            "sources": [f.url("overview"), f.url("monitor"), f.url("industries")],
        })
    return out


def _name_card(row: dict, changes: list[dict]) -> dict:
    exp = row.get("expectations") or {}
    return {
        "ticker": row.get("ticker"), "name": row.get("name"), "sector": row.get("sector"),
        "watchlist": row.get("membership") == "watchlist",
        "changes": [{"kind": c["kind"], "text": c["text"]} for c in changes],
        "anomaly": row.get("anomaly"), "in_queue": row.get("candidate"),
        "price_state": row.get("price_state"), "evidence_state": row.get("evidence_state"),
        "drawdown_1y_pct": row.get("drawdown_pct"), "peer_excess_1m_pp": row.get("peer_excess_pct"),
        "rs_improving_1m": row.get("rs_improving"), "above_20d_average": row.get("above_ma"),
        "first_seen": (row.get("first_seen") or {}).get("date"),
        "since_first_seen_pct": row.get("since_first_seen_pct"),
        "peers_since_first_seen_pct": row.get("peers_since_first_seen_pct"),
        "fy1_eps_change_30d_pct": exp.get("change_30d_pct"), "fy1_eps_change_90d_pct": exp.get("change_90d_pct"),
        "forward_pe": row.get("pe"), "pe_percentile_own_history": row.get("pe_percentile"),
        # Financials only (empty elsewhere): price over tangible book and what it earns on it.
        "ptbv": row.get("ptbv"), "ptbv_percentile_own_history": row.get("ptbv_percentile"), "rotce_pct": row.get("rotce"),
        "earnings_date": row.get("earnings_date"),
        "evidence_for": row.get("evidence_for") or [], "evidence_against": row.get("evidence_against") or [],
        "gaps": row.get("gaps") or [],
    }


def _names(f: _Feed) -> dict:
    m = f.get("monitor")
    if m is None:
        raise ValueError("monitor artifact missing")
    rows = {r["ticker"]: r for r in m["rows"]}
    by_ticker: dict[str, list[dict]] = {}
    for c in m.get("changes") or []:
        by_ticker.setdefault(c["ticker"], []).append(c)
    cards, exits = [], []
    for ticker, changes in by_ticker.items():
        kinds = {c["kind"] for c in changes}
        row = rows.get(ticker, {"ticker": ticker, "sector": changes[0].get("sector")})
        if kinds <= {"left", "left_index"}:
            # An exit is kept, in one line: it can matter (a recovery), but
            # rarely needs the full card.
            exits.append({**_pick(row, "ticker", "sector", "drawdown_pct", "peer_excess_pct", "price_state",
                                  "since_first_seen_pct"),
                          "watchlist": row.get("membership") == "watchlist",
                          "text": "; ".join(c["text"] for c in changes)})
        else:
            cards.append(_name_card(row, changes))
    queue = [r for r in m["rows"] if r.get("candidate")]

    def count(key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in queue:
            out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
        return dict(sorted(out.items()))

    return {
        "rule": m.get("note"), "settings": m.get("settings"),
        "previous_as_of": m.get("previous_as_of"),
        "queue_size": len(queue),
        "queue_by_price_state": count("price_state"), "queue_by_evidence_state": count("evidence_state"),
        "changed_this_session": cards, "left_the_queue": exits,
        "notices": m.get("notices") or [],
        "source": f.url("monitor"),
    }


def _event_cards(f: _Feed) -> dict[str, dict]:
    events = f.get("events") or {}
    out = {}
    for u in (events.get("upcoming") or []) + (events.get("reported") or []):
        card = u.get("card") or {}
        consensus, priced = card.get("consensus") or {}, card.get("priced") or {}
        out[u["symbol"]] = {
            "consensus_eps": consensus.get("eps"), "consensus_eps_range": [consensus.get("eps_low"), consensus.get("eps_high")],
            "consensus_eps_change_30d_pct": consensus.get("eps_change_30d_pct"),
            "consensus_revenue": consensus.get("revenue"), "eps_growth_pct": consensus.get("eps_growth_pct"),
            "revenue_growth_pct": consensus.get("revenue_growth_pct"),
            "options_implied_move_pct": (priced.get("implied") or {}).get("straddle_pct"),
            "past_mean_abs_move_pct": priced.get("mean_abs"),
            "history": u.get("history_summary"),
            "vs_guide": card.get("vs_guide"),
            "setup": card.get("setup"),
        }
    return out


def _timing(f: _Feed, as_of: str) -> dict:
    c = f.get("catalysts")
    if c is None:
        raise ValueError("catalysts artifact missing")
    detail_end = (date.fromisoformat(as_of) + timedelta(days=DETAIL_DAYS)).isoformat()
    calendar_end = (date.fromisoformat(as_of) + timedelta(days=CALENDAR_DAYS)).isoformat()
    implied = {(a["date"], a.get("title")): a["market"] for a in (f.get("overview") or {}).get("ahead") or []
               if a.get("market")}
    cards = _event_cards(f)
    macro, earnings, calendar = [], [], []
    for e in c["events"]:
        if not as_of < e["date"] <= calendar_end:
            continue
        weight = (e.get("index_weights") or {}).get("SPX")
        if e["date"] <= detail_end and e["importance"] in ("high", "medium"):
            if e["lane"] == "macro":
                row = _pick(e, "date", "time", "title", "importance", "certainty_class", "reference_period", "source_url")
                market = implied.get((e["date"], e["title"]))
                if market:
                    row["market_implied"] = _pick(market, "source", "label", "value", "unit", "low", "high", "open_interest")
                macro.append(row)
            else:
                earnings.append({**_pick(e, "date", "timing", "symbol", "name", "sector", "importance", "watchlist",
                                         "eps_forecast", "estimates", "last_year_eps", "fiscal_quarter"),
                                 "spx_weight_pct": weight, "expectations": cards.get(e.get("symbol"))})
        elif e["importance"] == "high":
            calendar.append({"date": e["date"], "lane": e["lane"],
                             "title": e.get("symbol") or e["title"], "spx_weight_pct": weight})
    earnings.sort(key=lambda e: (e["date"], -(e["spx_weight_pct"] or 0)))
    return {"detail_through": detail_end, "macro": macro, "earnings": earnings,
            "calendar_through": calendar_end, "calendar_high_importance": calendar,
            "sources": [f.url("catalysts"), f.url("events")]}


def _review(f: _Feed) -> dict:
    c, earnings = f.get("catalysts"), f.get("earnings")
    out: dict[str, Any] = {}
    cards = _event_cards(f)
    if c:
        recent = c["recent"]

        def report(e: dict) -> dict:
            return {**_pick(e, "symbol", "name", "sector", "timing", "importance", "watchlist", "eps_forecast", "eps",
                            "surprise_pct", "return_1d", "result_pending"),
                    "spx_weight_pct": (e.get("index_weights") or {}).get("SPX"),
                    "expectations": cards.get(e.get("symbol"))}

        out["last_session"] = {
            "session": recent["session"], "macro": recent.get("macro") or [],
            "earnings_reacted": [report(e) for e in recent.get("earnings_reacted") or []],
            "earnings_after_close": [report(e) for e in recent.get("earnings_after_close") or []],
            "market": recent.get("market"), "source": f.url("catalysts"),
        }
    if earnings and earnings.get("season"):
        s = earnings["season"]
        out["earnings_season"] = {
            **_pick(s, "quarter", "universe", "reported", "beat", "miss", "in_line", "beat_share",
                    "median_surprise_pct", "aggregate_surprise_pct", "growth_yoy_pct", "growth_companies"),
            "result_not_posted": s.get("pending") or [],
            "factset": _pick((earnings.get("factset") or {}).get("snapshot"), "report_date", "blended_earnings_growth_yoy",
                             "blended_revenue_growth_yoy", "forward_12m_pe", "forward_12m_pe_10y_avg",
                             "positive_eps_guidance_count", "negative_eps_guidance_count", "season_source_url"),
            "source": f.url("earnings"),
        }
    return out


def _data_quality(f: _Feed, validation: dict | None) -> dict:
    m = f.get("manifest") or {}
    sources = m.get("sources") or []
    counts: dict[str, int] = {}
    for s in sources:
        counts[s.get("freshness") or "unknown"] = counts.get(s.get("freshness") or "unknown", 0) + 1
    flagged = [_pick(s, "source_id", "label", "observed_date", "policy", "freshness", "status", "error")
               for s in sources
               if s.get("freshness") in ("stale", "unknown") or s.get("status") not in ("ok", "skipped", None)]
    return {
        "how_freshness_is_judged": ("each source by its own publishing schedule (manifest 'policy': daily close 7 days, "
                                    "weekly release 16, monthly release 100, ...), dated by the period it describes"),
        "validation": None if validation is None else {
            "deployable": validation.get("deployable"), "errors": validation.get("errors"),
            "warnings": validation.get("warnings"), "notices": validation.get("notices"),
            "findings": [x for x in validation.get("findings") or [] if x.get("severity") != "info"],
        },
        "sources_total": len(sources), "freshness_counts": counts, "flagged_sources": flagged,
        "skipped_panels": m.get("skipped_panels") or [], "panel_errors": m.get("errors") or {},
        "session_check": m.get("session_check"), "holdings_as_of": m.get("holdings_as_of"),
        "sections_unavailable": f.unavailable,
    }


# --- candidates -------------------------------------------------------------

def _candidate(rule_id: str, entity: str, trigger: str, pointer: str, *, cid: str | None = None,
               watchlist: bool | None = None, weight: float | None = None, values: dict | None = None) -> dict:
    return {"id": cid or f"{rule_id}:{entity}", "rule_id": rule_id, "kind": RULES[rule_id]["kind"],
            "entity": entity, "trigger": trigger, "values": values or {}, "watchlist": watchlist,
            "spx_weight_pct": weight, "question": RULES[rule_id]["question"], "pointer": pointer}


def _raised(brief: dict, f: _Feed) -> tuple[list[dict], set[str]]:
    """Candidates raised this build, and the rule families that had valid data
    (a condition missing from a family that had none is unknown, not resolved)."""
    out: list[dict] = []
    evaluated: set[str] = set()
    rb = brief.get("risk_budget") or {}
    risk = f.get("risk")
    if risk is not None:
        evaluated.add("risk")
        crossed = {t["key"] for t in risk.get("crossed") or []}
        for t in risk.get("breaches") or []:
            out.append(_candidate(
                "risk.breach", t["key"],
                f"{t['label']} at {t['value']} {t['unit']} is past its threshold ({t.get('horizon')} horizon)"
                + ("; crossed this session" if t["key"] in crossed else ""),
                "risk.json#/breaches", values=_pick(t, "label", "section", "horizon", "value", "unit", "crossed")))
    vol = rb.get("volatility")
    if vol and vol.get("reading"):
        evaluated.add("vol")
        if vol["reading"] != "in_line":
            out.append(_candidate(
                "vol.divergence", vol["reading"],
                f"MOVE {vol.get('move')} ({vol.get('move_pct_1y')}th pct, 1Y) against VIX {vol.get('vix')} "
                f"({vol.get('vix_pct_1y')}th pct): reading '{vol['reading']}'",
                "overview.json#/vol", values=_pick(vol, "move", "move_pct_1y", "vix", "vix_pct_1y", "ratio", "ratio_pct")))
    sectors = brief.get("sectors")
    if sectors:
        evaluated.add("sector")
        for s in sectors:
            flags = s.get("evidence_flags") or {}
            values = _pick(s, "etf_returns", "members_median_excess_1m_pct", "fy1_eps_revision_pct",
                           "forward_pe_percentile_vs_own_history")
            if s.get("sector_event"):
                out.append(_candidate("sector.event", s["etf"], f"{s['sector']}: members trail the market as a group",
                                      "monitor.json#/sectors", values=values, weight=s.get("weight_pct")))
            for flag, rule in (("estimates_cut", "sector.estimates_cut"), ("sold_off", "sector.sold_off")):
                if flags.get(flag):
                    out.append(_candidate(rule, s["etf"], f"{s['sector']}: {flag.replace('_', ' ')}",
                                          "industries.json#/sectors", values=values, weight=s.get("weight_pct")))
    names = brief.get("names")
    if names:
        for card in names["changed_this_session"]:
            for ch in card["changes"]:
                rule = f"monitor.{ch['kind']}"
                if rule not in RULES:
                    continue
                out.append(_candidate(rule, card["ticker"], ch["text"], f"monitor.json#/rows[ticker={card['ticker']}]",
                                      cid=f"{rule}:{card['ticker']}:{brief['as_of']}", watchlist=card["watchlist"],
                                      values=_pick(card, "price_state", "evidence_state", "drawdown_1y_pct",
                                                   "peer_excess_1m_pp", "fy1_eps_change_30d_pct")))
    review = (brief.get("review") or {}).get("last_session") or {}
    for e in review.get("earnings_reacted") or []:
        if e.get("importance") in ("high", "medium") or e.get("watchlist"):
            result = ("result not posted yet" if e.get("result_pending") else
                      f"EPS {e.get('eps')} vs {e.get('eps_forecast')} ({e.get('surprise_pct')}%)")
            out.append(_candidate("review.earnings", e["symbol"], f"{result}; 1D {e.get('return_1d')}%",
                                  "catalysts.json#/recent/earnings_reacted",
                                  cid=f"review.earnings:{e['symbol']}:{review['session']}", watchlist=e.get("watchlist"),
                                  weight=e.get("spx_weight_pct"),
                                  values=_pick(e, "eps", "eps_forecast", "surprise_pct", "return_1d", "result_pending")))
    timing = brief.get("timing") or {}
    for e in timing.get("earnings") or []:
        if e["importance"] == "high" or e.get("watchlist"):
            out.append(_candidate("catalyst.earnings", e["symbol"], f"reports {e['date']} {e.get('timing') or ''}".rstrip(),
                                  "catalysts.json#/events", cid=f"catalyst.earnings:{e['symbol']}:{e['date']}",
                                  watchlist=e.get("watchlist"), weight=e.get("spx_weight_pct")))
    for e in timing.get("macro") or []:
        if e["importance"] == "high":
            slug = "".join(ch if ch.isalnum() else "-" for ch in e["title"].lower()).strip("-")
            out.append(_candidate("catalyst.macro", e["title"], f"{e['title']} {e['date']} {e.get('time') or ''}".rstrip(),
                                  "catalysts.json#/events", cid=f"catalyst.macro:{slug}:{e['date']}",
                                  values={"market_implied": e.get("market_implied")}))
    return out, evaluated


def _family(rule_id: str) -> str:
    return rule_id.split(".")[0]


def track(raised: list[dict], evaluated: set[str], as_of: str, base: dict | None) -> tuple[list[dict], dict]:
    """States for this build's candidates, plus the ledger to publish.

    ``base`` is the ledger as of the previous session, ``None`` when there is
    no previous feed, or ``{"unreadable": reason}`` when it could not be read
    (every condition is then ``unknown`` rather than ``new``).
    """
    unreadable = bool(base and base.get("unreadable"))
    entries: dict[str, dict] = {} if base is None or unreadable else dict(base.get("entries") or {})
    ledger: dict[str, dict] = {}
    out = []
    for c in raised:
        old = entries.get(c["id"])
        kind = c["kind"]
        if kind == "event":
            state, first = "new", as_of
        elif kind == "scheduled":
            state, first = "scheduled", (old or {}).get("first_seen") or as_of
        elif unreadable:
            state, first = "unknown", None
        elif old and old.get("state") in ("new", "continuing", "unknown"):
            state, first = "continuing", old.get("first_seen")
        else:
            state, first = "new", as_of
        c = {**c, "state": state, "first_seen": first, "last_confirmed": as_of}
        out.append(c)
        if kind != "event":
            ledger[c["id"]] = {"rule_id": c["rule_id"], "entity": c["entity"], "state": state,
                               "first_seen": first, "last_confirmed": as_of}
    raised_ids = {c["id"] for c in raised}
    cutoff = (date.fromisoformat(as_of) - timedelta(days=RESOLVED_KEEP_DAYS)).isoformat()
    for cid, old in entries.items():
        if cid in raised_ids or old.get("rule_id") not in RULES:
            continue
        if RULES[old["rule_id"]]["kind"] == "scheduled":
            continue  # a catalyst that passed is in the review, not carried
        if old.get("state") == "resolved":
            if (old.get("resolved") or "") >= cutoff:
                ledger[cid] = old
            continue
        if _family(old["rule_id"]) in evaluated:
            state = {**old, "state": "resolved", "resolved": as_of}
        else:
            state = {**old, "state": "unknown"}
        ledger[cid] = state
        out.append({**_candidate(old["rule_id"], old["entity"],
                                 "no longer met on valid data" if state["state"] == "resolved"
                                 else "no valid reading this build", "", cid=cid),
                    "state": state["state"], "first_seen": old.get("first_seen"),
                    "last_confirmed": old.get("last_confirmed")})
    return out, ledger


def _order(c: dict) -> tuple:
    return (STATE_ORDER.index(c["state"]), RULE_ORDER.index(c["rule_id"]),
            0 if c.get("watchlist") else 1, -(c.get("spx_weight_pct") or 0), c["id"])


# --- the files --------------------------------------------------------------

def _previous(site: str, fetch: Callable[[str], str] | None) -> tuple[dict | None, str | None]:
    """The published brief, or None with why. A missing or non-JSON file is
    'no previous feed'; a failed fetch is reported, so states become unknown."""
    from .sources.http import FetchError, get_text
    fetch = fetch or (lambda url: get_text(url, timeout=20.0, retries=1))
    try:
        payload = json.loads(fetch(f"{site.rstrip('/')}/artifacts/{BRIEF_FILE}"))
    except FetchError as exc:
        return None, None if exc.not_found else f"previous feed unreadable: {exc}"
    except ValueError:
        return None, None  # the site's page, not a feed: none published yet
    return (payload if isinstance(payload, dict) and payload.get("schema") == SCHEMA else None), None


def _base(previous: dict | None, problem: str | None, as_of: str) -> tuple[dict | None, str | None]:
    """The ledger to compare with: the previous session's, never this one's."""
    if problem:
        return {"unreadable": problem}, None
    if previous is None:
        return None, None
    ledger = previous.get("candidate_ledger") or {}
    if ledger.get("as_of", "") < as_of:
        return ledger, ledger.get("as_of")
    base = previous.get("ledger_base")   # a rerun of the same session
    if ledger.get("as_of") == as_of:
        return base, (base or {}).get("as_of")
    return {"unreadable": f"previous feed is for {ledger.get('as_of')}, after this build's {as_of}"}, None


def build(*, root: Path | None = None, validation: dict | None = None,
          fetch: Callable[[str], str] | None = None, site: str | None = None) -> tuple[dict, dict]:
    """``(index, brief)`` from the artifacts in ``root``."""
    root = root or ARTIFACT_DIR
    site = site or load_config()["monitor"]["published_base_url"]
    f = _Feed(root, site)
    manifest = f.get("manifest")
    if manifest is None:
        raise ValueError("no manifest: nothing to condense")
    as_of = manifest["as_of"]
    previous, problem = _previous(site, fetch)
    base, compared_with = _base(previous, problem, as_of)

    header = {
        "schema": SCHEMA, "domain": "us_market", "as_of": as_of, "edition": manifest.get("edition"),
        "generated_at": manifest.get("generated_at"), "source_commit": os.environ.get("GITHUB_SHA"),
        "site": site, "index_url": f"{site}/artifacts/{INDEX_FILE}", "brief_url": f"{site}/artifacts/{BRIEF_FILE}",
        "compared_with": compared_with,
        "how_to_read": (
            "Every number is copied from a published artifact; nothing is recomputed, and each section names its "
            "source for drill-down. Dates are New York sessions; each observation keeps its own date. "
            "Candidates are raised by fixed rules and carry a neutral question, not a verdict. State: new / "
            "continuing / resolved (valid new data shows it ended) / unknown (no valid reading this build) for "
            "conditions, compared with the previous published session; event = this session; scheduled = ahead. "
            "The close edition (16:20 New York) leaves news to the evening edition (18:35); read the evening one."
        ),
    }
    brief: dict[str, Any] = {**header}
    brief["risk_budget"] = f.section("risk_budget", lambda: _risk_budget(f))
    brief["market"] = f.section("market", lambda: _market(f))
    brief["sectors"] = f.section("sectors", lambda: _sectors(f))
    brief["names"] = f.section("names", lambda: _names(f))
    brief["timing"] = f.section("timing", lambda: _timing(f, as_of))
    brief["review"] = f.section("review", lambda: _review(f))
    raised, evaluated = _raised(brief, f)
    candidates, ledger = track(raised, evaluated, as_of, base)
    candidates.sort(key=_order)
    brief["research_candidates"] = candidates
    brief["data_quality"] = _data_quality(f, validation)
    if base and base.get("unreadable"):
        brief["data_quality"]["candidate_states"] = base["unreadable"]
    brief["candidate_ledger"] = {"as_of": as_of, "entries": ledger}
    brief["ledger_base"] = None if not base or base.get("unreadable") else base

    index = {**header, "market_state": _market_state(brief, f), "candidates": _index_candidates(candidates),
             "next_7_days": _next_week(brief), "data_quality_alerts": _alerts(brief)}
    return index, brief


def _market_state(brief: dict, f: _Feed) -> dict:
    market, rb, review = brief.get("market") or {}, brief.get("risk_budget") or {}, brief.get("review") or {}
    vol = rb.get("volatility") or {}
    breadth = next((b for b in market.get("breadth") or [] if b["key"] == "SPX"), {})
    season = review.get("earnings_season") or {}
    next_meeting = (rb.get("fed") or {}).get("next_meeting") or {}
    return {
        "indices": [_pick(r, "key", "last", "1D", "1M", "YTD", "from_high_pct") for r in market.get("indices") or []],
        "rates": [_pick(r, "key", "value", "unit", "change_1d_bp", "change_1m_bp") for r in market.get("rates") or []],
        "breadth_spx": _pick(breadth, "above_50d", "above_200d", "new_highs", "new_lows"),
        "equal_minus_cap_pp": market.get("equal_minus_cap_pp"),
        "volatility": _pick(vol, "reading", "move", "move_pct_1y", "vix", "vix_pct_1y"),
        "sentiment": _pick(rb.get("sentiment"), "score", "rating", "week_ago"),
        "trend": [_pick(t, "key", "state") | {"flip_1m_distance_pct": next(
            (x["distance_pct"] for x in t.get("flips") or [] if x.get("lookback") == "1M"), None)}
            for t in rb.get("trend") or []],
        "risk_tiles_in_breach": (rb.get("risk_dashboard") or {}).get("core_in_breach"),
        "fed_next_meeting": _pick(next_meeting, "date", "change_bp", "futures_p_hike"),
        "earnings_season": _pick(season, "quarter", "reported", "beat_share", "median_surprise_pct")
        | {"result_not_posted": [r["symbol"] for r in season.get("result_not_posted") or []]} if season else None,
    }


def _short(c: dict) -> dict:
    return {k: c.get(k) for k in ("id", "state", "rule_id", "entity", "trigger", "question", "first_seen",
                                  "watchlist") if c.get(k) is not None}


def _index_candidates(candidates: list[dict]) -> dict:
    listed = [c for c in candidates if c["kind"] != "scheduled"]
    counts: dict[str, int] = {}
    for c in candidates:
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    return {"counts": counts, "top": [_short(c) for c in listed[:TOP_CANDIDATES]],
            "not_listed_here": max(0, len(listed) - TOP_CANDIDATES),
            "scheduled": "see next_7_days; every candidate is in the brief"}


def _next_week(brief: dict) -> list[dict]:
    timing = brief.get("timing") or {}
    out = [{"date": e["date"], "time": e.get("time"), "what": e["title"], "importance": e["importance"],
            "market_implied": e.get("market_implied")} for e in timing.get("macro") or []]
    out += [{"date": e["date"], "time": e.get("timing"), "what": f"{e['symbol']} earnings",
             "importance": e["importance"], "spx_weight_pct": e.get("spx_weight_pct"),
             "implied_move_pct": (e.get("expectations") or {}).get("options_implied_move_pct")}
            for e in timing.get("earnings") or [] if e["importance"] == "high" or e.get("watchlist")]
    return sorted(out, key=lambda e: (e["date"], e.get("time") or ""))


def _alerts(brief: dict) -> list[str]:
    dq = brief["data_quality"]
    out = [f"{x['severity']}: {x['check']}: {x['detail']}" for x in ((dq.get("validation") or {}).get("findings") or [])]
    out += [f"source {s['source_id']}: {s['status']}, {s['freshness']}" + (f" -- {s['error']}" if s.get("error") else "")
            for s in dq["flagged_sources"]]
    out += [f"section unavailable: {k}: {v}" for k, v in dq["sections_unavailable"].items()]
    if dq.get("candidate_states"):
        out.append(f"candidate states unknown: {dq['candidate_states']}")
    return out


def check(index: dict, brief: dict, root: Path) -> list[str]:
    """What would make the pair unsafe to publish."""
    problems = []
    for name, payload, limit in ((INDEX_FILE, index, INDEX_MAX_BYTES), (BRIEF_FILE, brief, BRIEF_MAX_BYTES)):
        size = len(json.dumps(payload, ensure_ascii=False).encode())
        if size > limit:
            problems.append(f"{name} is {size} bytes, over its {limit}")
        if payload.get("schema") != SCHEMA or not payload.get("as_of"):
            problems.append(f"{name} has no schema or as_of")
    ids = {c["id"] for c in brief["research_candidates"]}
    if len(ids) != len(brief["research_candidates"]):
        problems.append("candidate ids are not unique")
    for c in brief["research_candidates"]:
        if c["rule_id"] not in RULES or not c.get("question"):
            problems.append(f"{c['id']}: unknown rule or no question")
        target = (c.get("pointer") or "").split("#")[0]
        if target and not (root / target).exists():
            problems.append(f"{c['id']}: points at {target}, which this build did not write")
    for c in index["candidates"]["top"]:
        if c["id"] not in ids:
            problems.append(f"index candidate {c['id']} is not in the brief")
    return problems


def write(*, root: Path | None = None, validation: dict | None = None,
          fetch: Callable[[str], str] | None = None) -> dict:
    """Build, check and write both files. On any problem neither is left on
    disk: an old feed must not be published as this build's."""
    root = root or ARTIFACT_DIR
    paths = [root / INDEX_FILE, root / BRIEF_FILE]
    try:
        index, brief = build(root=root, validation=validation, fetch=fetch)
        problems = check(index, brief, root)
    except Exception as exc:  # noqa: BLE001 - the feed is optional; the dashboard is not
        problems = [f"{type(exc).__name__}: {str(exc)[:300]}"]
    if problems:
        for path in paths:
            path.unlink(missing_ok=True)
        return {"written": False, "problems": problems}
    for path, payload in zip(paths, (index, brief)):
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"written": True, "as_of": index["as_of"], "candidates": index["candidates"]["counts"],
            "bytes": {INDEX_FILE: paths[0].stat().st_size, BRIEF_FILE: paths[1].stat().st_size},
            "sections_unavailable": brief["data_quality"]["sections_unavailable"]}
