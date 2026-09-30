"""THEMES (CATALYSTS -> THEMES): what is coming for each group of names that
trades together, and the industry data behind the first two.

Every group gets a proxy's run-in against the S&P 500, its bellwethers'
next reports (scheduled on the calendar, or projected from their own report
rhythm and marked so) with how far the proxy has moved on their past
reports, and a six-week calendar of those reports, the macro releases that
bear on the group and the dates its own data is due.

Two groups carry industry data (docs/information_architecture.md):

- CLOUD & AI CAPEX: quarterly capex of the five largest cloud spenders from
  their 10-Q/10-K XBRL (compute.capex); monthly revenue of three Taiwanese
  AI-server makers (MOPS); OpenRouter tokens and estimated revenue by model
  author, and Ramp's AI adoption and spend per employee (both read from
  alternative-data's published files).
- SEMICONDUCTORS & MEMORY: TSMC and Nanya monthly revenue (MOPS), Korean IC
  exports (Korea Customs), ADATA's monthly memory note, and UK retail prices
  of memory kits and CPUs read from PCPartPicker's trend charts.

Each source is optional: one that fails leaves its section's reason on the
page and the rest renders.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
import statistics

import pandas as pd

from ..compute import capex as X
from ..compute import events as E
from ..compute import themes as T
from .. import cache
from ..sources import adata, altdata, dart, korea_customs, mops, motie, pcpartpicker, releases, sec, yahoo
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, describe_error, history_payload
from .financials import cik_for

INPUTS = ("catalysts", "evidence")
BN = 1e9


# --- groups -------------------------------------------------------------------

def _next_report(symbol: str, catalysts: dict, reactions: list[dict], as_of: date) -> dict | None:
    for e in catalysts.get("events") or []:
        if e.get("event_type") == "earnings" and e.get("symbol") == symbol and e["date"] > as_of.isoformat():
            return {"date": e["date"], "timing": e.get("timing"), "projected": False}
    past = [date.fromisoformat(r["date"]) for r in reactions if r.get("date")]
    projected = T.project_next(past, as_of)
    return {"date": projected.isoformat(), "timing": None, "projected": True} if projected else None


def _krx_closes(settings: dict) -> pd.DataFrame:
    """Korean closes for the Korean bellwethers and KOSPI, kept apart from the
    US price cache: merged into it, KRX-only sessions would add rows to it."""
    symbols = [k["yahoo"] for k in settings.get("korean") or []] + [settings.get("korea_index", "^KS11")]
    return cache.frame("themes", "krx-closes", lambda: yahoo.fetch_closes(symbols, period="5y", use_cache=False),
                       kind="daily_file")


def _korean(settings: dict, key: str, proxy: pd.Series, krx: pd.DataFrame, as_of: date) -> list[dict]:
    """Korean bellwethers: results dates from DART, their own move on the
    Korean session that day (beyond KOSPI), and the proxy on the US session
    of the same date -- the first to trade after a Korean-morning release."""
    out = []
    index = krx.get(settings.get("korea_index", "^KS11"))
    for spec in settings.get("korean") or []:
        if spec.get("group") != key:
            continue
        entry = {"symbol": spec["label"], "listing": spec["yahoo"], "in_universe": False, "reports": 0,
                 "impact": None, "own_mean_abs": None, "last": None, "next": None}
        try:
            filings = dart.results(spec["dart"], as_of)
        except Exception as exc:  # noqa: BLE001 - a refused search leaves the row, with why
            entry["error"] = describe_error(exc)
            out.append(entry)
            continue
        own, follow, moves = [], [], []
        close = krx.get(spec["yahoo"])
        for f in filings[:8]:
            day = pd.Timestamp(f["date"])
            if close is None or index is None or day not in close.dropna().index:
                continue
            c, i = close.dropna(), index.dropna()
            pos, ipos = c.index.get_loc(day), i.index.get_indexer([day])[0]
            if pos == 0 or ipos <= 0:
                continue
            move = 100 * (c.iloc[pos] / c.iloc[pos - 1] - 1)
            excess = move - 100 * (i.iloc[ipos] / i.iloc[ipos - 1] - 1)
            us = proxy[proxy.index >= day].dropna()
            follower = float(us.iloc[0]) if not us.empty and (us.index[0] - day).days <= 4 else None
            own.append(excess)
            follow.append(follower)
            moves.append({"date": f["date"], "move_pct": round(move, 2), "excess_pct": round(excess, 2),
                          "proxy_pct": None if follower is None else round(follower, 2), "url": f["url"]})
        entry["reports"] = len(moves)
        entry["impact"] = E.co_move(own, follow, min_reports=int(settings.get("min_reports", 4)))
        entry["own_mean_abs"] = round(sum(abs(m["move_pct"]) for m in moves) / len(moves), 2) if moves else None
        if moves:
            entry["last"] = {"date": moves[0]["date"], "session": moves[0]["date"], "move_pct": moves[0]["move_pct"],
                             "proxy_pct": moves[0]["proxy_pct"]}
        projected = T.project_next([date.fromisoformat(f["date"]) for f in filings], as_of)
        entry["next"] = {"date": projected.isoformat(), "timing": None, "projected": True} if projected else None
        entry["source_url"] = filings[0]["url"] if filings else None
        out.append(entry)
    return out


def _group(ctx, spec: dict, settings: dict, catalysts: dict, evidence: dict, excess: pd.DataFrame,
           market: pd.Series, as_of: date, krx: pd.DataFrame | None = None) -> dict:
    names = evidence.get("names") or {}
    etf = spec.get("etf")
    basket = list(spec.get("basket") or [])
    if etf and etf in ctx.etf_closes.columns:
        proxy_price = ctx.etf_closes[etf]
        proxy_label = etf
    elif basket:
        proxy_price = T.basket_index(ctx.closes, basket)
        proxy_label = f"equal-weight {', '.join(basket)}"
    else:
        proxy_price, proxy_label = pd.Series(dtype=float), None

    min_reports = int(settings.get("min_reports", 4))
    bellwethers = []
    for symbol in spec.get("bellwethers") or []:
        entry = names.get(symbol) or {}
        reactions = entry.get("reactions") or []
        sessions = [r["session"] for r in reactions if r.get("session")]
        if etf and etf in excess.columns:
            proxy = excess[etf]
        else:
            proxy = T.basket_excess(excess, basket, leave_out=symbol)
        stats = None
        if sessions and not proxy.empty:
            leader = E.moves_on(excess, symbol, sessions)
            follower = E.moves_on(proxy.to_frame("p"), "p", sessions)
            stats = E.co_move(leader, follower, min_reports=min_reports)
        nxt = _next_report(symbol, catalysts, reactions, as_of)
        last = reactions[0] if reactions else None
        bellwethers.append({
            "symbol": symbol,
            "in_universe": symbol in ctx.closes.columns,
            "next": nxt,
            "reports": len(sessions),
            "impact": stats,
            "own_mean_abs": entry.get("mean_abs_move"),
            "last": {"date": last["date"], "session": last["session"], "move_pct": last["move_pct"],
                     "proxy_pct": clean_float(E.moves_on(proxy.to_frame("p"), "p", [last["session"]])[0], 2)
                     if not proxy.empty else None} if last else None,
        })

    if krx is not None and not krx.empty:
        proxy = excess[etf] if etf and etf in excess.columns else T.basket_excess(excess, basket)
        bellwethers += _korean(settings, spec["key"], proxy, krx, as_of)

    end = (as_of + timedelta(days=int(settings.get("calendar_days", 42)))).isoformat()
    calendar = []
    for b in bellwethers:
        n = b["next"]
        if n and as_of.isoformat() < n["date"] <= end:
            calendar.append({"date": n["date"], "kind": "earnings", "symbol": b["symbol"], "timing": n["timing"],
                             "projected": n["projected"], "beta": (b["impact"] or {}).get("beta"),
                             "listing": b.get("listing")})
    patterns = [re.compile(p, re.I) for p in spec.get("macro") or []]
    for e in catalysts.get("events") or []:
        if e.get("lane") == "macro" and as_of.isoformat() < e["date"] <= end and any(p.search(e["title"]) for p in patterns):
            calendar.append({"date": e["date"], "kind": "macro", "title": e["title"], "time": e.get("time"),
                             "importance": e.get("importance")})
    relative = {}
    for key, symbol in (("SPX", ctx.primary.symbol), ("NDX", "^NDX")):
        if proxy_price.empty or symbol not in ctx.index_closes.columns:
            continue
        ratio = (proxy_price / ctx.index_closes[symbol].reindex(proxy_price.index)).dropna()
        if not ratio.empty:
            relative[key] = history_payload(ratio, years=10, digits=6)
    return {
        "key": spec["key"], "label": spec["label"], "proxy": proxy_label, "proxy_is_etf": bool(etf),
        "run_in": T.run_in(proxy_price, market) if not proxy_price.empty else {},
        # Proxy / index, unscaled: the page rebases it to 100 at the start of
        # whichever range is shown.
        "relative": relative,
        "bellwethers": bellwethers,
        "calendar": calendar,
    }


# --- CLOUD ----------------------------------------------------------------------

def _calendar_quarter(end: str) -> str:
    d = date.fromisoformat(end)
    # An off-cycle quarter counts toward the calendar quarter it mostly covers.
    mid = d - timedelta(days=45)
    return f"{mid.year}Q{(mid.month - 1) // 3 + 1}"


def _capex(ctx, settings: dict) -> dict:
    filers = list(settings.get("capex_filers") or [])
    cik_map = sec.fetch_ticker_cik_map()
    ciks = {t: cik_for(t, cik_map) for t in filers}
    sec.check_filings([c for c in ciks.values() if c])
    keep = int(settings.get("capex_quarters", 12))
    companies = []
    for ticker, cik in ciks.items():
        if not cik:
            continue
        facts = sec.fetch_company_facts(cik)
        series, tag = X.capex_series(facts)
        series = X.with_growth(series)[-keep:]
        leases = {r["end"]: r["value"] for r in X.quarterly(facts, X.LEASE_TAG)}
        companies.append({
            "symbol": ticker, "tag": tag,
            "quarters": [{"end": r["end"], "quarter": _calendar_quarter(r["end"]), "capex_bn": round(r["value"] / BN, 2),
                          "yoy_pct": r["yoy_pct"], "filed": r["filed"], "derived": r["derived"],
                          "leases_bn": round(leases[r["end"]] / BN, 2) if r["end"] in leases else None}
                         for r in series],
        })
    # The five together, per calendar quarter, only where all five have filed.
    totals: dict[str, dict] = {}
    for c in companies:
        for q in c["quarters"]:
            t = totals.setdefault(q["quarter"], {"quarter": q["quarter"], "capex_bn": 0.0, "filers": 0})
            t["capex_bn"] += q["capex_bn"]
            t["filers"] += 1
    rows = sorted(totals.values(), key=lambda t: t["quarter"])
    for i, t in enumerate(rows):
        t["capex_bn"] = round(t["capex_bn"], 2)
        t["complete"] = t["filers"] == len(companies)
        prior = next((p for p in rows if p["quarter"] == f"{int(t['quarter'][:4]) - 1}{t['quarter'][4:]}"), None)
        t["yoy_pct"] = round(100 * (t["capex_bn"] / prior["capex_bn"] - 1), 1) if prior and t["complete"] and prior["complete"] else None
    latest_filed = max((q["filed"] for c in companies for q in c["quarters"]), default=None)
    return {"companies": companies, "totals": rows, "latest_filed": latest_filed}


NVDA_DC = r"Data Center (?:quarterly )?revenue (?:was|of) \$([\d.]+) billion[^.]*?up ([\d,]+)% from a year ago"
NVDA_REVENUE = r"Revenue (?:was|of) \$([\d.]+) billion[^•]*?up ([\d,]+)% from a year ago"
NVDA_OUTLOOK = r"Revenue is expected to be \$([\d.]+) billion"


def _nvda(settings: dict) -> dict:
    """NVIDIA's data-center revenue and next-quarter outlook, from its releases."""
    cik = cik_for("NVDA", sec.fetch_ticker_cik_map())
    rows = []
    for r in releases.recent(cik, int(settings.get("nvda_quarters", 8))):
        dc, total, outlook = (releases.first(p, r["text"]) for p in (NVDA_DC, NVDA_REVENUE, NVDA_OUTLOOK))
        rows.append({"filed": r["filed"], "url": r["url"],
                     "dc_bn": float(dc[0]) if dc else None, "dc_yoy_pct": float(dc[1].replace(",", "")) if dc else None,
                     "revenue_bn": float(total[0]) if total else None,
                     "revenue_yoy_pct": float(total[1].replace(",", "")) if total else None,
                     "outlook_bn": float(outlook[0]) if outlook else None})
    if not any(r["dc_bn"] for r in rows):
        raise RuntimeError("no Data Center revenue line matched in the releases")
    return {"quarters": sorted(rows, key=lambda r: r["filed"])}


