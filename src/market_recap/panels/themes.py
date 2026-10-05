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
  exports (Korea Customs), the memory, DRAM and flash lines inside them, BLS semiconductor price indexes (FRED), ADATA's monthly memory note, and UK retail prices
  of memory kits and CPUs read from PCPartPicker's trend charts.

Each source is optional: one that fails leaves its section's reason on the
page and the rest renders.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
import re

import pandas as pd

from ..compute import capex as X
from ..compute import events as E
from ..compute import themes as T
from .. import cache
from ..sources import adata, alfred, altdata, dart, eia, fred, korea_customs, mops, motie, pcpartpicker, releases, sec, yahoo
from ..sources import expectations as expectations_source
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
    return {"months": [{**r, "exports_bn": None if r["exports_k"] is None else round(r["exports_k"] / 1e6, 2)} for r in rows], "fetched": fetched,
            "due": T.monthly_due(latest, 15, as_of)}


def _korea_flash(as_of: date) -> dict:
    rows, failed = motie.fetch(as_of)
    if not rows:
        raise RuntimeError("; ".join(failed) or "no release read")
    latest = rows[-1]["month"]
    return {"months": rows, "failed": failed, "due": T.monthly_due(latest, 1, as_of), "page": motie.LIST_URL}


# PCPartPicker's Cloudflare refuses cloud servers (HTTP 403) and is not worked
# around. The cloud build reads the ratios a home-connection job committed;
# it does not ask the site. A local build still reads it.
PCPP_SKIP_REASON = pcpartpicker.SKIPPED


def _pcpp(as_of: date) -> dict:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return pcpartpicker.load_feed(as_of)
    return pcpartpicker.snapshot()


MEMORY_MONTHS = 48
CHIP_MONTHS = 60
PUBLISH_DAY = 15
# Before the mid-month publication, the latest confirmed customs period is
# two months behind. Keep that lag as well as twelve months of YoY bases.
CUSTOMS_RELEASE_LAG_MONTHS = 2


def _specs(settings: dict, key: str) -> list[dict]:
    rows = settings.get(key) or []
    if not rows:
        raise RuntimeError(f"themes.{key} is empty")
    return rows


def _memory_exports(settings: dict, as_of: date) -> dict:
    """HS 854232 and the DRAM and flash lines inside it. Codes come from config."""
    series, failed = [], []
    for spec in _specs(settings, "memory_exports"):
        code, label = str(spec["code"]), str(spec["label"])
        try:
            rows, fetched = korea_customs.fetch_code(as_of, code, MEMORY_MONTHS + 12 + CUSTOMS_RELEASE_LAG_MONTHS)
            if not rows:
                raise RuntimeError("no monthly observations")
        except Exception as exc:  # one code fails alone
            failed.append(f"{label} ({code}): {describe_error(exc)}")
            continue
        by_month = {row["month"]: row for row in rows if row["month"] <= as_of.strftime("%Y-%m")}
        rows = [{"exports_k": None, "usd_per_kg": None, **row, **by_month.get(row["month"], {})}
                for row in T.fill_months({month: None for month in by_month})]
        rows = T.yoy_monthly(T.yoy_monthly(rows, "exports_k"), "usd_per_kg", key="unit_yoy_pct")[-MEMORY_MONTHS:]
        months = []
        for row in rows:
            months.append({
                "month": row["month"],
                "exports_bn": None if row["exports_k"] is None else round(row["exports_k"] / 1e6, 2),
                "yoy_pct": row.get("yoy_pct"),
                "usd_per_kg": None if row.get("usd_per_kg") is None else round(row["usd_per_kg"], 2),
                "unit_yoy_pct": row.get("unit_yoy_pct"),
                "weight_t": None if row.get("weight_t") is None else round(row["weight_t"], 1),
                "first_seen": row.get("first_seen"),
            })
        latest = next((row["month"] for row in reversed(months) if row["exports_bn"] is not None), None)
        series.append({"code": code, "label": label, "detail": spec.get("detail"), "months": months,
                       "fetched": fetched, "due": T.monthly_due(latest, PUBLISH_DAY, as_of)})
    if not series:
        raise RuntimeError("; ".join(failed) or "no memory exports read")
    return {"series": series, "failed": failed}


def _chip_prices(settings: dict, as_of: date) -> dict:
    """BLS semiconductor price indexes via FRED. Ids come from config."""
    series, failed = [], []
    for spec in _specs(settings, "chip_prices"):
        sid, label = str(spec["id"]), str(spec["label"])
        try:
            frame, url = fred.fetch_series(sid)
        except Exception as exc:
            failed.append(f"{label} ({sid}): {describe_error(exc)}")
            continue
        by_month = {}
        for dt, value in zip(frame["date"], frame["value"]):
            if pd.Timestamp(dt).date() <= as_of:
                by_month[pd.Timestamp(dt).strftime("%Y-%m")] = None if pd.isna(value) else float(value)
        rows = T.yoy_monthly(T.fill_months(by_month), "value")[-CHIP_MONTHS:]
        if not rows:
            failed.append(f"{label} ({sid}): no monthly observations")
            continue
        months = [{"month": row["month"], "value": None if row["value"] is None else round(float(row["value"]), 3),
                   "yoy_pct": row.get("yoy_pct")} for row in rows]
        latest = next((row["month"] for row in reversed(months) if row["value"] is not None), None)
        series.append({"id": sid, "label": label, "detail": spec.get("detail"), "url": url, "page": "https://fred.stlouisfed.org/series/" + sid, "months": months,
                       "due": T.monthly_due(latest, PUBLISH_DAY, as_of)})
    if not series:
        raise RuntimeError("; ".join(failed) or "no chip prices read")
    return {"series": series, "failed": failed}


