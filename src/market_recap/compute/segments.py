"""Revenue and profit by business, product and region, as series a page can draw.

Input is the per-filing extraction of ``sources.segments``. Each figure is taken
from the newest filing that reports it, so a year recast after a reorganisation
shows as recast; years only an older filing reports keep that filing's members.

A breakdown is a set of members that adds up to the company: filers tag
subtotals beside their parts (Apple's "Products" beside iPhone and Mac, NVIDIA's
"Data Center" beside Compute and Networking) and some tag two partitions of the
same revenue (Amazon's product / service sales beside its business lines). So
for each period the finest set of members whose sum meets the reported total
(within RECONCILE_SHARE) is kept, preferring the members the latest period
used. A segment breakdown that does not meet the total (a bank's managed-basis
revenue) is still shown, with the gap as its own line; a product or region
breakdown that does not is not shown at all for that period, since its members
may overlap.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from itertools import combinations

from ..sources.sec import fiscal_year
from ..sources.segments import PROFIT_CONCEPTS, REVENUE_CONCEPTS

VIEWS = ("segment", "product", "geography")
RECONCILE_SHARE = 0.01
# Above this many members the exact search is too slow to run per period.
MAX_SEARCH = 16
ANNUAL_DAYS = (350, 380)
QUARTER_DAYS = (80, 100)
NINE_MONTH_DAYS = (250, 285)
ANNUAL_KEPT = 15
QUARTERS_KEPT = 20


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _within(span: int, bounds: tuple[int, int]) -> bool:
    return bounds[0] <= span <= bounds[1]


def fallback_label(member: str) -> str:
    """``goog_GoogleCloudMember`` -> "Google Cloud", for a member no linkbase labelled."""
    name = member.split("_", 1)[-1]
    if member.startswith("country_"):
        return name
    name = re.sub(r"Member$", "", name)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).strip()


def merge(filings: list[dict]) -> tuple[dict, dict, dict, dict]:
    """(facts, totals, labels, sources) across filings, the newest filing's figure first.

    facts: {(concept, view, member, within, start, end): value}
    totals: {(concept, start, end): value}
    sources: {fact key: "filed accession"} of the filing each fact was taken from
    """
    facts: dict[tuple, float] = {}
    totals: dict[tuple, float] = {}
    labels: dict[str, str] = {}
    sources: dict[tuple, str] = {}
    for filing in sorted(filings, key=lambda f: (f["filed"], f["accession"]), reverse=True):
        source = f"{filing['filed']} {filing['accession']}"
        for concept, view, member, within, start, end, value in filing["facts"]:
            key = (concept, view, member, within, start, end)
            if key not in facts:
                facts[key] = value
                sources[key] = source
        for concept, start, end, value in filing["totals"]:
            totals.setdefault((concept, start, end), value)
        for member, label in filing.get("labels", {}).items():
            labels.setdefault(member, label)
    return facts, totals, labels, sources


def with_fourth_quarters(facts: dict, sources: dict | None = None) -> tuple[dict, set]:
    """Add each fourth quarter a filer reports only as its year less nine months.
    Keys end in (start, end); the rest of the key names the series. Returns the
    facts and the keys so derived; a derived figure takes its year's source."""
    out = dict(facts)
    derived: set[tuple] = set()
    nine = {}
    reported = set()  # (series, end) of each three-month figure
    quarters: dict[tuple, list] = {}  # series -> [(start, end, value)] of its three-month figures
    for key, value in facts.items():
        series, start, end = key[:-2], key[-2], key[-1]
        span = _days(start, end)
        if _within(span, NINE_MONTH_DAYS):
            nine[(series, start)] = (end, value)
        elif _within(span, QUARTER_DAYS):
            reported.add((series, end))
            quarters.setdefault(series, []).append((start, end, value))
    for key, value in facts.items():
        series, start, end = key[:-2], key[-2], key[-1]
        if not _within(_days(start, end), ANNUAL_DAYS) or (series, end) in reported:
            continue
        found = nine.get((series, start))
        if not found:
            # No nine-month figure: the year less its three reported quarters.
            inside = sorted({q[1]: q for q in quarters.get(series, []) if start <= q[0] and q[1] < end}.values(), key=lambda q: q[1])
            if len(inside) == 3:
                found = (inside[-1][1], sum(q[2] for q in inside))
        if not found or not _within(_days(found[0], end), QUARTER_DAYS):
            continue
        quarter = (*series, (date.fromisoformat(found[0]) + timedelta(days=1)).isoformat(), end)
        out[quarter] = value - found[1]
        derived.add(quarter)
        if sources is not None and key in sources:
            sources[quarter] = sources[key]
    return out, derived


