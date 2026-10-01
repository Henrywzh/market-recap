"""The ticker page's evidence and options layer: listed, never scored.

- Earnings reactions: each 8-K with Item 2.02 (results of operations) is an
  earnings release; its EDGAR acceptance time says whether it came before
  the open, during the session or after the close, and so which close-to-close
  move is the reaction.
- Implied move: the ATM straddle, as a share of spot, of the first expiry on
  or after the reaction session, from the options snapshot. It prices the
  whole period to expiry, not the report alone, and is labelled so.
- Insiders: Form 4 code P includes open-market *or private* purchases. The
  stricter direct-purchase cluster is computed separately from the broad
  30-calendar-day descriptive summary.
- Short interest and rating changes as their sources report them.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from bisect import bisect_left
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NEW_YORK = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)
CONSTANT_MATURITY_DAYS = 30


# --- earnings ----------------------------------------------------------------------

# SEC serves a filing accepted in the last day with its Eastern wall-clock
# time marked "Z" -- Micron's 16:02 release of 2026-09-30 read
# "16:02:22.000Z" that evening, its 16:02 release in June reads "20:02:01Z"
# -- and corrects it later. Read as UTC, an after-close report became 12:02
# "intraday" and was given a same-day move of 0.0%. A stamp this recent is
# read as Eastern: if SEC has already corrected it, an after-close report is
# still after the close, and before-open and intraday trade the same session.
FRESH_STAMP_DAYS = 1


def _accepted(stamp: str, fresh_after: date | None):
    moment = pd.Timestamp(stamp)
    if fresh_after is not None and moment.date() >= fresh_after:
        return moment.tz_localize(None).tz_localize(NEW_YORK)
    return (moment.tz_localize("UTC") if moment.tzinfo is None else moment).tz_convert(NEW_YORK)


def earnings_announcements(recent: dict, *, since: date | None = None, today: date | None = None) -> list[dict]:
    """Earnings releases from a submissions index's recent block, newest first."""
    forms = recent.get("form") or []
    items = recent.get("items") or [""] * len(forms)
    accepted = recent.get("acceptanceDateTime") or [None] * len(forms)
    fresh_after = today - timedelta(days=FRESH_STAMP_DAYS) if today else None
    out, seen = [], set()
    for form, item, stamp in zip(forms, items, accepted):
        if form != "8-K" or "2.02" not in str(item or "") or not stamp:
            continue
        moment = _accepted(stamp, fresh_after)
        day = moment.date()
        if day in seen or (since and day < since):
            continue
        seen.add(day)
        clock = moment.time()
        timing = "bmo" if clock < OPEN else "amc" if clock >= CLOSE else "intraday"
        out.append({"date": day.isoformat(), "time": clock.strftime("%H:%M"), "timing": timing})
    return sorted(out, key=lambda r: r["date"], reverse=True)


def six_k_announcements(recent: dict, pattern: str, timing: str) -> list[dict]:
    """Earnings releases of a foreign private issuer, newest first.

    A 6-K carries no item code, so the release is recognised by the name its
    filer gives the document (TSMC ``tsm-YYYYMMDDx6k.htm``, ASML
    ``...quarterlyfilings.htm``). Both release overnight New York time, so
    the timing is configured rather than read from the acceptance clock.
    """
    import re as _re
    rule = _re.compile(pattern)
    forms = recent.get("form") or []
    docs = recent.get("primaryDocument") or [""] * len(forms)
    filed = recent.get("filingDate") or [None] * len(forms)
    out, seen = [], set()
    for form, doc, day in zip(forms, docs, filed):
        if form != "6-K" or not day or day in seen or not rule.search(doc or ""):
            continue
        seen.add(day)
        out.append({"date": day, "time": None, "timing": timing})
    return out


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