def _guidance(settings: dict) -> dict:
    """What each filer's last two releases say about capex ahead, quoted."""
    cik_map = sec.fetch_ticker_cik_map()
    out = []
    for ticker in settings.get("capex_filers") or []:
        cik = cik_for(ticker, cik_map)
        if not cik:
            continue
        items = [{"filed": r["filed"], "url": r["url"], "statements": releases.guidance(r["text"])}
                 for r in releases.recent(cik, 2)]
        out.append({"symbol": ticker, "releases": items})
    return {"companies": out}


def _tw_revenue(codes: dict, months: int, as_of: date) -> list[dict]:
    out = []
    for code, label in codes.items():
        rows = mops.fetch_history(code, as_of, months)
        latest = rows[-1]["month"] if rows else None
        out.append({"code": code, "label": label,
                    "months": [{k: r.get(k) for k in ("month", "revenue_k", "yoy_pct", "ytd_yoy_pct", "first_seen", "note")} for r in rows],
                    "due": T.monthly_due(latest, 10, as_of)})
    return out


def _openrouter(settings: dict, as_of: date) -> dict:
    frame, commit = altdata.openrouter_daily(as_of, months=int(settings.get("openrouter_months", 7)))
    if frame.empty:
        raise RuntimeError("no OpenRouter files read")
    today = datetime.now(timezone.utc).date()
    frame = frame[frame["usage_date"].dt.date < today]          # today's file is a day in progress
    wanted = list(settings.get("openrouter_providers") or [])
    dates = sorted(frame["usage_date"].unique())
    totals = frame.groupby("usage_date")[["tokens", "revenue"]].sum().reindex(dates)
    providers = []
    for slug in wanted:
        rows = frame[frame["provider_slug"] == slug].set_index("usage_date").reindex(dates)
        if rows["tokens"].notna().sum() == 0:
            continue
        tokens, revenue = rows["tokens"].fillna(0), rows["revenue"].fillna(0)
        last7_t, prev28_t = tokens.iloc[-7:].sum(), tokens.iloc[-35:-7].sum() / 4
        last7_r, prev28_r = revenue.iloc[-7:].sum(), revenue.iloc[-35:-7].sum() / 4
        providers.append({
            "slug": slug, "name": rows["provider_name"].dropna().iloc[-1] if rows["provider_name"].notna().any() else slug,
            "tokens_b": [round(v / 1e9, 2) for v in tokens], "revenue_k": [round(v / 1e3, 1) for v in revenue],
            "week_tokens_b": round(last7_t / 1e9, 1), "week_revenue_k": round(last7_r / 1e3, 1),
            "tokens_vs_4w_pct": round(100 * (last7_t / prev28_t - 1), 1) if prev28_t else None,
            "revenue_vs_4w_pct": round(100 * (last7_r / prev28_r - 1), 1) if prev28_r else None,
            "revenue_share_pct": round(100 * last7_r / totals["revenue"].iloc[-7:].sum(), 1) if totals["revenue"].iloc[-7:].sum() else None,
        })
    return {
        "dates": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates],
        "total_tokens_b": [round(v / 1e9, 1) for v in totals["tokens"]],
        "total_revenue_k": [round(v / 1e3, 1) for v in totals["revenue"]],
        "providers": providers, "commit": commit,
    }