def _norm(label: str) -> str:
    """A label's identity across renamed members: "Google Services Segment" is "Google Services"."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(segments?|member|reportable)\b", "", label.lower()))


def _total_for(totals: dict, concept: str, start: str, end: str) -> float | None:
    for name in (concept, *REVENUE_CONCEPTS):
        value = totals.get((name, start, end))
        if value is not None:
            return value
    return None


def partition(values: dict, total: float | None, preferred: set) -> list | None:
    """The finest set of keys whose values sum to ``total``, preferring keys in
    ``preferred``; None when no set of two or more does, or there is no total."""
    if total is None or not total or len(values) < 2:
        return None
    tolerance = abs(total) * RECONCILE_SHARE
    keys = sorted(values)
    if abs(sum(values.values()) - total) <= tolerance:
        return keys
    if len(keys) > MAX_SEARCH:
        return None
    for size in range(len(keys) - 1, 1, -1):
        found = [combo for combo in combinations(keys, size) if abs(sum(values[k] for k in combo) - total) <= tolerance]
        if found:
            return list(max(found, key=lambda combo: (sum(k in preferred for k in combo), combo)))
    return None


def _periods(keys, bounds) -> list[tuple[str, str]]:
    spans = {(start, end) for start, end in keys if _within(_days(start, end), bounds)}
    # One period per end: a 52/53-week filer's quarter can be tagged with two starts.
    by_end: dict[str, tuple[str, str]] = {}
    for start, end in sorted(spans):
        by_end.setdefault(end, (start, end))
    return sorted(by_end.values(), key=lambda p: p[1])


def _quarter_label(end: str, annual: list[tuple[str, str]]) -> str:
    container = next(((s, e) for s, e in annual if s <= end <= e), None)
    if container:
        quarter = min(4, max(1, round(_days(container[0], end) / 91.3)))
        return f"Q{quarter} FY{fiscal_year(container[1])}"
    before = [e for _, e in annual if e < end]
    if before:
        last = before[-1]
        quarter = min(4, max(1, round(_days(last, end) / 91.3)))
        following = (date.fromisoformat(last) + timedelta(days=365)).isoformat()
        return f"Q{quarter} FY{fiscal_year(following)}"
    return end[:7]


def _choose(facts: dict, view: str, concepts) -> str | None:
    counts = {c: sum(1 for k in facts if k[0] == c and k[1] == view) for c in concepts}
    best = max(concepts, key=lambda c: (counts[c], -concepts.index(c)))
    return best if counts[best] else None


def _select(values: dict, total, view: str, preferred: set, segment_parts: dict | None):
    """(chosen keys, values, reconciled) for one period's figures from one filing, or None."""
    standalone = {key: value for key, value in values.items() if key[1] is None}
    chosen = partition(standalone, total, {k for k in preferred if k[1] is None})
    if chosen is not None:
        return chosen, values, True
    if view == "product" and segment_parts:
        # Products reported inside segments: each segment by its products where
        # they add up to it, else the segment itself.
        parts, filled = [], dict(values)
        for segment, revenue in segment_parts.items():
            inner = {key: value for key, value in values.items() if key[1] == segment}
            found = partition(inner, revenue, preferred)
            if found:
                parts += found
            else:
                parts.append((segment, None))
                filled[(segment, None)] = revenue
        if parts and total and abs(sum(filled[k] for k in parts) - total) <= abs(total) * RECONCILE_SHARE:
            return parts, filled, True
    if view == "segment" and len(standalone) >= 2:
        return sorted(standalone), values, False
    return None