# --- ENERGY -------------------------------------------------------------------------
# EIA's weekly inventories against the same week of the last five years,
# front-month futures and the 3-2-1 crack, and how each bellwether's excess
# return has moved with oil, gas and the crack over the last year.
ENERGY_FUTURES = {"CL=F": "WTI crude", "BZ=F": "Brent crude", "NG=F": "Henry Hub gas",
                  "RB=F": "RBOB gasoline", "HO=F": "Heating oil"}
EIA_WEEKS = 260


def _futures_closes() -> pd.DataFrame:
    """Kept apart from the members' price cache, like the Korean closes: a
    futures session is not an equity session."""
    return cache.frame("themes", "energy-futures", lambda: yahoo.fetch_closes(list(ENERGY_FUTURES), period="5y", use_cache=False),
                       kind="daily_file")


def _eia_section(key: str) -> dict:
    _, _, label, unit = eia.SERIES[key]
    frame = eia.seasonal(eia.fetch(key)).iloc[-EIA_WEEKS:]
    last = frame.iloc[-1]
    num = lambda v: None if pd.isna(v) else round(float(v), 2)  # noqa: E731
    return {"label": label, "unit": unit, "dates": [d.strftime("%Y-%m-%d") for d in frame.index],
            "value": [num(v) for v in frame["value"]], "avg5": [num(v) for v in frame["avg5"]],
            "latest": {"date": frame.index[-1].strftime("%Y-%m-%d"), "value": num(last["value"]), "change": num(last["change"]),
                       "avg5": num(last["avg5"]), "vs_avg5_pct": num(last["vs_avg5_pct"])}}


def _sensitivities(excess: pd.DataFrame, names: list[str], drivers: dict[str, pd.Series]) -> list[dict]:
    rows = []
    for name in names:
        if name not in excess.columns:
            continue
        row = {"symbol": name}
        for key, driver in drivers.items():
            row[key] = T.sensitivity(excess[name], driver)
        rows.append(row)
    return rows