def _latest_vintage(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Ramp republishes history; keep each row's latest scrape."""
    return frame.sort_values("scraped_at").drop_duplicates(keys, keep="last")


def _ramp() -> dict:
    tables, commit = altdata.ramp()
    pepm = _latest_vintage(tables["pepm"], ["date_month"]).sort_values("date_month")
    adoption = _latest_vintage(tables["adoption"], ["date_month"]).sort_values("date_month")
    dims = _latest_vintage(tables["pepm_by_dimension"], ["date_month", "dimension_type", "dimension_value"])
    latest = dims["date_month"].max()
    sectors = dims[(dims["date_month"] == latest) & (dims["dimension_type"] == "naics_sector")].sort_values("median_pepm", ascending=False)
    vendors = _latest_vintage(tables["vendors"], ["date_month", "vendor"]).sort_values("date_month")
    month = lambda v: pd.Timestamp(v).strftime("%Y-%m")  # noqa: E731
    return {
        "months": [month(v) for v in pepm["date_month"]],
        "median_pepm": [clean_float(v, 2) for v in pepm["median_pepm"]],
        "p90_pepm": [clean_float(v, 2) for v in pepm["p90_pepm"]],
        "p99_pepm": [clean_float(v, 2) for v in pepm["p99_pepm"]],
        "top10_median_pepm": [clean_float(v, 2) for v in pepm["top_10_percent_median_pepm"]],
        "top1_median_pepm": [clean_float(v, 2) for v in pepm["top_1_percent_median_pepm"]],
        "adoption": {"months": [month(v) for v in adoption["date_month"]],
                     "pct": [clean_float(v, 2) for v in adoption["adoption_rate_pct"]]},
        "sectors": {"month": month(latest) if pd.notna(latest) else None,
                    "rows": [{"sector": r.dimension_label, "median_pepm": clean_float(r.median_pepm, 2)} for r in sectors.itertuples()]},
        "vendors": {v: {"months": [month(x) for x in g["date_month"]], "pct": [clean_float(x, 2) for x in g["adoption_rate_pct"]]}
                    for v, g in vendors.groupby("vendor") if g["adoption_rate_pct"].iloc[-1] >= 1},
        "commit": commit,
    }


def _section(build) -> dict:
    try:
        return build()
    except Exception as exc:  # noqa: BLE001 - a source that fails leaves its reason, not a failed page
        return {"unavailable": describe_error(exc)}


# --- SEMIS -----------------------------------------------------------------------

def _korea(as_of: date) -> dict:
    rows, fetched = korea_customs.fetch_exports(as_of)
    rows = T.yoy_monthly(rows, "exports_k")
    latest = rows[-1]["month"] if rows else None
    return {"months": [{**r, "exports_bn": round(r["exports_k"] / 1e6, 2)} for r in rows], "fetched": fetched,
            "due": T.monthly_due(latest, 15, as_of)}


def _korea_flash(as_of: date) -> dict:
    rows, failed = motie.fetch(as_of)
    if not rows:
        raise RuntimeError("; ".join(failed) or "no release read")
    latest = rows[-1]["month"]
    return {"months": rows, "failed": failed, "due": T.monthly_due(latest, 1, as_of), "page": motie.LIST_URL}


def _family(title: str) -> str:
    return next((key for key in ("DDR5", "DDR4", "AMD", "Intel") if title.startswith(key)), "other")


def _pcpp() -> dict:
    out: dict = {"failed": []}
    for kind in ("memory", "cpu"):
        charts, failed = pcpartpicker.fetch(kind)
        out["failed"] += failed
        rows = []
        for c in charts:
            day = date.fromisoformat(c["image_date"])
            rows.append({"title": c["title"], "family": _family(c["title"]), "image_date": c["image_date"],
                         **pcpartpicker.summary(c["series"], day), "index": pcpartpicker.weekly_index(c["series"])})
        families = {}
        for fam in sorted({r["family"] for r in rows}):
            members = [r for r in rows if r["family"] == fam]
            agg = {k: (round(statistics.median(v), 1) if (v := [r[k] for r in members if r.get(k) is not None]) else None)
                   for k in ("chg_1m", "chg_3m", "chg_6m", "chg_12m")}
            dates = members[0]["index"]["dates"]
            series = [round(statistics.median(vals), 1) if (vals := [m["index"]["values"][i] for m in members
                      if i < len(m["index"]["values"]) and m["index"]["values"][i] is not None]) else None
                      for i in range(len(dates))]
            families[fam] = {**agg, "count": len(members), "index": {"dates": dates, "values": series}}
        out[kind] = {"rows": rows, "families": families, "page": pcpartpicker.BASE.format(kind=kind)}
    return out


# --- Drivers: the industry series in one shape, for the event cards ---------------
# Each series lists its points with the date it became public ("available"),
# so a card can say what has been released since the company last reported.
# A month's figure is dated by when its publisher releases it -- the 10th of
# the next month for Taiwan's monthly revenue, about the 15th for Korea's
# customs data -- or by when this build first saw it, if earlier.

def _after_month(month: str, day: int) -> str:
    year, m = (int(p) for p in month.split("-"))
    year, m = (year, m + 1) if m < 12 else (year + 1, 1)
    return date(year, m, min(day, 28)).isoformat()


def _driver(key: str, label: str, themes: list[str], kind: str, unit: str, points: list[dict]) -> dict | None:
    points = sorted((p for p in points if p.get("value") is not None and p.get("available")), key=lambda p: p["available"])
    return {"key": key, "label": label, "themes": themes, "kind": kind, "unit": unit, "points": points} if points else None


def _monthly(rows: list[dict], value: str, day: int, released: str | None = None) -> list[dict]:
    out = []
    for r in rows or []:
        available = r.get(released) if released else None
        available = available or min(filter(None, [r.get("first_seen"), _after_month(r["month"], day)]))
        out.append({"period": r["month"], "available": available, "value": r.get(value)})
    return out


def _drivers(cloud: dict, semis: dict) -> list[dict]:
    """kind 'yoy': the value is a year-on-year change, compared as is; 'level':
    a level, compared as a % change since the report."""
    out = []
    # A failed section is {"unavailable": ...}, not a list.
    listed = lambda x: x if isinstance(x, list) else []  # noqa: E731
    for tw in listed(semis.get("tw")):
        out.append(_driver(f"tw_{tw['code']}", f"{tw['label']} monthly revenue, y/y", ["semis"], "yoy", "pct",
                           _monthly(tw.get("months"), "yoy_pct", 10)))
    for tw in listed(cloud.get("odm")):
        out.append(_driver(f"tw_{tw['code']}", f"{tw['label']} monthly revenue, y/y", ["cloud"], "yoy", "pct",
                           _monthly(tw.get("months"), "yoy_pct", 10)))
    out.append(_driver("korea_chips", "Korea chip exports (customs), y/y", ["semis"], "yoy", "pct",
                       _monthly((semis.get("korea") or {}).get("months"), "yoy_pct", 15)))
    out.append(_driver("korea_flash", "Korea chip exports (1st-of-month release), y/y", ["semis"], "yoy", "pct",
                       _monthly((semis.get("korea_flash") or {}).get("months"), "semis_yoy_pct", 1, released="released")))
    for family, agg in ((semis.get("pcpp") or {}).get("memory") or {}).get("families", {}).items():
        index = agg.get("index") or {}
        out.append(_driver(f"pcpp_{family.lower()}", f"{family} retail price index (PCPartPicker UK)", ["semis"], "level", "index",
                           [{"period": d, "available": d, "value": v} for d, v in zip(index.get("dates", []), index.get("values", []))]))
    capex = [t for t in (cloud.get("capex") or {}).get("totals") or [] if t.get("complete")]
    out.append(_driver("hyperscaler_capex", "Five hyperscalers' capex, y/y", ["cloud", "semis"], "yoy", "pct",
                       [{"period": t["quarter"], "available": t.get("available") or _quarter_public(t["quarter"]), "value": t.get("yoy_pct")}
                        for t in capex]))
    out.append(_driver("nvda_dc", "NVIDIA data-center revenue, y/y", ["cloud", "semis"], "yoy", "pct",
                       [{"period": q.get("filed"), "available": q.get("filed"), "value": q.get("dc_yoy_pct")}
                        for q in (cloud.get("nvda") or {}).get("quarters") or []]))
    router = cloud.get("openrouter") or {}
    if router.get("dates"):
        tokens = pd.Series(router["total_tokens_b"], index=pd.to_datetime(router["dates"])).rolling(7).sum().dropna()
        weekly = tokens.iloc[::-7][::-1]
        out.append(_driver("openrouter_tokens", "OpenRouter tokens, trailing 7 days", ["cloud"], "level", "bn",
                           [{"period": d.strftime("%Y-%m-%d"), "available": (d + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                             "value": round(float(v), 1)} for d, v in weekly.items()]))
    ramp = cloud.get("ramp") or {}
    out.append(_driver("ramp_median", "Ramp AI spend per employee, median", ["cloud"], "level", "usd",
                       [{"period": m, "available": _after_month(m, 15), "value": v}
                        for m, v in zip(ramp.get("months") or [], ramp.get("median_pepm") or [])]))
    return [d for d in out if d]


def _quarter_public(quarter: str) -> str:
    """A calendar quarter's capex is public once the last of the five has
    filed -- about six weeks after it ends."""
    year, q = int(quarter[:4]), int(quarter[-1])
    end = date(year, 3 * q, 28) + timedelta(days=4)
    return (end.replace(day=1) + timedelta(days=45)).isoformat()


# --- build -------------------------------------------------------------------------

def build(ctx, *, inputs: dict | None = None) -> dict:
    inputs = inputs or {}
    catalysts, evidence = inputs.get("catalysts"), inputs.get("evidence")
    if not catalysts or not evidence:
        raise RuntimeError("THEMES needs this session's CATALYSTS and EVIDENCE")
    settings = dict(ctx.config["themes"])
    as_of = date.fromisoformat(ctx.as_of)
    market = ctx.index_closes[ctx.primary.symbol]
    etfs = [s for s in {*settings.get("etfs", []), *(g.get("etf") for g in settings["groups"] if g.get("etf"))}
            if s in ctx.etf_closes.columns]
    excess = E.daily_excess(pd.concat([ctx.closes, ctx.etf_closes[etfs]], axis=1), market)
    try:
        krx = _krx_closes(settings) if settings.get("korean") else None
    except Exception:
        krx = None
    groups = [_group(ctx, spec, settings, catalysts, evidence, excess, market, as_of, krx) for spec in settings["groups"]]

    cloud = {
        "capex": _section(lambda: _capex(ctx, settings)),
        "guidance": _section(lambda: _guidance(settings)),
        "nvda": _section(lambda: _nvda(settings)),
        "odm": _section(lambda: _tw_revenue(settings["tw_cloud"], int(settings.get("tw_months", 37)), as_of)),
        "openrouter": _section(lambda: _openrouter(settings, as_of)),
        "ramp": _section(_ramp),
    }
    semis = {
        "tw": _section(lambda: _tw_revenue(settings["tw_semis"], int(settings.get("tw_months", 37)), as_of)),
        "korea": _section(lambda: _korea(as_of)),
        "korea_flash": _section(lambda: _korea_flash(as_of)),
        "adata": _section(lambda: {"notes": adata.fetch_recent(as_of, 6)}),
        "pcpp": _section(_pcpp),
    }
    _data_dates(groups, cloud, semis, as_of, settings)
    _log(ctx, cloud, semis)
    for g in groups:
        g["calendar"].sort(key=lambda e: (e["date"], {"data": 0, "macro": 1, "earnings": 2}[e["kind"]]))
    return {"as_of": ctx.as_of, "calendar_days": int(settings.get("calendar_days", 42)), "groups": groups,
            "heatmap": _heatmap(catalysts, as_of, int(settings.get("heatmap_days", 21))),
            "membership": _membership(ctx, settings, excess),
            "member_corr": float(settings.get("member_corr", 0.55)),
            "cloud": cloud, "semis": semis, "drivers": _section(lambda: _drivers(cloud, semis))}


def _heatmap(catalysts: dict, as_of: date, days: int) -> dict:
    """S&P 500 weight reporting, by GICS sector and session, over the next ``days``."""
    end = (as_of + timedelta(days=days)).isoformat()
    events = [e for e in catalysts.get("events") or [] if e.get("event_type") == "earnings"
              and as_of.isoformat() < e["date"] <= end and (e.get("index_weights") or {}).get("SPX")]
    dates = sorted({e["date"] for e in events})
    sectors = sorted({e.get("sector") or "Other" for e in events})
    cells: dict[tuple[str, str], dict] = {}
    for e in events:
        cell = cells.setdefault((e.get("sector") or "Other", e["date"]), {"weight": 0.0, "names": []})
        cell["weight"] += e["index_weights"]["SPX"]
        cell["names"].append((e["symbol"], e["index_weights"]["SPX"]))
    rows = []
    for sector in sectors:
        row = []
        for day in dates:
            c = cells.get((sector, day))
            row.append(None if not c else {"w": round(c["weight"], 3),
                                           "top": [n for n, _ in sorted(c["names"], key=lambda x: -x[1])[:4]],
                                           "n": len(c["names"])})
        rows.append({"sector": sector, "cells": row, "total": round(sum(c["w"] for c in row if c), 2)})
    return {"dates": dates, "rows": sorted(rows, key=lambda r: -r["total"]),
            "day_totals": [round(sum((r["cells"][i] or {}).get("w", 0) for r in rows), 2) for i in range(len(dates))]}


def _membership(ctx, settings: dict, excess: pd.DataFrame) -> dict:
    """Which themes each name belongs to: named in the config (bellwether or
    basket), or trading with the theme's proxy (daily excess-return
    correlation over the last year at or above ``member_corr``)."""
    threshold = float(settings.get("member_corr", 0.55))
    recent = excess.iloc[-252:]
    out: dict[str, list[dict]] = {}
    for spec in settings["groups"]:
        etf, basket = spec.get("etf"), list(spec.get("basket") or [])
        named = set(spec.get("bellwethers") or []) | set(basket)
        proxy = recent[etf] if etf and etf in recent.columns else T.basket_excess(recent, basket)
        if proxy.dropna().empty:
            continue
        names = recent[[c for c in ctx.closes.columns if c in recent.columns]]
        overlap = names.notna().mul(proxy.notna(), axis=0).sum()
        corr = names.corrwith(proxy).where(overlap >= 150)        # too little shared history: no reading
        for symbol in set(corr[corr >= threshold].index) | (named & set(ctx.closes.columns)):
            value = corr.get(symbol)
            out.setdefault(symbol, []).append({
                "key": spec["key"], "label": spec["label"],
                "role": "bellwether" if symbol in (spec.get("bellwethers") or []) else "basket" if symbol in basket else "trades with",
                "corr": None if value is None or pd.isna(value) else round(float(value), 2)})
    return out


def _data_dates(groups: list[dict], cloud: dict, semis: dict, as_of: date, settings: dict) -> None:
    """Puts each industry series' next due date on its group's calendar."""
    end = (as_of + timedelta(days=int(settings.get("calendar_days", 42)))).isoformat()
    by_key = {g["key"]: g for g in groups}

    def add(key: str, title: str, due: dict | None) -> None:
        if due and due["due"] <= end and key in by_key:
            by_key[key]["calendar"].append({"date": max(due["due"], (as_of + timedelta(days=1)).isoformat()), "kind": "data",
                                            "title": f"{title} ({due['month']})", "late": due["late"]})

    for series in cloud.get("odm") if isinstance(cloud.get("odm"), list) else []:
        add("cloud", f"{series['label']} monthly revenue", series.get("due"))
    for series in semis.get("tw") if isinstance(semis.get("tw"), list) else []:
        add("semis", f"{series['label']} monthly revenue", series.get("due"))
    korea = semis.get("korea") or {}
    add("semis", "Korea IC exports (customs, confirmed)", korea.get("due"))
    flash = semis.get("korea_flash") or {}
    add("semis", "Korea exports, 1st-of-month release (semis first)", flash.get("due"))


def _log(ctx, cloud: dict, semis: dict) -> None:
    def record(source_id, label, url, section, observed, policy):
        failed = isinstance(section, dict) and "unavailable" in section
        ctx.log.add(SourceRecord(source_id, label, url, None if failed else observed, status="error" if failed else "ok",
                                 error=section["unavailable"][:ERROR_DETAIL_CHARS] if failed else None, policy=policy))

    capex = cloud["capex"]
    record("sec_capex", "Cloud capex (SEC XBRL 10-Q/10-K)", "https://www.sec.gov/edgar/search/", capex,
           None if "unavailable" in capex else max((c["quarters"][-1]["end"] for c in capex["companies"] if c["quarters"]), default=None),
           "quarterly_filing")
    nv = cloud["nvda"]
    record("sec_releases", "Earnings releases (8-K Ex. 99.1): NVIDIA Data Center, capex guidance", "https://www.sec.gov/edgar/search/", nv,
           None if "unavailable" in nv else nv["quarters"][-1]["filed"], "quarterly_filing")
    odm = cloud["odm"]
    record("mops_revenue", "Taiwan monthly revenue (MOPS)", mops.PAGE_URL, odm if isinstance(odm, dict) else {},
           None if isinstance(odm, dict) else max((s["months"][-1]["month"] + "-01" for s in odm if s["months"]), default=None),
           "monthly_release")
    orr = cloud["openrouter"]
    record("altdata_openrouter", "OpenRouter tokens & estimated revenue (alternative-data)", altdata.OPENROUTER_URL, orr,
           None if "unavailable" in orr else (orr["dates"][-1] if orr["dates"] else None), "daily_close")
    ramp = cloud["ramp"]
    record("altdata_ramp", "Ramp AI Index (alternative-data)", altdata.RAMP_URL, ramp,
           None if "unavailable" in ramp else (ramp["months"][-1] + "-01" if ramp["months"] else None), "monthly_release")
    korea = semis["korea"]
    record("korea_customs", "Korea Customs IC exports (HS 8542)", korea_customs.HOME_URL, korea,
           None if "unavailable" in korea else (korea["months"][-1]["month"] + "-01" if korea["months"] else None), "monthly_release")
    flash = semis["korea_flash"]
    record("motie_trade", "Korea monthly trade release (MOTIE, 1st of month)", motie.LIST_URL, flash,
           None if "unavailable" in flash else flash["months"][-1]["month"] + "-01", "monthly_release")
    notes = semis["adata"]
    record("adata_market_watch", "ADATA Memory & Flash Market Watch", "https://industrial.adata.com/en/edm", notes,
           None if "unavailable" in notes or not notes["notes"] else notes["notes"][0]["month"] + "-01", "monthly_release")
    pc = semis["pcpp"]
    record("pcpartpicker", "PCPartPicker UK price trends (memory, CPU)", "https://uk.pcpartpicker.com/trends/", pc,
           None if "unavailable" in pc else max((r["image_date"] for k in ("memory", "cpu") for r in pc.get(k, {}).get("rows", [])), default=None),
           "daily_close")
