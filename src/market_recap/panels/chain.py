"""CHAIN: the AI supply chain, its reporting season, and what a report has
carried down (or up) the chain before.

The graph is config/ai_chain.toml, each link checked against both companies'
SEC filings (config/ai_chain_evidence.json). Reports come from Yahoo's
earnings archive and recent quarters for every company, Korean preliminary
results from DART, and -- for a US filer the site already covers -- the day
and timing of its SEC release with Nasdaq's surprise (EVENTS). Prices are
each company's home line against its home index.

The study (compute.chain) runs over today's graph applied to every past
report: a link formed in 2024 is assumed in 2016 too. It is labelled so, and
nothing here is a signal.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import json
import tomllib

import pandas as pd

from .. import cache
from ..compute import chain as C
from ..compute import events as E
from ..config import CHAIN_EVIDENCE_PATH, CHAIN_PATH, EVENTS_ARTIFACT_DIR
from ..sources import dart, earnings_history, yahoo
from ..util import SourceRecord, describe_error

INPUTS = ("catalysts",)
HISTORY = "10y"
WORKERS = 4
# The study's second window: the AI build-out, from ChatGPT's first full year.
RECENT_SINCE = "2023-01-01"
CATEGORY_LABELS = {
    "from_customer": "a customer reported; its supplier followed",
    "from_supplier": "a supplier reported; its customer followed",
    "competitor": "a competitor reported",
    "partner": "a partner reported",
    "unlinked": "no link (both in the chain)",
}


def load_graph() -> dict:
    graph = tomllib.loads(CHAIN_PATH.read_text(encoding="utf-8"))
    groups = graph.get("groups") or {}
    edges = []
    for e in graph.get("edges") or []:
        for target in e["to"]:
            members = groups[target[1:]] if target.startswith("@") else [target]
            for member in members:
                if member == e["from"]:
                    continue
                edges.append({"from": e["from"], "to": member, "type": e["type"], "reason": e["reason"],
                              "named": not target.startswith("@"), "group": target[1:] if target.startswith("@") else None,
                              "source": e.get("source")})
    graph["edge_list"] = edges
    return graph


def categories(edges: list[dict]) -> dict[tuple[str, str], tuple[str, bool]]:
    """(lead, follower) -> (category, named). A pair linked twice keeps the
    supply link, then the partnership, then the rivalry."""
    rank = {"from_customer": 0, "from_supplier": 0, "partner": 1, "competitor": 2}
    out: dict[tuple[str, str], tuple[str, bool]] = {}

    def put(key, value):
        if key not in out or rank[value[0]] < rank[out[key][0]] or (rank[value[0]] == rank[out[key][0]] and value[1] and not out[key][1]):
            out[key] = value

    for e in edges:
        a, b = e["from"], e["to"]
        if e["type"] == "supplies":
            put((b, a), ("from_customer", e["named"]))   # the customer reports, the supplier follows
            put((a, b), ("from_supplier", e["named"]))
        elif e["type"] == "partner":
            put((a, b), ("partner", e["named"]))
            put((b, a), ("partner", e["named"]))
        else:
            put((a, b), ("competitor", e["named"]))
            put((b, a), ("competitor", e["named"]))
    return out


def _closes(ctx, graph: dict, markets: dict[str, C.Market]) -> pd.DataFrame:
    """Every node's and every market index's daily closes, through the page's
    session (an Asian session dated after it has not closed by the build)."""
    have = set(ctx.closes.columns)
    wanted = sorted({n.get("yahoo", n["key"]) for n in graph["nodes"] if n.get("yahoo", n["key"]) not in have}
                    | {m.index for m in markets.values()} - set(ctx.index_closes.columns))
    fetched = cache.frame("chain", "closes", lambda: yahoo.fetch_closes(wanted, period=HISTORY, use_cache=False),
                          kind="daily_file") if wanted else pd.DataFrame()
    missing = [s for s in wanted if s not in fetched.columns]
    if missing and not fetched.empty:
        # A cached frame from before a node was added lacks it: fetch just those.
        extra = yahoo.fetch_closes(missing, period=HISTORY, use_cache=False)
        fetched = fetched.join(extra, how="outer") if not extra.empty else fetched
    frames = [ctx.closes, ctx.index_closes]
    if not fetched.empty:
        fetched.index = pd.to_datetime(fetched.index)
        frames.append(fetched)
    out = pd.concat(frames, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    return out.loc[:pd.Timestamp(ctx.as_of)].sort_index()


def _site_history(key: str, as_of: str) -> list[dict]:
    """EVENTS' per-report rows for a name the site covers: the SEC release's
    day and timing, and Nasdaq's surprise."""
    try:
        payload = json.loads((EVENTS_ARTIFACT_DIR / f"{key}.json").read_text())
    except (OSError, ValueError):
        return []
    if payload.get("as_of") != as_of:
        return []
    return payload.get("history") or []


