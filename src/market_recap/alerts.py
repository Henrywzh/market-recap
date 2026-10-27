"""ALERTS: fixed rules over the artifacts this build wrote, announced when they change.

A rule watches one reading (a risk tile, a strip lead, an RSI, oil, the buyback
window, an OpenRouter author's run-rate, the build itself) and places it on a
tier: 0 below every line, 1 past the first, 2 past the second, and so on. The
tier is compared with the previous published session's ledger, so a reading
that stays past its line is announced once, on the day it crossed, and again
when it falls back (CLEARED) -- never every day it sits there. A tier is left
only once the reading is back past its line by the rule's ``reset`` margin, so
a VIX hovering at 20 does not flip in and out each session.

The ledger is carried in ``alerts.json`` and read back from the published site,
the same rule as the agent feed: a rerun of a session compares with the session
before it. Nothing here forecasts; each alert says what crossed which line.
``email.due`` tells the e-mail step whether this session's changes are news:
a rerun that finds the same changes as the build already published is not.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .config import ARTIFACT_DIR, load_config

SCHEMA = "market_recap.alerts.v1"
FILE = "alerts.json"
RISK_TIER = {"calm": 0, "elevated": 1, "stressed": 2}


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


# --- readings ---------------------------------------------------------------
# Each source returns [(subject, label, value, link)] from the artifacts; a
# reading the build did not produce is simply absent, never a zero.

def _tiles(arts: dict) -> dict:
    risk = arts.get("risk") or {}
    return {t["key"]: t for s in risk.get("sections") or [] for t in s.get("tiles") or []}


def _readings(rule: dict, arts: dict) -> list[tuple[str, str, Any, str]]:
    source = rule["source"]
    if source == "tile":
        t = _tiles(arts).get(rule["key"])
        field = rule.get("field", "value")
        return [(rule["key"], t.get("label") or rule["key"], t.get(field), "#risk")] if t and _finite(t.get(field)) else []
    if source == "strip":
        cell = next((c for c in (arts.get("risk") or {}).get("strip") or [] if c.get("key") == rule["key"] or c.get("column") == rule["key"]), None)
        return [(rule["key"], cell.get("label") or rule["key"], cell.get("value"), "#risk")] if cell and _finite(cell.get("value")) else []
    if source == "risk_state":
        risk = arts.get("risk") or {}
        strip = [c for c in risk.get("strip") or [] if c.get("lead")]
        if rule.get("from", "strip") == "strip":
            cells = strip
        else:
            # The matrix's other leads: one already on the strip is announced there, once.
            on_strip = {c["lead"] for c in strip}
            cells = [c for c in (risk.get("matrix") or {}).get("cells") or []
                     if c.get("lead") and c.get("scale") != "valuation" and c["lead"] not in on_strip]
        rows = {r["key"]: r["label"] for r in (risk.get("matrix") or {}).get("rows") or []}
        return [(f"{c.get('row')}:{c.get('column')}", f"{c.get('channel') or rows.get(c.get('row'), c.get('row'))} · {c.get('label')}",
                 c.get("state"), "#risk") for c in cells if c.get("state") in RISK_TIER]
    if source == "rsi6":
        rows = ((arts.get("today") or {}).get("board") or {}).get("rows") or []
        groups = set(rule.get("groups") or ["index", "sector"])
        return [(r["symbol"], r.get("label") or r["symbol"], r.get("rsi6"), f"#technicals/{r['symbol']}")
                for r in rows if r.get("group") in groups and _finite(r.get("rsi6"))]
    if source == "cross_asset":
        row = next((r for r in (arts.get("overview") or {}).get("cross_asset") or [] if r.get("key") == rule["key"]), None)
        field = rule.get("field", "last")
        return [(rule["key"], row.get("label") or rule["key"], row.get(field), "#overview")] if row and _finite(row.get(field)) else []
    if source == "rate":
        row = next((r for r in (arts.get("overview") or {}).get("rates") or [] if r.get("key") == rule["key"]), None)
        field = rule.get("field", "value")
        return [(rule["key"], row.get("label") or rule["key"], row.get(field), "#overview")] if row and _finite(row.get(field)) else []
    if source == "blackout":
        b = (((arts.get("risk") or {}).get("context") or {}).get("liquidity") or {}).get("blackout") or {}
        return [("blackout", "S&P 500 weight in buyback blackout", b.get("now_pct"), "#risk")] if _finite(b.get("now_pct")) else []
    if source == "openrouter_mom":
        return _openrouter(rule, arts)
    if source == "watch":
        items = ((arts.get("today") or {}).get("unusual") or {}).get("watch") or []
        return [(i.get("subject") or i.get("key"), i.get("subject") or "", 1 if (i.get("extra") or {}).get("state") == "triggered" else 0,
                 i.get("link") or "#watch") for i in items]
    if source == "health":
        return _health(arts)
    raise ValueError(f"unknown alert source {source!r}")


def openrouter_change(dates: list[str], daily: list, *, min_days: int = 7) -> float | None:
    """This month so far against last month: the change, in percent, of the mean
    day with a figure. None without ``min_days`` days in each, or a last month at zero."""
    if not dates:
        return None
    this = dates[-1][:7]
    year, month = int(this[:4]), int(this[5:7])
    last = f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"
    now = [v for d, v in zip(dates, daily) if d[:7] == this and _finite(v)]
    before = [v for d, v in zip(dates, daily) if d[:7] == last and _finite(v)]
    if len(now) < min_days or len(before) < min_days or not sum(before):
        return None
    return (sum(now) / len(now)) / (sum(before) / len(before)) * 100 - 100


def _openrouter(rule: dict, arts: dict) -> list[tuple[str, str, Any, str]]:
    router = ((arts.get("themes") or {}).get("semis") or {}).get("openrouter") or {}
    dates, out = router.get("dates") or [], []
    for p in router.get("providers") or []:
        if rule.get("providers") and p.get("slug") not in rule["providers"]:
            continue
        change = openrouter_change(dates, p.get(rule.get("field", "revenue_k")) or [])
        if change is not None:
            out.append((p["slug"], f"OpenRouter {p.get('name') or p['slug']} est. revenue, month so far vs last month", change,
                        "#themes/SEMIS.DATA.AI-USAGE"))
    return out


def _health(arts: dict) -> list[tuple[str, str, Any, str]]:
    """The build itself: panels it could not build, errors it logged, a feed it did not write."""
    manifest = arts.get("manifest") or {}
    skipped = manifest.get("skipped_panels") or []
    errors = manifest.get("errors") or []
    return [
        ("skipped_panels", f"Panels not built: {', '.join(map(str, skipped)) or 'none'}", len(skipped), "#"),
        ("build_errors", f"Build errors logged: {len(errors)}", len(errors), "#"),
        ("agent_feed", "Agent feed written this build", 0 if arts.get("agent-index") else 1, "#"),
    ]


# --- tiers ------------------------------------------------------------------

def tier_of(value, lines: list[float], op: str, *, previous: int = 0, reset: float = 0.0) -> int:
    """How many of ``lines`` the value is past (``op`` above or below). A tier
    already held is kept until the value is back past its line by ``reset``."""
    if not _finite(value):
        return previous
    past = (lambda line, margin=0.0: value >= line - margin) if op == "above" else (lambda line, margin=0.0: value <= line + margin)
    tier = sum(1 for line in lines if past(line))
    if previous > tier and previous <= len(lines) and past(lines[previous - 1], reset):
        return previous
    return tier


def _tier(rule: dict, value, previous: int) -> int:
    if rule["source"] == "risk_state":
        return RISK_TIER.get(value, previous)
    if rule["source"] in ("watch", "health"):
        return 1 if _finite(value) and value > 0 else 0
    lines = rule["lines"]
    if rule.get("op") == "abs":
        # A move either way: the tier of its size, the sign kept in the text.
        return tier_of(abs(value), lines, "above", previous=previous, reset=rule.get("reset", 0.0)) if _finite(value) else previous
    return tier_of(value, lines, rule.get("op", "above"), previous=previous, reset=rule.get("reset", 0.0))


def _fmt(value, unit: str | None) -> str:
    if isinstance(value, str):
        return value
    if not _finite(value):
        return "—"
    digits = 0 if unit in ("bp", "count") else 2 if unit in ("ratio", "corr") else 1
    text = f"{value:,.{digits}f}"
    if unit in ("pct_change", "pct_move"):
        text = ("+" if value > 0 else "") + text + "%"
    elif unit == "pct":
        text += "%"
    elif unit == "bp":
        text += "bp"
    elif unit == "usd":
        text = "$" + text
    return text.replace("-", "−")


def _line_text(rule: dict, tier: int) -> str:
    # A state carries its own word in the value; a watch or the build has no line.
    if rule["source"] in ("risk_state", "watch", "health") or tier <= 0:
        return ""
    line = rule["lines"][tier - 1]
    if rule.get("op") == "abs":
        return f"± {_fmt(abs(line), rule.get('unit')).lstrip('+')}"
    sign = {"above": "≥", "below": "≤"}.get(rule.get("op", "above"), "")
    return f"{sign} {_fmt(line, rule.get('unit'))}"


def evaluate(rules: list[dict], arts: dict, base: dict | None) -> tuple[list[dict], dict]:
    """The events (tier changes against ``base``) and this session's ledger.

    With no base (the first build, or an unreadable previous feed) nothing is
    compared: what is past a line is listed as ACTIVE, once, rather than NEW.
    """
    before = (base or {}).get("entries") or {}
    ledger: dict[str, dict] = {}
    events: list[dict] = []
    for rule in rules:
        for subject, label, value, link in _readings(rule, arts):
            key = f"{rule['id']}:{subject}"
            prev = before.get(key, {}).get("tier", 0)
            tier = _tier(rule, value, prev)
            ledger[key] = {"tier": tier, "value": value if not isinstance(value, float) else round(value, 4)}
            if base is None:
                state = "ACTIVE" if tier > 0 else None
            elif tier > prev:
                state = "NEW"
            elif tier < prev:
                state = "CLEARED" if tier == 0 else "EASED"
            else:
                state = None
            if not state:
                continue
            severity = rule.get("severity", "normal")
            if tier >= rule.get("high_from_tier", 99):
                severity = "high"
            shown_tier = tier if state != "CLEARED" else prev
            events.append({
                "key": key, "rule": rule["id"], "group": rule.get("group", "OTHER"), "state": state, "tier": tier,
                "severity": "normal" if state in ("CLEARED", "EASED") else severity,
                "label": label, "value": _fmt(value, rule.get("unit")),
                "line": _line_text(rule, shown_tier), "link": link, "note": rule.get("note"),
            })
    order = {"NEW": 0, "ACTIVE": 1, "EASED": 2, "CLEARED": 3}
    events.sort(key=lambda e: (e["severity"] != "high", order[e["state"]], e["group"], e["label"]))
    return events, ledger


# --- the file ---------------------------------------------------------------

def _previous(site: str, fetch: Callable[[str], str] | None) -> tuple[dict | None, str | None]:
    from .sources.http import FetchError, get_text
    fetch = fetch or (lambda url: get_text(url, timeout=20.0, retries=1))
    try:
        payload = json.loads(fetch(f"{site.rstrip('/')}/artifacts/{FILE}"))
    except FetchError as exc:
        return None, None if exc.not_found else f"previous alerts unreadable: {exc}"
    except ValueError:
        return None, None
    return (payload if isinstance(payload, dict) and payload.get("schema") == SCHEMA else None), None


def _base(previous: dict | None, as_of: str) -> dict | None:
    """The ledger of the session before this one, never this one's own."""
    if previous is None:
        return None
    ledger = previous.get("ledger") or {}
    if ledger.get("as_of", "") < as_of:
        return ledger
    return previous.get("ledger_base")   # a rerun of the same session


