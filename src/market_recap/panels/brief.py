"""BRIEF: the five-minute read, assembled from this session's other panels.

Nothing is fetched or computed afresh. Each line comes from the panel that
owns it -- RISK, PRICED PATH, CATALYSTS, MONITOR, the anchor and the decision
log -- and links to it. A panel that did not build for this session leaves
its line saying so; BRIEF never shows another session's numbers.
"""

from __future__ import annotations

from datetime import date, timedelta

# Panels BRIEF reads, all required to be from this session.
INPUTS = ("risk", "priced", "catalysts", "monitor", "anchor", "journal")
POST_EARNINGS_MOVE_PCT = 5.0
TIERS = {"high": 0, "medium": 1, "low": 2}


def _risk_strip(risk: dict | None, keys: list[str]) -> list[dict]:
    if not risk:
        return []
    tiles = {t["key"]: {**t, "section": s["key"], "horizon": s["horizon"]} for s in risk["sections"] for t in s["tiles"]}
    keep = ("key", "label", "unit", "value", "date", "pct_1y", "pct_long", "change_1w", "breach", "crossed",
            "risk_when", "threshold", "spark", "section", "horizon", "frequency", "error")
    return [{k: tiles[key].get(k) for k in keep} for key in keys if key in tiles]


def _priced_strip(priced: dict | None, risk: dict | None) -> dict | None:
    if not priced or not priced.get("meetings"):
        return None
    next_meeting = priced["meetings"][0]
    trace = [t for t in priced.get("next_meeting_trace") or [] if t["meeting"] == next_meeting["date"]]
    day_change = round(trace[-1]["change_bp"] - trace[-2]["change_bp"], 1) if len(trace) >= 2 else None
    year = next_meeting["date"][:4]
    by_year_end = [m for m in priced["meetings"] if m["date"][:4] == year][-1]
    cpi = next((r for r in priced.get("releases") or [] if r["key"] in ("cpi_yoy", "core_cpi_yoy")), None)
    tiles = {t["key"]: t for s in (risk or {}).get("sections", []) for t in s["tiles"]}
    return {
        "next_meeting": {
            "date": next_meeting["date"], "change_bp": next_meeting["change_bp"], "step": next_meeting["step"],
            "change_1d_bp": day_change, "change_1w_bp": next_meeting.get("change_1w_bp"),
            "kalshi_p_hike": (next_meeting.get("kalshi") or {}).get("p_hike"),
            "polymarket_p_hike": (next_meeting.get("polymarket") or {}).get("value"),
        },
        "by_year_end": {"date": by_year_end["date"], "cumulative_bp": by_year_end["cumulative_bp"]},
        "cpi": cpi,
        "implied_vs_realised": {
            "vix": (tiles.get("vix") or {}).get("value"),
            "realised": (tiles.get("rv20") or {}).get("value"),
        },
    }


def _changed(risk: dict | None, monitor: dict | None, as_of: str) -> dict:
    out = {"risk": [], "monitor": [], "earnings": []}
    if risk:
        out["risk"] = [{"key": c["key"], "label": c["label"], "value": c["value"], "unit": c["unit"],
                        "crossed": c["crossed"], "horizon": c["horizon"]} for c in risk.get("crossed") or []]
    if monitor:
        out["monitor"] = [{"ticker": c["ticker"], "sector": c.get("sector"), "kind": c["kind"], "text": c.get("text")}
                          for c in monitor.get("changes") or [] if c.get("kind") in ("entered", "left")]
        previous = monitor.get("previous_as_of")
        for row in monitor.get("rows") or []:
            reported = row.get("reported") or {}
            move = reported.get("return_1d")
            if not reported.get("date") or move is None:
                continue
            if previous and reported["date"] <= previous:
                continue
            if abs(move) >= POST_EARNINGS_MOVE_PCT:
                out["earnings"].append({"ticker": row["ticker"], "name": row.get("name"), "date": reported["date"],
                                        "return_1d": move, "surprise_pct": reported.get("surprise_pct")})
        out["earnings"].sort(key=lambda r: -abs(r["return_1d"]))
    return out


