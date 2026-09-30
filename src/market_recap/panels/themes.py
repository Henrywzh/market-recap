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
from ..sources import adata, altdata, korea_customs, mops, pcpartpicker, sec
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


def _group(ctx, spec: dict, settings: dict, catalysts: dict, evidence: dict, excess: pd.DataFrame,
           market: pd.Series, as_of: date) -> dict:
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

    end = (as_of + timedelta(days=int(settings.get("calendar_days", 42)))).isoformat()
    calendar = []
    for b in bellwethers:
        n = b["next"]
        if n and as_of.isoformat() < n["date"] <= end:
            calendar.append({"date": n["date"], "kind": "earnings", "symbol": b["symbol"], "timing": n["timing"],
                             "projected": n["projected"], "beta": (b["impact"] or {}).get("beta")})
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
    groups = [_group(ctx, spec, settings, catalysts, evidence, excess, market, as_of) for spec in settings["groups"]]

    cloud = {
        "capex": _section(lambda: _capex(ctx, settings)),
        "odm": _section(lambda: _tw_revenue(settings["tw_cloud"], int(settings.get("tw_months", 37)), as_of)),
        "openrouter": _section(lambda: _openrouter(settings, as_of)),
        "ramp": _section(_ramp),
    }
    semis = {
        "tw": _section(lambda: _tw_revenue(settings["tw_semis"], int(settings.get("tw_months", 37)), as_of)),
        "korea": _section(lambda: _korea(as_of)),
        "adata": _section(lambda: {"notes": adata.fetch_recent(as_of, 6)}),
        "pcpp": _section(_pcpp),
    }
    _data_dates(groups, cloud, semis, as_of, settings)
    _log(ctx, cloud, semis)
    for g in groups:
        g["calendar"].sort(key=lambda e: (e["date"], {"data": 0, "macro": 1, "earnings": 2}[e["kind"]]))
    return {"as_of": ctx.as_of, "calendar_days": int(settings.get("calendar_days", 42)), "groups": groups,
            "cloud": cloud, "semis": semis}


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


def _log(ctx, cloud: dict, semis: dict) -> None:
    def record(source_id, label, url, section, observed, policy):
        failed = isinstance(section, dict) and "unavailable" in section
        ctx.log.add(SourceRecord(source_id, label, url, None if failed else observed, status="error" if failed else "ok",
                                 error=section["unavailable"][:ERROR_DETAIL_CHARS] if failed else None, policy=policy))

    capex = cloud["capex"]
    record("sec_capex", "Cloud capex (SEC XBRL 10-Q/10-K)", "https://www.sec.gov/edgar/search/", capex,
           None if "unavailable" in capex else max((c["quarters"][-1]["end"] for c in capex["companies"] if c["quarters"]), default=None),
           "quarterly_filing")
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
    notes = semis["adata"]
    record("adata_market_watch", "ADATA Memory & Flash Market Watch", "https://industrial.adata.com/en/edm", notes,
           None if "unavailable" in notes or not notes["notes"] else notes["notes"][0]["month"] + "-01", "monthly_release")
    pc = semis["pcpp"]
    record("pcpartpicker", "PCPartPicker UK price trends (memory, CPU)", "https://uk.pcpartpicker.com/trends/", pc,
           None if "unavailable" in pc else max((r["image_date"] for k in ("memory", "cpu") for r in pc.get(k, {}).get("rows", [])), default=None),
           "daily_close")
