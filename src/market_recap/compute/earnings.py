"""Bottom-up S&P 500 earnings: estimate revisions and the reporting season.

"Bottom-up" as FactSet uses it: each company's consensus EPS times its
float-adjusted share count, added up. Float shares are proportional to the
index weight over the price, so the SPY weight file gives them without a
second source. Only ratios are reported (a revision in percent, a surprise
in percent); the scale cancels.

Fiscal periods are assigned to the calendar period holding most of their
months, without pro-rating: a fiscal year ending in June 2027 counts toward
CY2026, one ending in January 2027 likewise. A fiscal quarter counts toward
the calendar quarter it ends in.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any, Iterable

WINDOWS = {"7d": "eps_7d", "30d": "eps_30d", "60d": "eps_60d", "90d": "eps_90d"}
# A company whose estimate moved less than this is counted as unchanged in
# the breadth figures: rounding in the vendor's averages is not a revision.
FLAT_PCT = 0.1
# The season shown is the calendar quarter containing this many days ago:
# off-cycle reporters (quarters ending in July or August) start a season
# before its calendar quarter ends, and the main season runs to mid-November.
SEASON_LAG_DAYS = 75
MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def calendar_year(fiscal_end: Any) -> int | None:
    end = _date(fiscal_end)
    if end is None:
        return None
    return end.year if end.month >= 7 else end.year - 1


def calendar_quarter(period_end: Any) -> tuple[int, int] | None:
    end = _date(period_end)
    return (end.year, (end.month - 1) // 3 + 1) if end else None


def quarter_label(quarter: tuple[int, int]) -> str:
    return f"Q{quarter[1]} {quarter[0]}"


def season_quarter(as_of: date) -> tuple[int, int]:
    return calendar_quarter(as_of - timedelta(days=SEASON_LAG_DAYS))  # type: ignore[return-value]


def nasdaq_quarter(fiscal_quarter: Any) -> tuple[int, int] | None:
    """'Aug/2026' -> (2026, 3)."""
    try:
        month, year = str(fiscal_quarter).split("/")
        return int(year), (MONTHS[month[:3].title()] - 1) // 3 + 1
    except (KeyError, ValueError):
        return None


def pick_period(trend: dict | None, target: tuple) -> dict | None:
    """The fiscal period in a company's trend that maps to the target:
    ("quarter", year, q) or ("year", year)."""
    if not trend:
        return None
    periods = ("0q", "+1q") if target[0] == "quarter" else ("0y", "+1y")
    for name in periods:
        period = trend.get(name)
        if not period or period.get("eps") is None:
            continue
        mapped = calendar_quarter(period.get("end")) if target[0] == "quarter" else calendar_year(period.get("end"))
        if mapped == (target[1:] if target[0] == "quarter" else target[1]):
            return period
    return None


def _change(now: float, then: float) -> float | None:
    return (now / then - 1.0) * 100.0 if then > 0 else None


def _leader(members: list[dict]) -> dict | None:
    """The member that moved its group's 30-day revision most, and by how many
    percentage points of the group: one REIT's FFO basis change or one
    investment gain can be most of a sector's figure."""
    usable = [r for r in members if r["period"].get("eps_30d") is not None]
    base = sum(r["period"]["eps_30d"] * r["shares"] for r in usable)
    if base <= 0 or not usable:
        return None
    top = max(usable, key=lambda r: abs(r["period"]["eps"] - r["period"]["eps_30d"]) * r["shares"])
    pp = (top["period"]["eps"] - top["period"]["eps_30d"]) * top["shares"] / base * 100.0
    return {"symbol": top["symbol"], "pp": round(pp, 2)} if abs(pp) >= 0.01 else None