def _us_side(ts: str) -> tuple[str, str]:
    """The New York day of an instant and whether it fell before, during or
    after that day's session -- the terms SEC release timing is kept in."""
    at = pd.Timestamp(ts).tz_convert("America/New_York")
    clock = at.hour * 60 + at.minute
    return at.date().isoformat(), "bmo" if clock < 9 * 60 + 30 else "amc" if clock >= 16 * 60 else "intraday"


def _reports(node: dict, market: C.Market, as_of: date) -> tuple[list[dict], dict | None, list[str]]:
    """Every report the node is known to have made: Yahoo's, with a US
    filer's SEC day and timing laid over it, and a Korean filer's DART
    preliminary results added."""
    symbol = node.get("yahoo", node["key"])
    rows, upcoming, errors = earnings_history.history(symbol)
    site = _site_history(node["key"], as_of.isoformat())
    for h in site:
        day = pd.Timestamp(h["date"])
        match = next((r for r in rows if abs((pd.Timestamp(r["ts"]).tz_convert(market.tz).tz_localize(None).normalize() - day).days) <= 3), None)
        if match is not None:
            # Yahoo's clock time stands when it agrees with the SEC release on
            # the day and on which side of New York's session it fell: an ADR's
            # "bmo" release came out at 07:00 in Amsterdam, not New York.
            if not (match.get("timed") and _us_side(match["ts"]) == (h["date"], h.get("timing"))):
                match.update({"local": h["date"], "timing": h.get("timing")})
            match["source"] = match["source"] + "+sec"
            if match.get("surprise_pct") is None and h.get("surprise_pct") is not None:
                match["surprise_pct"] = h["surprise_pct"]
        else:
            rows.append({"ts": pd.Timestamp(h["date"]).tz_localize(market.tz).isoformat(), "local": h["date"],
                         "timing": h.get("timing"), "timed": False, "surprise_pct": h.get("surprise_pct"), "source": "sec"})
    if node.get("dart"):
        try:
            filings = dart.results(node["dart"], as_of, years=10)
        except Exception as exc:  # noqa: BLE001 - Yahoo's rows still stand
            filings = []
            errors.append(f"dart: {describe_error(exc)}")
        for f in filings:
            day = pd.Timestamp(f["date"])
            near = [r for r in rows if abs((pd.Timestamp(r["ts"]).tz_convert(market.tz).tz_localize(None).normalize() - day).days) <= 3]
            if near:
                continue
            rows.append({"ts": day.tz_localize(market.tz).isoformat(), "local": f["date"], "timing": "bmo", "timed": False,
                         "surprise_pct": None, "source": "dart_preliminary", "url": f["url"]})
    rows = [r for r in rows if pd.Timestamp(r["ts"]).date() <= as_of]
    rows.sort(key=lambda r: pd.Timestamp(r["ts"]))
    return rows, upcoming, errors


def _next_report(node: dict, upcoming: dict | None, catalysts: dict | None, as_of: date) -> dict | None:
    for e in (catalysts or {}).get("events") or []:
        if e.get("event_type") == "earnings" and e.get("symbol") == node["key"] and e["date"] > as_of.isoformat():
            return {"date": e["date"], "timing": e.get("timing"), "source": "calendar", "estimated": False}
    if upcoming:
        day = pd.Timestamp(upcoming["ts"]).date()
        if day > as_of:
            return {"date": day.isoformat(), "timing": None, "source": "yahoo", "estimated": upcoming.get("estimated")}
    return None


