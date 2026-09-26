"""The ticker page's evidence and options layer: listed, never scored.

- Earnings reactions: each 8-K with Item 2.02 (results of operations) is an
  earnings release; its EDGAR acceptance time says whether it came before
  the open, during the session or after the close, and so which close-to-close
  move is the reaction.
- Implied move: the ATM straddle, as a share of spot, of the first expiry on
  or after the reaction session, from the options snapshot. It prices the
  whole period to expiry, not the report alone, and is labelled so.
- Insiders: open-market purchases (Form 4 code P) and sales (S). A cluster is
  two or more different insiders buying within 30 days.
- Short interest and rating changes as their sources report them.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NEW_YORK = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)
CONSTANT_MATURITY_DAYS = 30


# --- earnings ----------------------------------------------------------------------

def earnings_announcements(recent: dict, *, since: date | None = None) -> list[dict]:
    """Earnings releases from a submissions index's recent block, newest first."""
    forms = recent.get("form") or []
    items = recent.get("items") or [""] * len(forms)
    accepted = recent.get("acceptanceDateTime") or [None] * len(forms)
    out, seen = [], set()
    for form, item, stamp in zip(forms, items, accepted):
        if form != "8-K" or "2.02" not in str(item or "") or not stamp:
            continue
        moment = pd.Timestamp(stamp)
        moment = (moment.tz_localize("UTC") if moment.tzinfo is None else moment).tz_convert(NEW_YORK)
        day = moment.date()
        if day in seen or (since and day < since):
            continue
        seen.add(day)
        clock = moment.time()
        timing = "bmo" if clock < OPEN else "amc" if clock >= CLOSE else "intraday"
        out.append({"date": day.isoformat(), "time": clock.strftime("%H:%M"), "timing": timing})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def reaction(closes: pd.Series, day: date, timing: str) -> dict | None:
    """Close-to-close move over the session that first traded on the news."""
    s = closes.dropna()
    if s.empty:
        return None
    when = pd.Timestamp(day)
    if timing == "amc":
        base = s[s.index <= when]
        react = s[s.index > when]
    else:
        base = s[s.index < when]
        react = s[s.index >= when]
    if base.empty or react.empty:
        return None
    b, r = base.index[-1], react.index[0]
    if (r - b).days > 5:  # a gap in the prices, not a session
        return None
    return {"base": b.strftime("%Y-%m-%d"), "session": r.strftime("%Y-%m-%d"),
            "move_pct": float(100 * (s[r] / s[b] - 1))}


def reactions(closes: pd.Series, index_close: pd.Series, announcements: list[dict], count: int = 8) -> list[dict]:
    out = []
    for a in announcements:
        r = reaction(closes, date.fromisoformat(a["date"]), a["timing"])
        if r is None:
            continue
        idx = index_close.dropna()
        index_move = None
        if pd.Timestamp(r["base"]) in idx.index and pd.Timestamp(r["session"]) in idx.index:
            index_move = float(100 * (idx[pd.Timestamp(r["session"])] / idx[pd.Timestamp(r["base"])] - 1))
        out.append({**a, **{k: r[k] for k in ("session", "move_pct")},
                    "index_pct": None if index_move is None else round(index_move, 2),
                    "excess_pct": None if index_move is None else round(r["move_pct"] - index_move, 2)})
        out[-1]["move_pct"] = round(out[-1]["move_pct"], 2)
        if len(out) >= count:
            break
    return out


def implied_move(summary: pd.DataFrame, reaction_session: date) -> dict | None:
    """The ATM straddle of the first expiry on or after the reaction session."""
    if summary is None or summary.empty:
        return None
    rows = summary.copy()
    rows["expiry_date"] = pd.to_datetime(rows["expiry"], errors="coerce")
    rows = rows[(rows["expiry_date"] >= pd.Timestamp(reaction_session)) & rows["straddle_pct"].notna()]
    if rows.empty:
        return None
    first = rows.sort_values("expiry_date").iloc[0]
    return {"expiry": first["expiry_date"].strftime("%Y-%m-%d"), "days": int(first["days"]),
            "straddle_pct": round(float(first["straddle_pct"]), 2),  # already a percent of spot
            "atm_iv": None if pd.isna(first.get("atm_iv")) else round(float(first["atm_iv"]), 4)}