def revisions(companies: Iterable[dict], target: tuple) -> dict:
    """How far the aggregate estimate for ``target`` moved over each window.

    ``companies``: dicts with symbol, sector, shares (float, any consistent
    scale) and trend. Each window uses the companies with both values, and
    says how many that is.
    """
    rows = []
    for company in companies:
        period = pick_period(company.get("trend"), target)
        if period is not None and company.get("shares"):
            rows.append({**company, "period": period})

    def window(members: list[dict], key: str) -> dict:
        usable = [r for r in members if r["period"].get(key) is not None]
        now = sum(r["period"]["eps"] * r["shares"] for r in usable)
        then = sum(r["period"][key] * r["shares"] for r in usable)
        return {"pct": round(_change(now, then), 2) if usable and _change(now, then) is not None else None,
                "companies": len(usable)}

    out: dict[str, Any] = {"companies": len(rows), "windows": {w: window(rows, k) for w, k in WINDOWS.items()}}
    sectors: dict[str, list[dict]] = {}
    for row in rows:
        sectors.setdefault(row.get("sector") or "Unclassified", []).append(row)
    out["sectors"] = sorted(
        ({"sector": name, "companies": len(members),
          **{w: window(members, WINDOWS[w])["pct"] for w in ("30d", "90d")},
          "leader_30d": _leader(members)} for name, members in sectors.items()),
        key=lambda item: (item["30d"] is None, -(item["30d"] or 0)),
    )
    moved = [r for r in rows if r["period"].get("eps_30d") is not None]
    up = sum(1 for r in moved if (_change(r["period"]["eps"], r["period"]["eps_30d"]) or 0) > FLAT_PCT
             and r["period"]["eps_30d"] > 0)
    down = sum(1 for r in moved if (_change(r["period"]["eps"], r["period"]["eps_30d"]) or 0) < -FLAT_PCT
               and r["period"]["eps_30d"] > 0)
    out["breadth_30d"] = {"up": up, "down": down, "unchanged": len(moved) - up - down}
    # Which names moved the aggregate: a few large revisions can carry a
    # sector (an investment gain booked in EPS, say), and the reader should
    # see that rather than read it as a broad upgrade.
    base = sum(r["period"]["eps_30d"] * r["shares"] for r in moved)
    if base > 0:
        contributions = sorted(
            ((r["symbol"], (r["period"]["eps"] - r["period"]["eps_30d"]) * r["shares"] / base * 100.0) for r in moved),
            key=lambda item: item[1],
        )
        out["movers_30d"] = {
            "up": [{"symbol": s, "pp": round(c, 3)} for s, c in contributions[::-1][:5] if c > 0],
            "down": [{"symbol": s, "pp": round(c, 3)} for s, c in contributions[:5] if c < 0],
        }
    ends = sorted({r["period"].get("end") for r in rows if r["period"].get("end")})
    out["fiscal_period_ends"] = [ends[0], ends[-1]] if ends else None
    return out


def season(reports: list[dict], universe: dict[str, dict], quarter: tuple[int, int]) -> dict:
    """The reporting season for ``quarter`` so far.

    ``reports``: Nasdaq calendar rows that carry an actual EPS, with the
    year-ago EPS captured before the report where one was. ``universe``:
    symbol -> {sector, shares}. A beat is an actual strictly above the
    consensus shown beside it; equal is in line.
    """
    done: dict[str, dict] = {}
    for report in reports:
        symbol = report.get("symbol")
        if symbol in universe and report.get("eps") is not None and nasdaq_quarter(report.get("fiscal_quarter")) == quarter:
            if symbol not in done or report["date"] > done[symbol]["date"]:
                done[symbol] = report
    rows = list(done.values())
    with_estimate = [r for r in rows if r.get("eps_forecast") is not None]
    beat = [r for r in with_estimate if r["eps"] > r["eps_forecast"]]
    miss = [r for r in with_estimate if r["eps"] < r["eps_forecast"]]

    def aggregate(members: list[dict], numerator: str, denominator: str) -> float | None:
        usable = [r for r in members if r.get(numerator) is not None and r.get(denominator) is not None]
        top = sum(r[numerator] * universe[r["symbol"]]["shares"] for r in usable)
        bottom = sum(r[denominator] * universe[r["symbol"]]["shares"] for r in usable)
        return round(_change(top, bottom), 2) if usable and _change(top, bottom) is not None else None

    growth_rows = [r for r in rows if r.get("year_ago_eps") is not None]
    by_sector: dict[str, list[dict]] = {}
    for row in rows:
        by_sector.setdefault(universe[row["symbol"]].get("sector") or "Unclassified", []).append(row)
    surprises = [r["surprise_pct"] for r in with_estimate if r.get("surprise_pct") is not None]
    return {
        "quarter": quarter_label(quarter),
        "universe": len(universe),
        "reported": len(rows),
        "with_estimate": len(with_estimate),
        "beat": len(beat),
        "miss": len(miss),
        "in_line": len(with_estimate) - len(beat) - len(miss),
        "beat_share": round(len(beat) / len(with_estimate) * 100, 1) if with_estimate else None,
        "median_surprise_pct": round(median(surprises), 2) if surprises else None,
        "aggregate_surprise_pct": aggregate(with_estimate, "eps", "eps_forecast"),
        "growth_yoy_pct": aggregate(growth_rows, "eps", "year_ago_eps"),
        "growth_companies": len(growth_rows),
        "sectors": sorted(
            ({"sector": name, "reported": len(members),
              "beat": sum(1 for r in members if r.get("eps_forecast") is not None and r["eps"] > r["eps_forecast"]),
              "with_estimate": sum(1 for r in members if r.get("eps_forecast") is not None)}
             for name, members in by_sector.items()),
            key=lambda item: -item["reported"],
        ),
        "latest": sorted(rows, key=lambda r: (r["date"], r["symbol"]), reverse=True)[:25],
    }