def _energy(spec: dict, excess: pd.DataFrame, as_of: date) -> dict:
    out: dict = {"eia": {key: _section(lambda key=key: _eia_section(key)) for key in eia.SERIES}}
    futures = _futures_closes()
    prices = {}
    for symbol, label in ENERGY_FUTURES.items():
        if symbol in futures.columns:
            s = futures[symbol].dropna().iloc[-756:]
            prices[symbol] = {"label": label, "dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), 3) for v in s]}
    crack = T.crack_321(futures.get("CL=F"), futures.get("RB=F"), futures.get("HO=F")) if {"CL=F", "RB=F", "HO=F"} <= set(futures.columns) else pd.Series(dtype=float)
    if not crack.empty:
        c = crack.iloc[-756:]
        prices["crack"] = {"label": "3-2-1 crack ($/bbl)", "dates": [d.strftime("%Y-%m-%d") for d in c.index], "values": [round(float(v), 2) for v in c]}
    out["prices"] = prices
    gas, _ = fred.fetch_series("GASREGW")
    gas = gas.set_index("date")["value"].iloc[-260:]
    out["retail_gasoline"] = {"dates": [d.strftime("%Y-%m-%d") for d in gas.index], "values": [round(float(v), 3) for v in gas]}
    drivers = {"wti": futures["CL=F"].pct_change(fill_method=None) * 100 if "CL=F" in futures.columns else pd.Series(dtype=float),
               "gas": futures["NG=F"].pct_change(fill_method=None) * 100 if "NG=F" in futures.columns else pd.Series(dtype=float),
               "crack": crack.diff()}
    out["sensitivity"] = {"drivers": {"wti": "WTI, per 1% move", "gas": "Henry Hub, per 1% move", "crack": "3-2-1 crack, per $1 move"},
                          "rows": _sensitivities(excess, [spec.get("etf") or ""] + list(spec.get("bellwethers") or []), drivers)}
    out["next"] = {"petroleum": eia.next_release(as_of, 2).isoformat(), "gas_storage": eia.next_release(as_of, 3).isoformat()}
    return out


# --- HOUSING ------------------------------------------------------------------------
HOUSING_SERIES = {
    "MORTGAGE30US": ("30-year mortgage rate (Freddie Mac)", "pct", "weekly"),
    "HOUST": ("Housing starts, SAAR (thousands)", "k", "monthly"),
    "HOUST1F": ("Single-family starts, SAAR (thousands)", "k", "monthly"),
    "PERMIT": ("Building permits, SAAR (thousands)", "k", "monthly"),
    "HSN1F": ("New home sales, SAAR (thousands)", "k", "monthly"),
    "MSACSR": ("New homes for sale, months' supply", "months", "monthly"),
    "CSUSHPINSA": ("Case-Shiller US home price index", "index", "monthly"),
}


def _release_dates(series_id: str) -> dict[str, str]:
    """Observation date -> the day it was first public, from ALFRED; empty
    without a key or when ALFRED fails, and the caller's lag stands in."""
    if not alfred.available():
        return {}
    try:
        first = alfred.first_releases(series_id)
    except Exception:  # noqa: BLE001 -- a dating refinement, never a reason to drop the series
        return {}
    return {d.strftime("%Y-%m-%d"): r.strftime("%Y-%m-%d") for d, r in zip(first["date"], first["released"])}


PUBLISHED_SINCE = "2014-01-01"


def _published(series_id: str, freq: str, start: pd.Timestamp) -> dict | None:
    """Each observation as its first release said it, from ``start``: the
    first print and the year-earlier value as known that day. What a stock
    card compares against a report date; the charts keep the current vintage."""
    if freq == "daily" or not alfred.available():
        return None
    try:
        frame = alfred.as_published(alfred.vintages(series_id, since=PUBLISHED_SINCE), freq)
    except Exception:  # noqa: BLE001 -- the card falls back to the current vintage
        return None
    frame = frame[frame["date"] >= start]
    if frame.empty:
        return None
    num = lambda v: None if v is None or pd.isna(v) else round(float(v), 3)  # noqa: E731
    return {"dates": [d.strftime("%Y-%m-%d") for d in frame["date"]], "available": [d.strftime("%Y-%m-%d") for d in frame["released"]],
            "values": [num(v) for v in frame["value"]], "year_ago": [num(v) for v in frame["year_ago"]]}


def _dated(series_id: str, index: pd.DatetimeIndex, lag: tuple, published: dict | None = None) -> tuple[list[str], str]:
    # The vintages behind ``published`` already say when each date was first public.
    exact = dict(zip(published["dates"], published["available"])) if published else _release_dates(series_id)
    dates = [d.strftime("%Y-%m-%d") for d in index]
    out = [exact.get(d) or _available(d_, lag) for d, d_ in zip(dates, index)]
    return out, ("alfred" if dates and dates[-1] in exact else "approximate")


def _fred_section(series_id: str, label: str, unit: str, freq: str) -> dict:
    frame, _ = fred.fetch_series(series_id)
    s = frame.set_index("date")["value"].iloc[-(520 if freq == "weekly" else 120):]
    # Freddie Mac's weekly rate is dated by its release; Census's months are
    # public in the second half of the next month.
    published = _published(series_id, freq, s.index[0])
    available, dated = _dated(series_id, s.index, ("days", 0) if freq == "weekly" else ("months", 1, 26), published)
    return {"id": series_id, "label": label, "unit": unit, "freq": freq,
            "dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), 3) for v in s],
            "available": available, "dated": dated, "published": published}


def _housing(spec: dict, excess: pd.DataFrame, as_of: date) -> dict:
    out: dict = {"series": {sid: _section(lambda sid=sid, meta=meta: _fred_section(sid, *meta)) for sid, meta in HOUSING_SERIES.items()}}
    ten, _ = fred.fetch_series("DGS10")
    ten = ten.set_index("date")["value"]
    drivers = {"ten_year": ten.diff() * 100}          # basis points a day
    out["sensitivity"] = {"drivers": {"ten_year": "10-year yield, per 1bp move"},
                          "rows": _sensitivities(excess, [spec.get("etf") or ""] + list(spec.get("bellwethers") or []), drivers)}
    out["next"] = {"mortgage_rate": eia.next_release(as_of, 3).isoformat()}
    return out


# --- BANKS & CONSUMER ---------------------------------------------------------------
# FRED series in one shape: (label, short name, unit, frequency, release lag).
# The lag says when an observation became public: ("days", n) after its FRED
# date, or ("months", n, day) -- that day of the n-th month after the month it
# covers. H.8 is published on Friday for the week ending nine days earlier;
# claims on Thursday for the week ending the Saturday before; the bank call-
# report delinquency rates about two months after the quarter; the loan
# officer survey early in the second month of its quarter.
BANKS_SERIES = {
    "TOTLL": ("Loans and leases, all commercial banks ($bn)", "LOANS", "bn", "weekly", ("days", 9)),
    "DPSACBW027SBOG": ("Deposits, all commercial banks ($bn)", "DEPOSITS", "bn", "weekly", ("days", 9)),
    "T10Y2Y": ("10-year less 2-year Treasury yield", "2s10s", "rate", "daily", ("days", 0)),
    "T10Y3M": ("10-year less 3-month Treasury yield", "3m10y", "rate", "daily", ("days", 0)),
    "BAMLH0A0HYM2": ("High-yield option-adjusted spread (ICE BofA)", "HY OAS", "rate", "daily", ("days", 1)),
    "DRALACBS": ("Delinquency rate, all loans, commercial banks", "DELINQ ALL", "rate", "quarterly", ("days", 146)),
    "DRCCLACBS": ("Delinquency rate, credit cards", "DELINQ CARDS", "rate", "quarterly", ("days", 146)),
    "DRCRELEXFACBS": ("Delinquency rate, commercial real estate ex-farmland", "DELINQ CRE", "rate", "quarterly", ("days", 146)),
    "DRTSCILM": ("Loan officer survey: net % of banks tightening C&I standards (large & mid firms)", "SLOOS C&I", "pct", "quarterly", ("days", 36)),
}
CONSUMER_SERIES = {
    "RSAFS": ("Retail and food services sales ($m, SA)", "RETAIL SALES", "m", "monthly", ("months", 1, 16)),
    "RSFSXMV": ("Retail sales ex motor vehicles ($m, SA)", "EX AUTOS", "m", "monthly", ("months", 1, 16)),
    "PCEC96": ("Real personal consumption expenditures (chained $bn, SAAR)", "REAL PCE", "bn", "monthly", ("months", 1, 28)),
    "PSAVERT": ("Personal saving rate", "SAVING RATE", "rate", "monthly", ("months", 1, 28)),
    "TOTALSL": ("Consumer credit outstanding ($m)", "CREDIT", "m", "monthly", ("months", 2, 8)),
    "UMCSENT": ("University of Michigan consumer sentiment", "SENTIMENT", "index", "monthly", ("months", 0, 28)),
    "ICSA": ("Initial jobless claims", "CLAIMS", "count", "weekly", ("days", 5)),
    "CCSA": ("Continuing jobless claims", "CONTINUING", "count", "weekly", ("days", 12)),
}
FRED_KEEP = {"daily": 1260, "weekly": 520, "monthly": 120, "quarterly": 60}
# A rate or a spread changes in points; anything else in percent.
POINTS_UNITS = {"rate", "pct"}


def _months_later(month: str, n: int, day: int) -> str:
    year, m = (int(p) for p in month.split("-"))
    m += n
    year, m = year + (m - 1) // 12, (m - 1) % 12 + 1
    return date(year, m, min(day, 28)).isoformat()


def _available(stamp: pd.Timestamp, lag: tuple) -> str:
    if lag[0] == "days":
        return (stamp + pd.Timedelta(days=lag[1])).strftime("%Y-%m-%d")
    return _months_later(stamp.strftime("%Y-%m"), lag[1], lag[2])


def _series_section(series_id: str, meta: tuple) -> dict:
    label, short, unit, freq, lag = meta
    frame, _ = fred.fetch_series(series_id)
    full = frame.set_index("date")["value"]
    s = full.iloc[-FRED_KEEP[freq]:]
    last, stamp = float(s.iloc[-1]), s.index[-1]
    year_ago = full.asof(stamp - pd.Timedelta(days=364 if freq != "monthly" else 360))
    prior = float(s.iloc[-2]) if len(s) > 1 else None
    if unit in POINTS_UNITS:
        change = None if prior is None else round(last - prior, 3)
        yoy = None if pd.isna(year_ago) else round(last - float(year_ago), 3)
    else:
        change = None if not prior else round((last / prior - 1) * 100, 2)
        yoy = None if pd.isna(year_ago) or not year_ago else round((last / float(year_ago) - 1) * 100, 2)
    published = _published(series_id, freq, s.index[0])
    available, dated = _dated(series_id, s.index, lag, published) if freq != "daily" else ([_available(d, lag) for d in s.index], "market")
    return {"id": series_id, "label": label, "short": short, "unit": unit, "freq": freq,
            "dates": [d.strftime("%Y-%m-%d") for d in s.index], "values": [round(float(v), 3) for v in s],
            "available": available, "dated": dated, "published": published,
            "latest": {"date": stamp.strftime("%Y-%m-%d"), "value": round(last, 3), "change": change, "yoy": yoy,
                       "available": available[-1]}}


def _fred_daily_change(series_id: str, scale: float = 100.0) -> pd.Series:
    frame, _ = fred.fetch_series(series_id)
    return frame.set_index("date")["value"].diff() * scale


# The loan officer survey has no published schedule; its results come out the
# Monday after the FOMC meeting that closes January, April, July and October
# (the July 2026 survey: FOMC 7/29, released Monday 8/3).
SLOOS_MONTHS = (1, 4, 7, 10)


def sloos_expected(catalysts: dict, as_of: date) -> str | None:
    for e in sorted(catalysts.get("events") or [], key=lambda e: e["date"]):
        day = date.fromisoformat(e["date"])
        if e["title"].startswith("FOMC decision") and day.month in SLOOS_MONTHS and day.day >= 20:
            monday = day + timedelta(days=(7 - day.weekday()) % 7 or 7)
            if monday > as_of:
                return monday.isoformat()
    return None


def _banks(spec: dict, excess: pd.DataFrame, as_of: date) -> dict:
    out: dict = {"series": {sid: _section(lambda sid=sid, meta=meta: _series_section(sid, meta)) for sid, meta in BANKS_SERIES.items()}}
    drivers = {"curve": _fred_daily_change("T10Y2Y"), "ten_year": _fred_daily_change("DGS10"), "hy_oas": _fred_daily_change("BAMLH0A0HYM2")}
    out["sensitivity"] = {"drivers": {"curve": "2s10s, per 1bp", "ten_year": "10-year yield, per 1bp", "hy_oas": "HY spread, per 1bp"},
                          "rows": _sensitivities(excess, [spec.get("etf") or ""] + list(spec.get("bellwethers") or []), drivers)}
    out["next"] = {"h8": eia.next_release(as_of, 4).isoformat()}
    return out


def _consumer(spec: dict, excess: pd.DataFrame, as_of: date) -> dict:
    out: dict = {"series": {sid: _section(lambda sid=sid, meta=meta: _series_section(sid, meta)) for sid, meta in CONSUMER_SERIES.items()}}
    futures = _futures_closes()
    drivers = {"ten_year": _fred_daily_change("DGS10"),
               "gasoline": futures["RB=F"].pct_change(fill_method=None) * 100 if "RB=F" in futures.columns else pd.Series(dtype=float),
               "hy_oas": _fred_daily_change("BAMLH0A0HYM2")}
    out["sensitivity"] = {"drivers": {"ten_year": "10-year yield, per 1bp", "gasoline": "RBOB gasoline, per 1%", "hy_oas": "HY spread, per 1bp"},
                          "rows": _sensitivities(excess, [spec.get("etf") or ""] + list(spec.get("bellwethers") or []), drivers)}
    out["next"] = {"claims": eia.next_release(as_of, 3).isoformat()}
    return out


# --- Release-day studies ---------------------------------------------------------
# How each theme's ETF moved beyond the S&P 500 on the session of each release
# of the series that bear on it. Release days and first prints from ALFRED
# (what the release itself said, prior month as known that day); EIA's
# weekly report is dated the Wednesday after the week (a holiday week, a day
# later, is not shifted).
# The surprise is the actual less TradingView's published forecast where its
# calendar has one for most releases (back to 2016 for these lines), else the
# print against its own trend.
# group: [(series, label, headline: 'pct' change | 'diff' change, unit,
#          TradingView line, its surprise: 'diff' | 'pct', the surprise's unit)]
STUDIES = {
    "energy": [("eia:crude_stocks", "EIA crude stocks, weekly change", "diff", "mb", r"^EIA Crude Oil Stocks Change$", "diff", "mbbl")],
    "banks": [("PAYEMS", "Nonfarm payrolls", "diff", "k", r"^Non Farm Payrolls$", "diff", "k"),
              ("CPILFESL", "Core CPI, m/m", "pct", "pct", r"^Core Inflation Rate MoM$", "diff", "pp")],
    "consumer": [("RSAFS", "Retail sales, m/m", "pct", "pct", r"^Retail Sales MoM$", "diff", "pp"),
                 ("ICSA", "Initial jobless claims, w/w", "diff", "count", r"^Initial Jobless Claims$", "diff", "k"),
                 ("PAYEMS", "Nonfarm payrolls", "diff", "k", r"^Non Farm Payrolls$", "diff", "k")],
    "housing": [("HOUST", "Housing starts, m/m", "pct", "pct", r"^Housing Starts$", "pct", "%"),
                ("HSN1F", "New home sales, m/m", "pct", "pct", r"^New Home Sales$", "pct", "%"),
                ("CPILFESL", "Core CPI, m/m", "pct", "pct", r"^Core Inflation Rate MoM$", "diff", "pp")],
}
EIA_RELEASE_LAG = 5


def _study_releases(series: str) -> pd.DataFrame:
    if series.startswith("eia:"):
        s = eia.fetch(series[4:])
        return pd.DataFrame({"date": s.index[1:], "released": s.index[1:] + pd.Timedelta(days=EIA_RELEASE_LAG),
                             "value": s.to_numpy()[1:], "prior": s.to_numpy()[:-1]})
    return alfred.releases(alfred.vintages(series))


def _studies(groups: list[dict], excess: pd.DataFrame, as_of: date) -> dict:
    out: dict = {"keyed": alfred.available()}
    cache_: dict[str, pd.DataFrame] = {}
    try:
        calendar, missing = expectations_source.tradingview_history(excess.index[0].date(), as_of)
        out["forecast_months_missing"] = missing
    except Exception as exc:  # noqa: BLE001 -- the studies fall back to the trend
        calendar, out["forecast_error"] = [], describe_error(exc)[:ERROR_DETAIL_CHARS]
    for g in groups:
        etf = g.get("proxy") if g.get("proxy_is_etf") else None
        if g["key"] not in STUDIES or not etf or etf not in excess.columns:
            continue
        rows = []
        for series, label, headline, unit, tv_title, tv_mode, surprise_unit in STUDIES[g["key"]]:
            if not series.startswith("eia:") and not out["keyed"]:
                rows.append({"series": series, "label": label, "unavailable": "no FRED_API_KEY: ALFRED release days need one"})
                continue
            try:
                if series not in cache_:
                    cache_[series] = _study_releases(series)
                study = T.release_study(cache_[series], excess[etf], headline=headline,
                                        forecasts=T.tv_surprises(calendar, tv_title, tv_mode))
            except Exception as exc:  # noqa: BLE001 -- one study's failure is its own row
                rows.append({"series": series, "label": label, "unavailable": describe_error(exc)[:ERROR_DETAIL_CHARS]})
                continue
            if study:
                rows.append({"series": series, "label": label, "headline": headline, "unit": unit,
                             "surprise_unit": surprise_unit if study["basis"] == "forecast" else unit, **study})
        out[g["key"]] = {"proxy": etf, "rows": rows}
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


def _drivers(cloud: dict, semis: dict, energy: dict | None = None, housing: dict | None = None,
             banks: dict | None = None, consumer: dict | None = None) -> list[dict]:
    """kind 'yoy': the value is a year-on-year change, compared as is; 'level':
    a level, compared as a % change since the report; 'pp': a rate or a gap
    already in percent, compared in points."""
    out = []
    for key, section in ((energy or {}).get("eia") or {}).items():
        if "unavailable" in section:
            continue
        # A week is public the Wednesday (gas: Thursday) after it ends.
        lag = 6 if key == "gas_storage" else 5
        out.append(_driver(f"eia_{key}_vs5y", f"{section['label']}, vs 5-year average", ["energy"], "pp", "pct",
                           [{"period": d, "available": (pd.Timestamp(d) + pd.Timedelta(days=lag)).strftime("%Y-%m-%d"), "value": v}
                            for d, v in zip(section["dates"], [None if a is None or v is None else round((v / a - 1) * 100, 2)
                                                               for v, a in zip(section["value"], section["avg5"])])]))
    for key in ("CL=F", "NG=F", "crack"):
        p = ((energy or {}).get("prices") or {}).get(key)
        if p:
            out.append(_driver(f"px_{key}", p["label"], ["energy"], "level", "usd",
                               [{"period": d, "available": d, "value": v} for d, v in zip(p["dates"], p["values"])]))
    for sid, section in ((housing or {}).get("series") or {}).items():
        if "unavailable" in section:
            continue
        if sid == "MORTGAGE30US":
            out.append(_driver("mortgage30", section["label"], ["housing"], "pp", "rate", _points(section, "pp")))
        elif sid in ("HOUST", "HSN1F", "PERMIT"):
            out.append(_driver(f"fred_{sid.lower()}", f"{section['label'].split(',')[0]}, y/y", ["housing"], "yoy", "pct",
                               _points(section, "yoy")))
    for theme, section, wanted in (("banks", banks, BANK_DRIVERS), ("consumer", consumer, CONSUMER_DRIVERS)):
        for sid, kind in wanted.items():
            series = ((section or {}).get("series") or {}).get(sid)
            if series and "unavailable" not in series:
                out.append(_series_driver(series, [theme], kind))
    gas = (energy or {}).get("retail_gasoline")
    if gas:
        # EIA's Monday survey, public the same afternoon.
        out.append(_driver("retail_gasoline", "US regular gasoline, $/gal", ["consumer"], "level", "usd",
                           [{"period": d, "available": d, "value": v} for d, v in zip(gas["dates"], gas["values"])]))
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
    mem = semis.get("memory_exports") or {}
    if "unavailable" not in mem:
        for series in mem.get("series") or []:
            out.append(_driver(f"kr_{series['code']}", f"Korea {series['label']} exports, y/y", ["semis"], "yoy", "pct",
                               _monthly(series.get("months"), "yoy_pct", PUBLISH_DAY)))
            out.append(_driver(f"kr_{series['code']}_unit", f"Korea {series['label']} export value per kg, y/y", ["semis"], "yoy", "pct",
                               _monthly(series.get("months"), "unit_yoy_pct", PUBLISH_DAY)))
    chips = semis.get("chip_prices") or {}
    if "unavailable" not in chips:
        for series in chips.get("series") or []:
            out.append(_driver(f"bls_{series['id'].lower()}", f"{series['label']}, y/y", ["semis"], "yoy", "pct",
                               _monthly(series.get("months"), "yoy_pct", PUBLISH_DAY)))
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


# Which bank and consumer series reach the event cards, and how they compare:
# 'yoy' turns a level into its change on a year earlier first.
BANK_DRIVERS = {"TOTLL": "yoy", "DPSACBW027SBOG": "yoy", "T10Y2Y": "pp", "BAMLH0A0HYM2": "pp", "DRALACBS": "pp", "DRTSCILM": "pp"}
CONSUMER_DRIVERS = {"RSAFS": "yoy", "PCEC96": "yoy", "TOTALSL": "yoy", "UMCSENT": "level", "ICSA": "level", "PSAVERT": "pp"}
PERIODS_PER_YEAR = {"daily": 252, "weekly": 52, "monthly": 12, "quarterly": 4}


def _points(series: dict, kind: str) -> list[dict]:
    """A series' card points. As first published when ALFRED has them (the
    value the release said, its y/y against the year-earlier figure as known
    that day); otherwise the current vintage, y/y against the revised year."""
    period = (lambda d: d[:7]) if series["freq"] in ("monthly", "quarterly") else (lambda d: d)  # noqa: E731
    values, dates, available = series["values"], series["dates"], series.get("available") or series["dates"]
    if kind == "yoy":
        lag = PERIODS_PER_YEAR[series["freq"]]
        values = [None if i < lag or not values[i - lag] else round((values[i] / values[i - lag] - 1) * 100, 2) for i in range(len(values))]
    pub = series.get("published")
    if pub:
        current = dict(zip(dates, values))
        first = pub["values"]
        if kind == "yoy":
            first = [None if v is None or not y else round((v / y - 1) * 100, 2) for v, y in zip(first, pub["year_ago"])]
        out = []
        for d, a, v in zip(pub["dates"], pub["available"], first):
            point = {"period": period(d), "available": a, "value": v, "as": "published"}
            now = current.get(d)
            # Revised since: a card says so, or a benchmark revision reads as news.
            if v is not None and now is not None and abs(now - v) > max(0.05, abs(v) * 0.005):
                point["revised"] = now
            out.append(point)
        return out
    if series["freq"] == "daily":
        # A daily series is weekly on a card: the count of new releases would be noise.
        keep = list(range(len(dates) - 1, -1, -5))[::-1]
        dates, values, available = [dates[i] for i in keep], [values[i] for i in keep], [available[i] for i in keep]
    return [{"period": period(d), "available": a, "value": v} for d, a, v in zip(dates, available, values)]


def _series_driver(series: dict, themes: list[str], kind: str) -> dict | None:
    label, unit = series["label"], series["unit"]
    if kind == "yoy":
        label, unit = f"{label.split(' (')[0]}, y/y", "pct"
    return _driver(f"fred_{series['id'].lower()}", label, themes, kind, unit, _points(series, kind))


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
        "memory_exports": _section(lambda: _memory_exports(settings, as_of)),
        "chip_prices": _section(lambda: _chip_prices(settings, as_of)),
        "pcpp": _section(lambda: _pcpp(as_of)),
    }
    specs = {g["key"]: g for g in settings["groups"]}
    energy = _section(lambda: _energy(specs.get("energy", {}), excess, as_of))
    housing = _section(lambda: _housing(specs.get("housing", {}), excess, as_of))
    banks = _section(lambda: _banks(specs.get("banks", {}), excess, as_of))
    if "unavailable" not in banks:
        banks["next"]["sloos"] = sloos_expected(catalysts, as_of)
    consumer = _section(lambda: _consumer(specs.get("consumer", {}), excess, as_of))
    studies = _section(lambda: _studies(groups, excess, as_of))
    _data_dates(groups, cloud, semis, as_of, settings)
    _weekly_dates(groups, energy, housing, banks, as_of)
    _log(ctx, cloud, semis)
    _log_more(ctx, energy, housing, banks, consumer)
    _log_studies(ctx, studies)
    for g in groups:
        g["calendar"].sort(key=lambda e: (e["date"], {"data": 0, "macro": 1, "earnings": 2}[e["kind"]]))
    drivers = _section(lambda: _drivers(cloud, semis, energy, housing, banks, consumer))
    # The first prints live on in the drivers; the charts read the current vintage.
    for section in (housing, banks, consumer):
        for series in (section.get("series") or {}).values():
            series.pop("published", None)
    return {"as_of": ctx.as_of, "calendar_days": int(settings.get("calendar_days", 42)), "groups": groups,
            "heatmap": _heatmap(catalysts, as_of, int(settings.get("heatmap_days", 21))),
            "membership": _membership(ctx, settings, excess),
            "member_corr": float(settings.get("member_corr", 0.55)),
            "cloud": cloud, "semis": semis, "energy": energy, "housing": housing, "banks": banks, "consumer": consumer, "studies": studies,
            "drivers": drivers}


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
    for series in (semis.get("memory_exports") or {}).get("series") or []:
        add("semis", f"Korea {series['label']} exports (customs)", series.get("due"))
    for series in (semis.get("chip_prices") or {}).get("series") or []:
        add("semis", series["label"], series.get("due"))