def constant_maturity_iv(rows: pd.DataFrame, days: int = CONSTANT_MATURITY_DAYS) -> float | None:
    """ATM IV at ``days``, linear in total variance between the bracketing expiries."""
    clean = rows.dropna(subset=["atm_iv", "days"])
    clean = clean[clean["days"] > 0].sort_values("days")
    if clean.empty:
        return None
    below = clean[clean["days"] <= days]
    above = clean[clean["days"] >= days]
    if below.empty or above.empty:
        return None
    lo, hi = below.iloc[-1], above.iloc[0]
    if lo["days"] == hi["days"]:
        return float(lo["atm_iv"])
    var_lo, var_hi = lo["atm_iv"] ** 2 * lo["days"], hi["atm_iv"] ** 2 * hi["days"]
    weight = (days - lo["days"]) / (hi["days"] - lo["days"])
    variance = var_lo + weight * (var_hi - var_lo)
    return float(np.sqrt(variance / days)) if variance > 0 else None


# --- insiders ----------------------------------------------------------------------

def _text(node, path: str) -> str | None:
    found = node.find(path)
    if found is None:
        return None
    value = found.find("value")
    raw = (value.text if value is not None else found.text) or ""
    return raw.strip() or None


def parse_form4(xml: str) -> list[dict]:
    """Non-derivative transactions of one Form 4, one row each."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    owners = []
    for owner in root.findall("reportingOwner"):
        rel = owner.find("reportingOwnerRelationship")
        title = _text(rel, "officerTitle") if rel is not None else None
        role = "director" if rel is not None and _text(rel, "isDirector") in ("1", "true") else None
        if rel is not None and _text(rel, "isOfficer") in ("1", "true"):
            role = title or "officer"
        if rel is not None and _text(rel, "isTenPercentOwner") in ("1", "true"):
            role = role or "10% owner"
        owners.append({"name": _text(owner, "reportingOwnerId/rptOwnerName"), "role": role})
    name = "; ".join(o["name"] for o in owners if o["name"]) or None
    role = next((o["role"] for o in owners if o["role"]), None)
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        try:
            shares = float(_text(tx, "transactionAmounts/transactionShares") or "nan")
            price = float(_text(tx, "transactionAmounts/transactionPricePerShare") or "nan")
        except ValueError:
            continue
        out.append({
            "date": _text(tx, "transactionDate"), "owner": name, "role": role, "code": code,
            "shares": None if np.isnan(shares) else shares, "price": None if np.isnan(price) else price,
            "value": None if np.isnan(shares) or np.isnan(price) else round(shares * price, 2),
        })
    return out


def insider_summary(transactions: list[dict], as_of: date, *, window_days: int = 90,
                    cluster_days: int = 30, min_insiders: int = 2, min_value: float = 0.0) -> dict:
    recent = [t for t in transactions if t.get("date") and date.fromisoformat(t["date"][:10]) >= as_of - timedelta(days=window_days)]
    buys = sorted((t for t in recent if t["code"] == "P"), key=lambda t: t["date"])
    sells = [t for t in recent if t["code"] == "S"]
    cluster = None
    for i, first in enumerate(buys):
        start = date.fromisoformat(first["date"][:10])
        group = [t for t in buys[i:] if date.fromisoformat(t["date"][:10]) <= start + timedelta(days=cluster_days)]
        owners = {t["owner"] for t in group if t["owner"]}
        if len(owners) >= min_insiders and sum(t["value"] or 0 for t in group) >= min_value:
            cluster = {"insiders": sorted(owners), "count": len(owners), "from": group[0]["date"][:10],
                       "to": group[-1]["date"][:10], "value": round(sum(t["value"] or 0 for t in group), 0)}
    return {
        "window_days": window_days,
        "buys": [{k: t[k] for k in ("date", "owner", "role", "shares", "price", "value")} for t in buys][-10:],
        "buy_value": round(sum(t["value"] or 0 for t in buys), 0),
        "sell_value": round(sum(t["value"] or 0 for t in sells), 0),
        "sellers": len({t["owner"] for t in sells if t["owner"]}),
        "cluster": cluster,
    }


# --- short interest and ratings -------------------------------------------------------

def short_summary(rows: list[dict]) -> dict | None:
    """Latest report, change over about a month (two reports back), history."""
    ordered = sorted(rows, key=lambda r: r["date"])
    if not ordered:
        return None
    last = ordered[-1]
    month = ordered[-3] if len(ordered) >= 3 else None
    change = None if not month or not month["interest"] else round(100 * (last["interest"] / month["interest"] - 1), 1)
    return {"date": last["date"], "interest": last["interest"], "days_to_cover": last["days_to_cover"],
            "change_1m_pct": change,
            "history": [{"date": r["date"], "interest": r["interest"], "days_to_cover": r["days_to_cover"]} for r in ordered[-24:]]}


def ratings_summary(changes: list[dict], as_of: date, *, window_days: int = 90) -> dict:
    recent = [c for c in changes if c.get("date") and date.fromisoformat(c["date"][:10]) >= as_of - timedelta(days=window_days)]
    recent.sort(key=lambda c: c["date"], reverse=True)
    action = lambda c: str(c.get("Action") or "").lower()
    raised = [c for c in recent if (c.get("currentPriceTarget") or 0) > (c.get("priorPriceTarget") or 0) > 0]
    cut = [c for c in recent if 0 < (c.get("currentPriceTarget") or 0) < (c.get("priorPriceTarget") or 0)]
    return {
        "window_days": window_days,
        "upgrades": sum(action(c) == "up" for c in recent),
        "downgrades": sum(action(c) == "down" for c in recent),
        "initiations": sum(action(c) == "init" for c in recent),
        "target_raises": len(raised),
        "target_cuts": len(cut),
        "recent": [{"date": c["date"][:10], "firm": c.get("Firm"), "action": action(c), "from": c.get("FromGrade") or None,
                    "to": c.get("ToGrade") or None, "target": c.get("currentPriceTarget") or None,
                    "prior_target": c.get("priorPriceTarget") or None} for c in recent[:12]],
    }


def evidence_lines(insiders: dict | None, short: dict | None, ratings: dict | None, settings: dict) -> tuple[list[str], list[str]]:
    """The phase-3 facts as for / against lines, by rules in [evidence]."""
    for_, against = [], []
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"
    if insiders and insiders.get("cluster"):
        c = insiders["cluster"]
        for_.append(f"Insider cluster buy: {c['count']} insiders bought ${c['value'] / 1e6:,.1f}m on the open market, {c['from']} → {c['to']}")
    elif insiders:
        large = [b for b in insiders.get("buys") or [] if (b.get("value") or 0) >= float(settings.get("single_buy_min_value", 1_000_000))]
        if large:
            biggest = max(large, key=lambda b: b["value"])
            for_.append(f"Open-market insider buy: {biggest['owner']} ({biggest.get('role') or 'insider'}) ${biggest['value'] / 1e6:,.1f}m on {biggest['date'][:10]}")
    if short and short.get("change_1m_pct") is not None:
        move = short["change_1m_pct"]
        threshold = float(settings.get("short_change_pct", 20))
        if move >= threshold:
            against.append(f"Short interest up {move:.0f}% in a month ({short['days_to_cover']:.1f} days to cover, {short['date']})")
        elif move <= -threshold:
            for_.append(f"Short interest down {abs(move):.0f}% in a month ({short['date']})")
    if ratings:
        net = ratings["upgrades"] - ratings["downgrades"]
        if net > 0:
            for_.append(f"Ratings: {plural(ratings['upgrades'], 'upgrade')} vs {plural(ratings['downgrades'], 'downgrade')} in {ratings['window_days']} days")
        elif net < 0:
            against.append(f"Ratings: {plural(ratings['downgrades'], 'downgrade')} vs {plural(ratings['upgrades'], 'upgrade')} in {ratings['window_days']} days")
    return for_, against