def strict_form4_buys(xml: str, *, issuer_cik: int, filed: str, filing_url: str | None = None) -> list[dict]:
    """Research-grade subset of P purchases; exclude plans and indirect holdings.

    Code P alone means open-market *or private* purchase. These extra fields
    follow quantamental-lab's primary transaction contract; an absent field
    fails closed rather than silently becoming a direct discretionary buy.
    """
    try:
        root = ET.fromstring(xml)
        actual_cik = int(_text(root, "issuer/issuerCik") or "0")
    except (ET.ParseError, ValueError):
        return []
    if actual_cik != issuer_cik or _text(root, "documentType") != "4":
        return []
    if (_text(root, "aff10b5One") or "").lower() not in ("0", "false", "no"):
        return []
    owners = root.findall("reportingOwner")
    if len(owners) != 1:
        return []  # Joint/chain ownership cannot count as distinct buyers.
    owner = owners[0]
    owner_id = _text(owner, "reportingOwnerId/rptOwnerCik")
    if not owner_id:
        return []
    name = _text(owner, "reportingOwnerId/rptOwnerName")
    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        coding = _text(tx, "transactionCoding/transactionCode")
        acquire = _text(tx, "transactionAmounts/transactionAcquiredDisposedCode")
        direct = _text(tx, "ownershipNature/directOrIndirectOwnership")
        swap = (_text(tx, "transactionCoding/equitySwapInvolved") or "").lower()
        if coding != "P" or acquire != "A" or direct != "D" or swap not in ("0", "false", "no"):
            continue
        # Many filers write an empty <deemedExecutionDate/>; only a dated one
        # marks a trade executed under a plan or order placed earlier.
        if _text(tx, "deemedExecutionDate") or (_text(tx, "transactionCoding/aff10b5One") or "").lower() in ("1", "true", "yes"):
            continue
        try:
            shares = float(_text(tx, "transactionAmounts/transactionShares") or "nan")
            price = float(_text(tx, "transactionAmounts/transactionPricePerShare") or "nan")
        except ValueError:
            continue
        if not np.isfinite(shares) or not np.isfinite(price) or shares <= 0 or price <= 0:
            continue
        when = _text(tx, "transactionDate")
        if not when:
            continue
        out.append({"date": when[:10], "filed": filed[:10], "owner_id": owner_id, "owner": name,
                    "value": round(shares * price, 2), "filing_url": filing_url})
    return out


def strict_buy_cluster(transactions: list[dict], sessions: pd.DatetimeIndex, *, max_sessions: int = 5,
                       min_value: float = 250_000) -> dict | None:
    """Latest non-overstated cluster: >=2 owner CIKs within five SPX sessions."""
    if not transactions or sessions.empty:
        return None
    dates = sorted(pd.Timestamp(d).normalize() for d in sessions)
    eligible = sorted((t for t in transactions if t.get("date") and t.get("owner_id") and t.get("filed")),
                      key=lambda t: t["date"])
    candidates = []
    for first in eligible:
        start = bisect_left(dates, pd.Timestamp(first["date"]))
        if start >= len(dates):
            continue
        end = dates[min(start + max_sessions - 1, len(dates) - 1)]
        group = [t for t in eligible if first["date"] <= t["date"] <= end.strftime("%Y-%m-%d")]
        owners = {t["owner_id"] for t in group}
        value = sum(t["value"] for t in group)
        if len(owners) >= 2 and value >= min_value:
            candidates.append({"from": first["date"], "to": group[-1]["date"],
                               "available": max(t["filed"] for t in group), "count": len(owners),
                               "transactions": len(group), "value": round(value, 0),
                               "owners": sorted({t["owner"] for t in group if t.get("owner")}),
                               "filing_urls": sorted({t["filing_url"] for t in group if t.get("filing_url")})})
    return max(candidates, key=lambda c: (c["available"], c["to"], c["value"])) if candidates else None


def insider_summary(transactions: list[dict], as_of: date, *, window_days: int = 90,
                    cluster_days: int = 30, min_insiders: int = 2, min_value: float = 0.0) -> dict:
    recent = [t for t in transactions if t.get("date")
              and as_of - timedelta(days=window_days) <= date.fromisoformat(t["date"][:10]) <= as_of]
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
    recent = [c for c in changes if c.get("date")
              and as_of - timedelta(days=window_days) <= date.fromisoformat(c["date"][:10]) <= as_of]
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
    if insiders and insiders.get("strict_cluster"):
        c = insiders["strict_cluster"]
        coverage = insiders.get("form4_coverage") or {}
        suffix = " (partial filing coverage)" if not coverage.get("complete") else ""
        for_.append(f"Direct Form 4 P purchase cluster: {c['count']} owners, ${c['value'] / 1e6:,.1f}m, "
                    f"{c['from']} → {c['to']}; observable by {c['available']}{suffix}")
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