def _weekly_dates(groups: list[dict], energy: dict, housing: dict, banks: dict, as_of: date) -> None:
    """The next weekly release of each, on its group's calendar. The petroleum
    report and jobless claims are already there from the macro calendar."""
    by_key = {g["key"]: g for g in groups}
    items = [("energy", (energy.get("next") or {}).get("gas_storage"), "EIA natural gas storage, 10:30"),
             ("housing", (housing.get("next") or {}).get("mortgage_rate"), "Freddie Mac mortgage rate"),
             ("banks", (banks.get("next") or {}).get("h8"), "Fed H.8 bank loans & deposits, 16:15"),
             ("banks", (banks.get("next") or {}).get("sloos"), "Senior Loan Officer Survey (expected: the Monday after the FOMC)")]
    for key, day, title in items:
        if day and key in by_key:
            by_key[key]["calendar"].append({"date": day, "kind": "data", "title": title, "late": False})


def _log_more(ctx, energy: dict, housing: dict, banks: dict, consumer: dict) -> None:
    failed = [k for k, v in (energy.get("eia") or {}).items() if "unavailable" in v]
    ctx.log.add(SourceRecord(
        "eia_weekly", "EIA weekly petroleum and natural gas storage (history pages)", eia.PAGE_URL,
        None if "unavailable" in energy else max((v["latest"]["date"] for v in (energy.get("eia") or {}).values() if "latest" in v), default=None),
        rows=len(energy.get("eia") or {}) - len(failed), policy="weekly_article",
        status="error" if "unavailable" in energy or len(failed) == len(eia.SERIES) else ("partial" if failed else "ok"),
        error=(energy.get("unavailable") or "; ".join(f"{k}: {energy['eia'][k]['unavailable'][:80]}" for k in failed[:3])) or None))
    series = housing.get("series") or {}
    bad = [k for k, v in series.items() if "unavailable" in v]
    ctx.log.add(SourceRecord(
        "fred_housing", "Housing series (FRED: Freddie Mac, Census, S&P Case-Shiller)", fred.CSV_URL.format(series_id="HOUST"),
        None if "unavailable" in housing else max((v["dates"][-1] for v in series.values() if "dates" in v), default=None),
        rows=len(series) - len(bad), policy="monthly_release",
        status="error" if "unavailable" in housing else ("partial" if bad else "ok"),
        error=housing.get("unavailable") or (", ".join(bad) or None)))
    for source_id, label, section in (
            ("fred_banks", "Bank series (FRED: Fed H.8, Treasury curve, ICE BofA HY OAS, call-report delinquencies, SLOOS)", banks),
            ("fred_consumer", "Consumer series (FRED: Census retail sales, BEA PCE, Fed G.19, UMich sentiment, DOL claims)", consumer)):
        series = section.get("series") or {}
        bad = [k for k, v in series.items() if "unavailable" in v]
        first = next(iter(series), "TOTLL")
        ctx.log.add(SourceRecord(
            source_id, label, fred.CSV_URL.format(series_id=first),
            None if "unavailable" in section else max((v["latest"]["date"] for v in series.values() if "latest" in v), default=None),
            rows=len(series) - len(bad), policy="monthly_release",
            status="error" if "unavailable" in section or (series and len(bad) == len(series)) else ("partial" if bad else "ok"),
            error=section.get("unavailable") or (", ".join(bad) or None)))