def _ret(series: C.Series | None, sessions: int) -> float | None:
    if series is None or len(series.excess) <= sessions:
        return None
    return round(float(series.excess.iloc[-sessions:].sum()), 2)


def build(ctx, *, inputs: dict | None = None) -> dict:
    inputs = inputs or {}
    as_of = date.fromisoformat(ctx.as_of)
    graph = load_graph()
    markets = {k: C.market_from(k, v) for k, v in (graph.get("markets") or {}).items()}
    nodes = {n["key"]: n for n in graph["nodes"]}
    try:
        evidence = json.loads(CHAIN_EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        evidence = {"edges": {}}

    closes = _closes(ctx, graph, markets)
    series: dict[str, C.Series] = {}
    for key, node in nodes.items():
        market = markets[node["market"]]
        symbol = node.get("yahoo", key)
        if symbol in closes.columns and market.index in closes.columns:
            excess = C.daily_excess(closes[symbol], closes[market.index])
            if len(excess) > 60:
                series[key] = C.Series(excess, market)

    with ThreadPoolExecutor(WORKERS) as pool:
        fetched = dict(zip(nodes, pool.map(lambda k: _reports(nodes[k], markets[nodes[k]["market"]], as_of), nodes)))
    reports = {k: C.reports_for(rows, series.get(k), markets[nodes[k].get("releases", nodes[k]["market"])])
               for k, (rows, _, _) in fetched.items()}
    failed = {k: errs for k, (_, _, errs) in fetched.items() if errs}

    cats = categories(graph["edge_list"])
    rows: list[dict] = []
    for lead in nodes:
        if not reports[lead]:
            continue
        for follow, s in series.items():
            if follow == lead:
                continue
            category, named = cats.get((lead, follow), ("unlinked", False))
            for r in C.pair_records(lead, reports[lead], follow, s, reports[follow]):
                r["category"], r["named"] = category, named
                rows.append(r)

    study = _study(rows)
    study["layers"] = _layers(rows, nodes)
    edges = _edges(graph["edge_list"], rows, evidence.get("edges") or {})
    season = _season(nodes, reports, series, rows, cats, as_of, fetched, inputs.get("catalysts"))

    covered = sum(1 for k in nodes if reports[k])
    ctx.log.add(SourceRecord("chain_earnings", "AI-chain earnings history (Yahoo archive and recent quarters, DART, SEC)",
                             earnings_history.PAGE_URL.format(symbol="NVDA"), ctx.as_of, rows=sum(len(v) for v in reports.values()),
                             status="ok" if covered >= 0.9 * len(nodes) else "partial",
                             error=f"{len(nodes) - covered} of {len(nodes)} companies without reports" if covered < len(nodes) else None))
    ctx.log.add(SourceRecord("chain_prices", "AI-chain home-market closes and indices (Yahoo)", "https://finance.yahoo.com",
                             ctx.as_of, rows=len(series), status="ok" if len(series) >= 0.9 * len(nodes) else "partial",
                             error=None if len(series) == len(nodes) else
                             "no prices: " + ", ".join(sorted(set(nodes) - set(series)))))
    return {
        "as_of": ctx.as_of,
        "layers": graph.get("layers") or [],
        "markets": {k: {"tz": m.tz, "close": m.close.strftime("%H:%M"), "index": m.index} for k, m in markets.items()},
        "nodes": [_node(nodes[k], series.get(k), reports[k], fetched[k][1], inputs.get("catalysts"), as_of, season)
                  for k in nodes],
        "edges": edges,
        "season": season["summary"],
        "replay": _replay(nodes, series, reports, as_of),
        "study": study,
        "evidence_checked": evidence.get("checked"),
        "failed": failed,
    }


def _node(node: dict, s: C.Series | None, reps: list[C.Report], upcoming: dict | None, catalysts: dict | None,
          as_of: date, season: dict) -> dict:
    last = next((r for r in reversed(reps) if r.own_at is not None), None)
    return {
        "key": node["key"], "name": node["name"], "layer": node["layer"], "market": node["market"],
        "site": (EVENTS_ARTIFACT_DIR / f"{node['key']}.json").exists(),
        "priced": s is not None,
        "ret_1m": _ret(s, 21), "ret_3m": _ret(s, 63),
        "reports": len(reps), "reports_since": reps[0].info.date().isoformat() if reps else None,
        "last": None if last is None else {
            "date": last.info.date().isoformat(), "session": s.day(last.own_at) if s is not None else None,
            "surprise": None if last.surprise is None else round(last.surprise, 2),
            "move": None if last.own_move is None else round(last.own_move, 2), "source": last.source},
        "next": _next_report(node, upcoming, catalysts, as_of),
        "season": season["nodes"].get(node["key"]),
    }


def _study(rows: list[dict]) -> dict:
    out = {"graph": "current", "since": None, "categories": {}, "recent_since": RECENT_SINCE}
    if not rows:
        return out
    out["since"] = min(r["lead_day"] for r in rows)
    for period, part in (("all", rows), ("recent", [r for r in rows if r["lead_day"] >= RECENT_SINCE])):
        block = {}
        for cat, label in CATEGORY_LABELS.items():
            chosen = [r for r in part if r["category"] == cat]
            if not chosen:
                continue
            block[cat] = {"label": label, **C.summarise(chosen), "priced_in": C.priced_in(chosen)}
            named = [r for r in chosen if r["named"]]
            if cat in ("from_customer", "from_supplier") and named and len(named) < len(chosen):
                block[cat]["named_only"] = C.summarise(named)["immediate"]
        out["categories"][period] = block
    return out


# A cell names its firmest pairs: the ordered pairs whose same-session
# read-through has the largest t over at least this many reports.
TOP_PAIRS = 3
PAIR_MIN_REPORTS = 8


def _layers(rows: list[dict], nodes: dict) -> dict:
    """The layer-by-layer matrix, over all years and since RECENT_SINCE, each
    cell with its firmest pairs."""
    layer_of = {k: n["layer"] for k, n in nodes.items()}
    out = {}
    for period, part in (("all", rows), ("recent", [r for r in rows if r["lead_day"] >= RECENT_SINCE])):
        matrix = C.layer_matrix(part, layer_of)
        by_pair: dict[tuple[str, str], list[dict]] = {}
        for r in part:
            by_pair.setdefault((r["lead"], r["follow"]), []).append(r)
        best: dict[tuple[str, str], list[dict]] = {}
        for (lead, follow), pair in by_pair.items():
            stats = E.co_move([r["lead_move"] for r in pair], [r["follow_move"] for r in pair], min_reports=PAIR_MIN_REPORTS)
            if stats and stats["t"] is not None and stats["t"] > 0:
                best.setdefault((layer_of[lead], layer_of[follow]), []).append(
                    {"lead": lead, "follow": follow, "beta": stats["beta"], "t": stats["t"], "n": stats["n"]})
        for (a, b), pairs in best.items():
            if a in matrix and b in matrix[a]:
                matrix[a][b]["top"] = sorted(pairs, key=lambda p: -p["t"])[:TOP_PAIRS]
        out[period] = matrix
    return out


def _edges(edge_list: list[dict], rows: list[dict], evidence: dict) -> list[dict]:
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by_pair.setdefault((r["lead"], r["follow"]), []).append(r)
    out = []
    for e in edge_list:
        stats = {}
        for lead, follow in ((e["from"], e["to"]), (e["to"], e["from"])):
            pair = by_pair.get((lead, follow)) or []
            moved = E.co_move([r["lead_move"] for r in pair], [r["follow_move"] for r in pair], min_reports=8)
            if moved:
                drift = [r["drift"] * (1 if r["lead_move"] > 0 else -1) for r in pair if r.get("drift") is not None and r["lead_move"]]
                moved["drift_signed"] = round(sum(drift) / len(drift), 2) if len(drift) >= 8 else None
                moved["since"] = min(r["lead_day"] for r in pair)
            stats[f"{lead}>{follow}"] = moved
        ev = evidence.get(f"{e['from']}>{e['to']}") or {}
        out.append({**{k: e[k] for k in ("from", "to", "type", "reason", "named", "group")},
                    "evidence": {k: ev.get(k) for k in ("strength", "filer", "form", "filed", "url", "text")} if ev.get("filer") else
                    ({"strength": "group"} if not e["named"] else {"strength": "unverified", "source": e.get("source")}),
                    "stats": stats})
    return out


# Seasons the replay carries: this one and the one before, so the early days
# of a new season still have a whole season to play.
REPLAY_SEASONS = 2


def _replay(nodes: dict, series: dict[str, C.Series], reports: dict[str, list[C.Report]], as_of: date) -> list[dict]:
    """Per season: its sessions (every market's, as dates), each company's
    move beyond its home index on each, and each report on the session its
    own market traded it."""
    out = []
    day = as_of
    for _ in range(REPLAY_SEASONS):
        start, end, label = C.season_window(day)
        last = min(end, as_of)
        lo, hi = pd.Timestamp(start), pd.Timestamp(last)
        dates = sorted({d for s in series.values() for d in s.excess.index if lo <= d <= hi})
        moves = {}
        for key, s in series.items():
            window = s.excess.loc[lo:hi].reindex(dates)
            moves[key] = [None if pd.isna(v) else round(float(v), 2) for v in window]
        reported = []
        for key, reps in reports.items():
            s = series.get(key)
            for r in reps:
                if r.own_at is None or s is None:
                    continue
                session = s.excess.index[r.own_at]
                if lo <= session <= hi:
                    reported.append({"key": key, "day": session.strftime("%Y-%m-%d"),
                                     "surprise": None if r.surprise is None else round(r.surprise, 2),
                                     "move": None if r.own_move is None else round(r.own_move, 2)})
        out.append({"label": label, "start": start.isoformat(), "end": end.isoformat(), "through": last.isoformat(),
                    "dates": [d.strftime("%Y-%m-%d") for d in dates], "moves": moves,
                    "reports": sorted(reported, key=lambda r: (r["day"], r["key"]))})
        day = start - timedelta(days=1)
    return out


def _season(nodes: dict, reports: dict, series: dict, rows: list[dict], cats: dict, as_of: date,
            fetched: dict, catalysts: dict | None) -> dict:
    """This season so far: who has reported, how it landed, and how much each
    linked company has already moved on those reports."""
    start, end, label = C.season_window(as_of)
    lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(as_of + timedelta(days=1), tz="UTC")
    reported = {}
    for key, reps in reports.items():
        inside = [r for r in reps if lo <= r.info < hi]
        if inside:
            r = inside[-1]
            reported[key] = {"date": r.info.date().isoformat(), "surprise": None if r.surprise is None else round(r.surprise, 2),
                             "move": None if r.own_move is None else round(r.own_move, 2), "source": r.source}
    by_follow: dict[str, list[dict]] = {}
    for r in rows:
        if r["category"] == "unlinked" or not lo <= r["lead_info"] < hi:
            continue
        by_follow.setdefault(r["follow"], []).append(r)
    out_nodes = {}
    for key in nodes:
        mine = reported.get(key)
        heard = by_follow.get(key) or []
        # Before its own report: the moves it has already made on its links' reports.
        own_info = pd.Timestamp(mine["date"], tz="UTC") if mine else None
        before = [r for r in heard if own_info is None or r["lead_info"] < own_info]
        seen, read_in = set(), 0.0
        for r in before:
            if r["follow_day"] not in seen:
                seen.add(r["follow_day"])
                read_in += r["follow_move"]
        out_nodes[key] = {
            "reported": mine,
            "read_in": round(read_in, 2) if before else None,
            "heard": [{"lead": r["lead"], "category": r["category"], "day": r["follow_day"], "move": round(r["follow_move"], 2),
                       "lead_move": round(r["lead_move"], 2), "lead_surprise": None if r["lead_surprise"] is None else round(r["lead_surprise"], 2)}
                      for r in sorted(heard, key=lambda r: r["lead_info"])],
        }
    summary = {"label": label, "start": start.isoformat(), "end": end.isoformat(),
               "reported": len(reported), "companies": len(nodes),
               "beat": sum(1 for v in reported.values() if (v["surprise"] or 0) > 0),
               "missed": sum(1 for v in reported.values() if v["surprise"] is not None and v["surprise"] < 0)}
    return {"summary": summary, "nodes": out_nodes}