def _signature(events: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted((e["key"], e["state"], e["tier"]) for e in events)).encode()).hexdigest()[:16]


def _read(root: Path, name: str) -> dict | None:
    path = root / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build(*, root: Path | None = None, fetch: Callable[[str], str] | None = None) -> dict:
    root = root or ARTIFACT_DIR
    config = load_config()
    settings = config.get("alerts") or {}
    site = config["monitor"]["published_base_url"]
    arts = {name: _read(root, name) for name in ("manifest", "risk", "today", "overview", "themes", "agent-index")}
    manifest = arts["manifest"] or {}
    as_of = manifest.get("as_of") or date.today().isoformat()
    previous, problem = _previous(site, fetch)
    base = None if problem else _base(previous, as_of)
    events, ledger = evaluate(settings.get("rules") or [], arts, base)
    signature = _signature(events)
    # Already announced: the published file is this session's and found the same changes.
    sent_before = bool(previous) and previous.get("as_of") == as_of and (previous.get("email") or {}).get("signature") == signature
    return {
        "schema": SCHEMA, "as_of": as_of, "edition": manifest.get("edition"), "generated_at": manifest.get("generated_at"),
        "site": site, "compared_with": (base or {}).get("as_of"), "problem": problem,
        "how_to_read": ("Each alert is a fixed rule's reading crossing a line, compared with the previous published session: "
                        "NEW (crossed), EASED (back one line), CLEARED (back below every line), ACTIVE (first build, "
                        "nothing to compare). A reading staying past its line is not repeated. Descriptive, not a forecast."),
        "events": events,
        "active": sorted(k for k, v in ledger.items() if v["tier"] > 0),
        "ledger": {"as_of": as_of, "entries": ledger},
        "ledger_base": base,
        "email": {"due": bool(events) and not sent_before, "signature": signature,
                  "subject": subject_line(as_of, events)},
    }


def subject_line(as_of: str, events: list[dict]) -> str:
    counts = {s: sum(1 for e in events if e["state"] == s) for s in ("NEW", "ACTIVE", "EASED", "CLEARED")}
    high = sum(1 for e in events if e["severity"] == "high")
    parts = [f"{n} {s.lower()}" for s, n in counts.items() if n]
    return f"Market Recap alerts · {as_of} · " + (", ".join(parts) or "no change") + (f" · {high} high" if high else "")


def write(*, root: Path | None = None, fetch: Callable[[str], str] | None = None) -> dict:
    """Build and write alerts.json. Optional: a build that fails leaves no file."""
    root = root or ARTIFACT_DIR
    path = root / FILE
    try:
        payload = build(root=root, fetch=fetch)
    except Exception as exc:  # noqa: BLE001 - alerts are optional; the dashboard is not
        path.unlink(missing_ok=True)
        return {"written": False, "problem": f"{type(exc).__name__}: {str(exc)[:300]}"}
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"written": True, "events": len(payload["events"]), "email_due": payload["email"]["due"],
            "compared_with": payload["compared_with"]}