def _log_studies(ctx, studies: dict) -> None:
    rows = [r for k, v in studies.items() if isinstance(v, dict) for r in v.get("rows", [])]
    scored = [r for r in rows if r.get("basis") == "forecast"]
    missing = studies.get("forecast_months_missing") or []
    ctx.log.add(SourceRecord(
        "tradingview_forecasts", "Release forecasts and actuals (TradingView economic calendar)", expectations_source.TV_URL,
        max((x["released"] for r in scored for x in r.get("recent", []) if x.get("vs_forecast") is not None), default=None),
        rows=len(scored), policy="weekly_release",
        status="error" if studies.get("forecast_error") or (rows and not scored) else ("partial" if missing else "ok"),
        error=studies.get("forecast_error") or (f"months not answered: {', '.join(missing[:6])}" if missing else None)))
    bad = [r["series"] for r in rows if "unavailable" in r]
    keyed = studies.get("keyed")
    ctx.log.add(SourceRecord(
        "alfred_releases", "Release days and first prints (ALFRED, FRED's vintage archive)", alfred.page_url("RSAFS"),
        None if "unavailable" in studies or not rows else max((r["recent"][0]["released"] for r in rows if r.get("recent")), default=None),
        rows=len(rows) - len(bad), policy="monthly_release",
        status="error" if "unavailable" in studies or not keyed else ("partial" if bad else "ok"),
        error=studies.get("unavailable") or (None if keyed else "no FRED_API_KEY: release days approximated") or (", ".join(bad) or None)))