def view_series(facts: dict, totals: dict, labels: dict, derived: set, sources: dict, view: str,
                periods: list[tuple[str, str]], segment_revenue: dict | None = None) -> dict | None:
    """One breakdown over ``periods`` (oldest first). Each period is read from
    the newest filing that breaks it down completely: a recast year from the
    filing that recast it, never half from one filing and half from another."""
    concept = _choose(facts, view, REVENUE_CONCEPTS)
    if concept is None:
        return None
    profit_concept = _choose(facts, view, PROFIT_CONCEPTS) if view == "segment" else None
    by_period: dict[tuple, dict] = {}
    for key, value in facts.items():
        c, v, member, within, start, end = key
        if c == concept and v == view:
            by_period.setdefault((start, end), {})[(member, within)] = (value, sources.get(key, ""))
    rows: list[dict] = []
    preferred: set = set()
    for start, end in reversed(periods):  # newest first, so older periods prefer its members
        pool = by_period.get((start, end), {})
        if not pool:
            continue
        total = _total_for(totals, concept, start, end)
        vintages = sorted({src for _, src in pool.values()}, reverse=True)
        picked = None
        for vintage in vintages + [None]:
            values = {k: v for k, (v, src) in pool.items() if vintage is None or src == vintage}
            picked = _select(values, total, view, preferred, (segment_revenue or {}).get((start, end)))
            if picked:
                break
        if not picked:
            continue
        chosen, values, reconciled = picked
        if not preferred:
            preferred = set(chosen)
        profit = {}
        if profit_concept:
            profit = {member: value for (c, v, member, within, s, e), value in facts.items()
                      if c == profit_concept and v == view and within is None and s == start and e == end}
        rows.append({"start": start, "end": end, "revenue": {k: values[k] for k in chosen}, "total": total,
                     "reconciled": reconciled, "profit": profit,
                     "total_profit": totals.get((profit_concept, start, end)) if profit_concept else None,
                     "derived": any((concept, view, k[0], k[1], start, end) in derived for k in chosen)})
    if not rows:
        return None
    rows.reverse()
    if view != "segment":
        # A derived fourth quarter whose members its neighbouring reported quarters
        # do not use (a line renamed in the 10-K, so the year less nine months
        # exists only for a coarser split) is left out rather than drawn in another split.
        reported = [r for r in rows if not r["derived"]]
        kept = []
        for row in rows:
            near = [r for r in reported if abs(_days(r["end"], row["end"])) <= 200]
            allowed = set().union(*(set(r["revenue"]) for r in near)) if near else None
            if row["derived"] and allowed is not None and not set(row["revenue"]) <= allowed:
                continue
            kept.append(row)
        rows = kept

    def label(key):
        return labels.get(key[0]) or fallback_label(key[0])

    # One series per business, however often its member was renamed: members whose
    # labels agree (less "segment") are one line, labelled as the latest filing does.
    # A product is one line across the segments it was reported under ("Google"
    # before 2020, "Google Services" after), unless one period has it under two.
    shared = set()
    for row in rows:
        seen: set = set()
        for key in row["revenue"]:
            name = _norm(label(key))
            if name in seen:
                shared.add(name)
            seen.add(name)
    canonical: dict[tuple, tuple] = {}
    keys: list[tuple] = []
    for row in reversed(rows):  # latest members first, then any only older periods had
        for key in sorted(row["revenue"], key=lambda k: -abs(row["revenue"][k])):
            name = _norm(label(key))
            identity = (name, _norm(label((key[1], None))) if key[1] and name in shared else "")
            if identity not in canonical:
                canonical[identity] = key
                keys.append(key)
            canonical[key] = canonical[identity]
    for row in rows:
        merged: dict = {}
        for key, value in row["revenue"].items():
            merged.setdefault(canonical[key], value)
        row["revenue"] = merged
        row["profit"] = {canonical.get((m, None), (m, None))[0]: v for m, v in row["profit"].items()}
    names = [label(k) for k in keys]
    members = [{"key": f"{m}@{w}" if w else m, "label": n if names.count(n) == 1 or not w else f"{label((w, None))} · {n}"}
               for (m, w), n in zip(keys, names)]
    member_keys = [m["key"] for m in members]
    revenue = {mk: [row["revenue"].get(k) for row in rows] for mk, k in zip(member_keys, keys)}
    profit = {}
    if profit_concept:
        profit = {mk: [row["profit"].get(k[0]) if k[1] is None else None for row in rows] for mk, k in zip(member_keys, keys)}
        profit = {mk: series for mk, series in profit.items() if any(v is not None for v in series)}
    unallocated = []
    for row in rows:
        members_profit = [row["profit"].get(k[0]) for k in row["revenue"]]
        complete = profit_concept and row["total_profit"] is not None and all(v is not None for v in members_profit)
        unallocated.append(row["total_profit"] - sum(members_profit) if complete else None)
    return {
        "concept": concept,
        "profit_concept": profit_concept,
        "members": members,
        "periods": [{"start": r["start"], "end": r["end"], "derived": r["derived"], "reconciled": r["reconciled"]} for r in rows],
        "revenue": revenue,
        "profit": profit,
        "total_revenue": [r["total"] for r in rows],
        "total_profit": [r["total_profit"] for r in rows] if profit_concept else [],
        "unallocated": unallocated if profit_concept else [],
    }


def breakdown(filings: list[dict]) -> dict:
    """{views: {view: {annual, quarterly}}} for one company."""
    facts, totals, labels, sources = merge(filings)
    facts, derived = with_fourth_quarters(facts, sources)
    totals, _ = with_fourth_quarters(totals)
    spans = {(k[4], k[5]) for k in facts}
    annual = _periods(spans, ANNUAL_DAYS)[-ANNUAL_KEPT:]
    quarterly = _periods(spans, QUARTER_DAYS)[-QUARTERS_KEPT:]
    out: dict = {}
    segment_revenue: dict = {}
    for view in VIEWS:
        series = {}
        for kind, periods in (("annual", annual), ("quarterly", quarterly)):
            result = view_series(facts, totals, labels, derived, sources, view, periods,
                                 segment_revenue.get(kind) if view == "product" else None)
            if result is None:
                continue
            label_of = (lambda p: f"FY{fiscal_year(p['end'])}") if kind == "annual" else (lambda p: _quarter_label(p["end"], annual))
            for period in result["periods"]:
                period["label"] = label_of(period)
            series[kind] = result
            if view == "segment":
                segment_revenue[kind] = {
                    (p["start"], p["end"]): {m["key"]: result["revenue"][m["key"]][i] for m in result["members"]
                                             if "@" not in m["key"] and result["revenue"][m["key"]][i] is not None}
                    for i, p in enumerate(result["periods"])}
        if series:
            out[view] = series
    return out