def _sessions_after(as_of: str, count: int) -> list[str]:
    day = date.fromisoformat(as_of)
    out = []
    while len(out) < count:
        day += timedelta(days=1)
        if day.weekday() < 5:
            out.append(day.isoformat())
    return out


def _next_72h(catalysts: dict | None, watch: set[str], top: set[str], as_of: str) -> list[dict]:
    if not catalysts:
        return []
    window = set(_sessions_after(as_of, 3))
    items = []
    for event in catalysts.get("events") or []:
        if event.get("date") not in window:
            continue
        if event.get("lane") == "macro":
            # Medium-importance central-bank items are mostly speeches; the
            # decision itself is high. Five speeches would bury a CPI print.
            importance = event.get("importance")
            if importance not in ("high", "medium") or (importance == "medium" and event.get("event_type") == "central_bank"):
                continue
            market = next((x for x in event.get("expectations") or [] if x.get("kind") == "market"), None)
            items.append({"kind": "macro", "date": event["date"], "time": event.get("time"), "title": event.get("title"),
                          "importance": event.get("importance"), "market": market})
        else:
            symbol = event.get("symbol")
            if not symbol or (symbol not in watch and symbol not in top and not event.get("watchlist")):
                continue
            items.append({"kind": "earnings", "date": event["date"], "time": event.get("timing") or event.get("time"),
                          "symbol": symbol, "title": event.get("name") or event.get("title"),
                          "watchlist": bool(event.get("watchlist")) or symbol in watch,
                          "weight": (event.get("index_weights") or {}).get("SPX"),
                          "eps_forecast": event.get("eps_forecast")})
    items.sort(key=lambda i: (i["date"], i["kind"] != "macro", TIERS.get(i.get("importance") or "low", 3)))
    return items


def _my_list(monitor: dict | None, journal: dict | None) -> list[dict]:
    if not monitor:
        return []
    checkpoints = {}
    for entry in (journal or {}).get("open_checkpoints") or []:
        checkpoints.setdefault(entry["ticker"], entry)
    out = []
    for row in monitor.get("rows") or []:
        if row.get("membership") != "watchlist" and row["ticker"] not in checkpoints:
            continue
        out.append({
            "ticker": row["ticker"], "name": row.get("name"), "membership": row.get("membership"),
            "drawdown_pct": row.get("drawdown_pct"), "peer_excess_pct": row.get("peer_excess_pct"),
            "price_state": row.get("price_state"), "evidence_state": row.get("evidence_state"),
            "candidate": row.get("candidate"), "earnings_date": row.get("earnings_date"),
            "checkpoint": checkpoints.get(row["ticker"]),
        })
    out.sort(key=lambda r: (r["checkpoint"] is None, r["ticker"]))
    return out


def build(ctx, *, inputs: dict[str, dict | None]) -> dict:
    settings = ctx.config.get("brief", {})
    risk, priced, catalysts = inputs.get("risk"), inputs.get("priced"), inputs.get("catalysts")
    monitor, anchor, journal = inputs.get("monitor"), inputs.get("anchor"), inputs.get("journal")
    watch = {row["ticker"] for row in (monitor or {}).get("rows") or [] if row.get("membership") == "watchlist"}
    holdings = ctx.holdings
    top = set(holdings.sort_values("weight", ascending=False)["yahoo_symbol"].head(int(settings.get("top_weights", 20)))) \
        if not holdings.empty else set()
    return {
        "as_of": ctx.as_of,
        "missing": sorted(name for name in INPUTS if inputs.get(name) is None),
        "anchor": None if not anchor else {k: anchor[k] for k in ("rule", "held", "next", "components", "changes")} | {
            "history": {k: anchor["history"][k][-252:] for k in ("dates", "exposure", "spy")}},
        "risk": {
            "tactical": _risk_strip(risk, list(settings.get("tactical", []))),
            "slow": _risk_strip(risk, list(settings.get("slow", []))),
            "breaches": len((risk or {}).get("breaches") or []),
        },
        "priced": _priced_strip(priced, risk),
        "changed": _changed(risk, monitor, ctx.as_of),
        "next_72h": _next_72h(catalysts, watch, top, ctx.as_of),
        "my_list": _my_list(monitor, journal),
    }