def _count(items, key: str) -> int:
    """Observations across a section's series: each series' ``key`` list summed."""
    return sum(len(item.get(key) or []) for item in items or [] if isinstance(item, dict))


def _log(ctx, cloud: dict, semis: dict) -> None:
    def record(source_id, label, url, section, observed, policy, rows=0):
        failed = isinstance(section, dict) and "unavailable" in section
        ctx.log.add(SourceRecord(source_id, label, url, None if failed else observed, status="error" if failed else "ok",
                                 error=section["unavailable"][:ERROR_DETAIL_CHARS] if failed else None, policy=policy,
                                 rows=0 if failed else rows))

    capex = cloud["capex"]
    record("sec_capex", "Cloud capex (SEC XBRL 10-Q/10-K)", "https://www.sec.gov/edgar/search/", capex,
           None if "unavailable" in capex else max((c["quarters"][-1]["end"] for c in capex["companies"] if c["quarters"]), default=None),
           "quarterly_filing", _count(capex.get("companies"), "quarters"))
    nv = cloud["nvda"]
    record("sec_releases", "Earnings releases (8-K Ex. 99.1): NVIDIA Data Center, capex guidance", "https://www.sec.gov/edgar/search/", nv,
           None if "unavailable" in nv else nv["quarters"][-1]["filed"], "quarterly_filing", len(nv.get("quarters") or []))
    odm = cloud["odm"]
    record("mops_revenue", "Taiwan monthly revenue (MOPS)", mops.PAGE_URL, odm if isinstance(odm, dict) else {},
           None if isinstance(odm, dict) else max((s["months"][-1]["month"] + "-01" for s in odm if s["months"]), default=None),
           "monthly_release", 0 if isinstance(odm, dict) else _count(odm, "months"))
    orr = cloud["openrouter"]
    record("altdata_openrouter", "OpenRouter tokens & estimated revenue (alternative-data)", altdata.OPENROUTER_URL, orr,
           None if "unavailable" in orr else (orr["dates"][-1] if orr["dates"] else None), "daily_close", len(orr.get("dates") or []))
    ramp = cloud["ramp"]
    record("altdata_ramp", "Ramp AI Index (alternative-data)", altdata.RAMP_URL, ramp,
           None if "unavailable" in ramp else (ramp["months"][-1] + "-01" if ramp["months"] else None), "monthly_release",
           len(ramp.get("months") or []))
    korea = semis["korea"]
    record("korea_customs", "Korea Customs IC exports (HS 8542)", korea_customs.HOME_URL, korea,
           None if "unavailable" in korea else (korea["months"][-1]["month"] + "-01" if korea["months"] else None), "monthly_release",
           len(korea.get("months") or []))
    flash = semis["korea_flash"]
    record("motie_trade", "Korea monthly trade release (MOTIE, 1st of month)", motie.LIST_URL, flash,
           None if "unavailable" in flash else flash["months"][-1]["month"] + "-01", "monthly_release", len(flash.get("months") or []))
    notes = semis["adata"]
    record("adata_market_watch", "ADATA Memory & Flash Market Watch", "https://industrial.adata.com/en/edm", notes,
           None if "unavailable" in notes or not notes["notes"] else notes["notes"][0]["month"] + "-01", "monthly_release",
           len(notes.get("notes") or []))
    mem = semis["memory_exports"]
    mem_failed = isinstance(mem, dict) and "unavailable" in mem
    mem_months = [s["months"][-1]["month"] for s in (mem.get("series") or []) if s.get("months")] if not mem_failed else []
    ctx.log.add(SourceRecord(
        "korea_customs_memory", "Korea Customs memory exports (HS 854232, DRAM, flash)", korea_customs.HOME_URL,
        None if mem_failed or not mem_months else min(mem_months) + "-01",
        rows=0 if mem_failed else _count(mem.get("series"), "months"),
        status="error" if mem_failed else ("partial" if mem.get("failed") else "ok"),
        error=(mem.get("unavailable") if mem_failed else None) or ("; ".join(mem.get("failed") or []) or None),
        policy="monthly_release"))
    chips = semis["chip_prices"]
    chip_failed = isinstance(chips, dict) and "unavailable" in chips
    chip_months = [s["months"][-1]["month"] for s in (chips.get("series") or []) if s.get("months")] if not chip_failed else []
    ctx.log.add(SourceRecord(
        "fred_chip_prices", "BLS semiconductor producer and import prices (FRED)",
        next((series["page"] for series in chips.get("series") or []), "https://fred.stlouisfed.org/"),
        None if chip_failed or not chip_months else min(chip_months) + "-01",
        rows=0 if chip_failed else _count(chips.get("series"), "months"),
        status="error" if chip_failed else ("partial" if chips.get("failed") else "ok"),
        error=(chips.get("unavailable") if chip_failed else None) or ("; ".join(chips.get("failed") or []) or None),
        policy="monthly_release"))
    pc = semis["pcpp"]
    if "skipped" in pc:
        ctx.log.add(SourceRecord("pcpartpicker", "PCPartPicker UK price trends (memory, CPU)", "https://uk.pcpartpicker.com/trends/",
                                 None, status="skipped", error=pc["skipped"], policy="daily_close"))
    else:
        record("pcpartpicker", "PCPartPicker UK price trends (memory, CPU)", "https://uk.pcpartpicker.com/trends/", pc,
               None if "unavailable" in pc else min((r["image_date"] for k in ("memory", "cpu") for r in pc.get(k, {}).get("rows", [])), default=None),
               "daily_close", sum(len((pc.get(k) or {}).get("rows") or []) for k in ("memory", "cpu")))
