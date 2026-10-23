"""POSITIONING view: who is forced to trade.

Two readings, each from its own public source:

- Trend followers: a rules-based proxy for systematic trend books on the
  S&P 500 and Nasdaq-100 (compute.positioning), with the price at which each
  lookback flips tomorrow.
- Short interest: FINRA's twice-monthly consolidated short interest for the
  index members, the watchlist and the broad ETFs -- days to cover, the
  change since the last round, and the members' total short value over a
  year of rounds.
- Buyback blackout: the share of S&P 500 weight whose issuers are likely in
  their earnings blackout, from each member's report dates. An estimate of a
  convention, not of any company's actual policy.
- Insider buying: strict SEC Form 4 open-market purchases by the members'
  insiders, read from EDGAR's daily index, and clusters of them.
- Trend check: a listed trend-following ETF's equity beta from its daily
  prices, set against the S&P 500 model position.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json
import statistics
import time

import pandas as pd

from .. import cache
from ..compute import evidence as V
from ..compute import positioning as P
from ..compute.blackout import calendar_momentum
from ..sources import finra, sec, yahoo
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, company_name, history_payload, to_iso_date
from .index_put_call import build_component

# Same-session artifacts this panel reads (build.optional_panel).
# The index put/call SPX series also reads RISK's cached Cboe files, but RISK is
# not declared here (loading its artifact would add nothing). A POSITIONING-only
# build uses whatever RISK last cached; missing sessions stay blank.
INPUTS = ("catalysts", "evidence")

# The trend check: a listed trend-following ETF against the factor ETFs whose
# daily returns explain its equity beta (returns only, not its holdings).
CHECK_ETF = "DBMF"
CHECK_FACTORS = ("SPY", "IEF", "UUP", "GLD", "USO")
CHECK_WINDOW = 63
YAHOO_HOME = "https://finance.yahoo.com"


def _round_row(row: dict, digits: int) -> dict:
    return {k: clean_float(v, digits) if isinstance(v, float) else v for k, v in row.items()}


def _model(close: pd.Series, spec, settings) -> dict:
    """The vol-scaled model position, volatility-control exposure and what a price move does to them."""
    years = int(settings.get("history_years", 10))
    position = P.model_position(close)
    vol_control = P.vol_control_exposure(close)
    vol_60 = P.realised_vol(close, P.CTA_VOL_WINDOW).iloc[-1]
    vol_20 = P.realised_vol(close, P.VC_VOL_WINDOW).iloc[-1]
    position_now = float(position.iloc[-1])
    scenarios = []
    for row in P.scenario_flows(close):
        low, high = P.flow_range_bn(row["position_change"], spec.symbol)
        scenarios.append({**_round_row(row, 2), "flow_bn_low": clean_float(low, 2), "flow_bn_high": clean_float(high, 2)})
    notional = P.MAX_NOTIONAL_BN.get(spec.symbol)
    return {
        "position": clean_float(position_now, 1),
        "vol_60d": clean_float(100 * vol_60, 1),
        "vol_20d": clean_float(100 * vol_20, 1),
        "leverage": clean_float(min(P.TARGET_VOL / vol_60, P.LEVERAGE_CAP), 2),
        "vol_control": clean_float(vol_control.iloc[-1], 1),
        "room": {k: clean_float(v, 1) for k, v in P.room(position_now).items()},
        "scenarios": scenarios,
        "flow_assumption_bn": list(notional) if notional else None,
        "history": {
            "position": history_payload(position, years=years, digits=1),
            "vol_control": history_payload(vol_control, years=years, digits=1),
        },
    }


def _trend(ctx, spec, settings) -> dict | None:
    close = ctx.index_closes[spec.symbol].dropna() if spec.symbol in ctx.index_closes else pd.Series(dtype=float)
    if len(close) < max(P.LOOKBACKS.values()) + 2:
        return None
    score = P.trend_score(close)
    now = float(score.iloc[-1])
    scorecard_start = close.index[-1] - pd.DateOffset(years=int(settings.get("history_years", 10)))
    scorecard_close = close[close.index > scorecard_start]
    scorecard_score = score.reindex(scorecard_close.index)
    return {
        "key": spec.key, "label": spec.label, "symbol": spec.symbol,
        "as_of": to_iso_date(close.index[-1]),
        "close": clean_float(close.iloc[-1], 2),
        "score": clean_float(now, 2),
        "state": P.label(now),
        "flips": [{k: (clean_float(v, 2) if isinstance(v, float) else v) for k, v in row.items()} for row in P.flip_levels(close)],
        "averages": [{k: (clean_float(v, 2) if isinstance(v, float) else v) for k, v in row.items()} for row in P.ma_levels(close)],
        "history": {
            "score": history_payload(score, years=int(settings.get("history_years", 10)), digits=2),
            "close": history_payload(close, years=int(settings.get("history_years", 10)), digits=2),
        },
        # Chart history above intentionally thins older observations to
        # weekly. Forward outcomes need actual consecutive trading sessions.
        "scorecard_history": {
            "dates": [d.strftime("%Y-%m-%d") for d in scorecard_close.index],
            "score": [clean_float(v, 2) for v in scorecard_score],
            "close": [clean_float(v, 2) for v in scorecard_close],
        },
        "model": _model(close, spec, settings),
    }


def _trend_check(ctx, settings) -> dict:
    """The listed trend ETF's equity beta from daily prices, beside the S&P 500 model position."""
    years = int(settings.get("history_years", 10))
    symbols = [CHECK_ETF, *CHECK_FACTORS]
    label = "Yahoo daily closes: a listed trend-following ETF and its factor ETFs"
    try:
        prices = yahoo.fetch_closes(symbols, period=f"{years}y")
        missing = [s for s in symbols if s not in prices.columns or prices[s].dropna().empty]
        if missing:
            raise ValueError(f"no Yahoo closes for {', '.join(missing)}")
    except Exception as exc:
        ctx.log.add(SourceRecord("trend_check_prices", label, YAHOO_HOME, status="error",
                                 error=str(exc)[:ERROR_DETAIL_CHARS]))
        return {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
    ctx.log.add(SourceRecord("trend_check_prices", label, YAHOO_HOME, to_iso_date(prices.index[-1]),
                             rows=int(prices.shape[0])))
    returns = prices.sort_index().pct_change(fill_method=None)
    beta = P.implied_equity_beta(returns[CHECK_ETF], returns[list(CHECK_FACTORS)], window=CHECK_WINDOW)
    if beta.empty:
        return {"unavailable": f"fewer than {CHECK_WINDOW} sessions with prices for every series"}
    if ctx.primary.symbol not in ctx.index_closes:
        return {"unavailable": f"no {ctx.primary.label} closes to compare with"}
    close = ctx.index_closes[ctx.primary.symbol].dropna()
    position = P.model_position(close)
    return {
        "etf": CHECK_ETF, "window": CHECK_WINDOW,
        "dates": [d.strftime("%Y-%m-%d") for d in beta.index],
        "beta": [clean_float(v, 3) for v in beta],
        "position": [clean_float(v, 1) for v in position.reindex(beta.index)],
        "as_of": to_iso_date(beta.index[-1]),
        "beta_now": clean_float(beta.iloc[-1], 2),
        # The beta is itself a 63-session regression, so only changes a full
        # window apart are independent; shorter ones are mostly overlap.
        "corr_levels": clean_float(P.level_correlation(beta, position), 2),
        "corr_with_model": clean_float(P.change_correlation(beta, position, step=CHECK_WINDOW, min_samples=12), 2),
    }


def _universe(ctx, settings) -> tuple[dict[str, dict], list[str]]:
    """FINRA symbol -> {ticker, name, group}; members first, then the ETFs."""
    names: dict[str, dict] = {}
    for spec in ctx.indices:
        for row in ctx.priced(spec.key).itertuples():
            entry = names.setdefault(finra.finra_symbol(row.yahoo_symbol), {
                "ticker": row.yahoo_symbol, "name": company_name(row.name), "sector": getattr(row, "sector", None),
                "indices": [],
            })
            entry["indices"].append(spec.key)
    for row in (ctx.watchlist.itertuples() if not ctx.watchlist.empty and "ticker" in ctx.watchlist else []):
        names.setdefault(finra.finra_symbol(str(row.ticker)), {"ticker": str(row.ticker), "name": None, "sector": None, "indices": ["watchlist"]})
    etfs = [str(t) for t in settings.get("short_interest_etfs", [])]
    for ticker in etfs:
        names.setdefault(finra.finra_symbol(ticker), {"ticker": ticker, "name": None, "sector": "ETF", "indices": ["etf"]})
    return names, etfs


def _price_on(frame: pd.DataFrame, ticker: str, day: pd.Timestamp) -> float | None:
    if ticker not in frame.columns:
        return None
    series = frame[ticker].dropna()
    series = series[series.index <= day]
    return float(series.iloc[-1]) if not series.empty else None


def _short_interest(ctx, settings) -> dict:
    names, etfs = _universe(ctx, settings)
    rounds = int(settings.get("short_interest_rounds", 24))
    until = date.fromisoformat(ctx.as_of) if ctx.as_of else date.today()
    frames = []
    for nominal in finra.candidate_dates(until, rounds + 1):
        frame = finra.fetch_round(nominal, sorted(names))
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise ValueError("FINRA returned no short-interest round")
    data = pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "settlement_date"], keep="first")
    data = data[data["symbol"].isin(names)]
    dates = sorted(data["settlement_date"].unique())[-rounds:]
    data = data[data["settlement_date"].isin(dates)]
    latest_day = dates[-1]
    prices = pd.concat([ctx.closes, ctx.etf_closes], axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]

    def row(r) -> dict:
        info = names[r.symbol]
        price = _price_on(prices, info["ticker"], r.settlement_date)
        return {
            "ticker": info["ticker"], "name": info["name"], "sector": info["sector"], "indices": info["indices"],
            "shares_short": clean_float(r.shares_short, 0),
            "change_pct": clean_float(r.change_pct, 2),
            "days_to_cover": clean_float(r.days_to_cover, 2),
            "short_value": clean_float(r.shares_short * price, 0) if price else None,
            "average_daily_volume": clean_float(r.average_daily_volume, 0),
        }

    latest = [row(r) for r in data[data["settlement_date"] == latest_day].itertuples()]
    members = [r for r in latest if "etf" not in r["indices"] and "watchlist" not in r["indices"]]
    # Each member's short shares over the rounds shown, for the table's sparkline.
    history = data.pivot_table(index="settlement_date", columns="symbol", values="shares_short", aggfunc="last")
    spark = {names[s]["ticker"]: [clean_float(v, 0) for v in history[s].to_numpy()] for s in history.columns}

    # The members' total short value per round, priced at each settlement date's close.
    spx = {finra.finra_symbol(t) for t in ctx.symbols_for(ctx.primary.key)}
    aggregate = []
    for day in dates:
        rows = data[(data["settlement_date"] == day) & data["symbol"].isin(spx)]
        value = sum((r.shares_short * p) for r in rows.itertuples()
                    if (p := _price_on(prices, names[r.symbol]["ticker"], day)))
        aggregate.append({
            "date": to_iso_date(day),
            "short_value_bn": clean_float(value / 1e9, 1),
            "median_days_to_cover": clean_float(rows["days_to_cover"].median(), 2),
            "names": int(len(rows)),
        })

    top = int(settings.get("short_interest_top", 15))
    by = lambda key, reverse=True: sorted((r for r in members if r[key] is not None), key=lambda r: r[key], reverse=reverse)[:top]
    return {
        "settlement_date": to_iso_date(latest_day),
        "previous_settlement_date": to_iso_date(dates[-2]) if len(dates) > 1 else None,
        "rounds": [to_iso_date(d) for d in dates],
        "aggregate": aggregate,
        "etfs": sorted((r for r in latest if r["ticker"] in etfs), key=lambda r: etfs.index(r["ticker"])),
        "most_days_to_cover": by("days_to_cover"),
        "biggest_increase": by("change_pct"),
        "biggest_decrease": by("change_pct", reverse=False),
        "watchlist": [r for r in latest if "watchlist" in r["indices"]],
        "spark": {r["ticker"]: spark.get(r["ticker"]) for group in (by("days_to_cover"), by("change_pct"), by("change_pct", False)) for r in group}
                 | {t: spark.get(t) for t in etfs},
        "covered": len(latest),
    }


def _report_dates(symbol: str, catalysts: dict | None, evidence: dict | None) -> tuple[list[date], bool]:
    """A member's known report dates, and whether its next one is scheduled."""
    past = [date.fromisoformat(r["date"][:10]) for r in ((evidence or {}).get("names", {}).get(symbol, {}).get("reactions") or [])
            if r.get("date")]
    upcoming = [date.fromisoformat(e["date"]) for e in ((catalysts or {}).get("events") or [])
                if e.get("event_type") == "earnings" and e.get("symbol") == symbol and e.get("date")]
    return sorted(set(past + upcoming)), bool(upcoming)


def _blackout(ctx, settings, catalysts, evidence) -> dict:
    """Share of S&P 500 weight likely inside an earnings buyback blackout.

    Convention, not policy: a window opens ``before`` calendar days ahead of
    each report and closes ``after`` days behind it. Where a member's next
    report is not yet on the calendar it is projected from its own median
    gap between reports, and the page draws that stretch as projected.
    """
    before = int(settings.get("blackout_days_before", 30))
    after = int(settings.get("blackout_days_after", 2))
    back = int(settings.get("blackout_history_days", 365))
    ahead = int(settings.get("blackout_days_ahead", 60))
    as_of = date.fromisoformat(ctx.as_of)
    members = ctx.priced(ctx.primary.key)
    windows, scheduled, projected, missing, total = [], 0, 0, 0, 0.0
    for row in members.itertuples():
        weight = float(row.weight or 0)
        total += weight
        dates, has_next = _report_dates(row.yahoo_symbol, catalysts, evidence)
        if not dates:
            missing += 1
            continue
        if has_next:
            scheduled += 1
        elif len(dates) >= 2:
            gap = statistics.median((b - a).days for a, b in zip(dates, dates[1:]))
            nxt = dates[-1] + timedelta(days=int(min(max(gap, 80), 100)))
            while nxt < as_of:
                nxt += timedelta(days=int(min(max(gap, 80), 100)))
            dates.append(nxt)
            projected += 1
        windows.append((weight, [(d - timedelta(days=before), d + timedelta(days=after)) for d in dates]))
    days = [as_of + timedelta(days=n) for n in range(-back, ahead + 1)]
    share = []
    for day in days:
        inside = sum(w for w, spans in windows if any(a <= day <= b for a, b in spans))
        share.append(round(100 * inside / total, 1) if total else None)
    series = pd.Series(share, index=pd.to_datetime(days))
    now = clean_float(series.loc[pd.Timestamp(as_of)], 1)
    future = series[series.index > pd.Timestamp(as_of)]
    peak_day = future.idxmax() if future.notna().any() else None
    return {
        "as_of": ctx.as_of, "before_days": before, "after_days": after,
        "dates": [d.isoformat() for d in days], "share_pct": share,
        "now_pct": now,
        "peak_pct": clean_float(future.max(), 1) if peak_day is not None else None,
        "peak_date": to_iso_date(peak_day),
        "members": int(len(members)), "scheduled": scheduled, "projected": projected, "missing": missing,
        "weight_covered_pct": clean_float(100 * sum(w for w, _ in windows) / total, 1) if total else None,
        "momentum": calendar_momentum([d.isoformat() for d in days], share, ctx.as_of,
                                      settings.get("blackout_change_calendar_days", [])),
    }


def _filing_link(path: str, cik: int) -> str:
    accession = path.rsplit("/", 1)[-1].removesuffix(".txt")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"


def _insiders(ctx, settings) -> dict:
    """Strict Form 4 purchases by members' insiders over the window, read from
    EDGAR's daily index newest day first. Each filing's parse is kept for
    good, so a build reads only what is new, within a filing and time budget;
    coverage says how much of the window has been read so far."""
    window = int(settings.get("insider_window_days", 90))
    max_new = int(settings.get("insider_max_new_filings", 1500))
    budget = float(settings.get("insider_budget_seconds", 420))
    min_value = float(settings.get("insider_cluster_min_value", 250_000))
    as_of = date.fromisoformat(ctx.as_of)
    cik_map = sec.fetch_ticker_cik_map()
    weights = {r.yahoo_symbol: float(r.weight or 0) for r in ctx.priced(ctx.primary.key).itertuples()}
    members: dict[int, dict] = {}
    for spec in ctx.indices:
        for row in ctx.priced(spec.key).itertuples():
            cik = cik_map.get(row.yahoo_symbol.upper()) or cik_map.get(row.yahoo_symbol.upper().replace("-", "."))
            if cik:
                members.setdefault(cik, {"ticker": row.yahoo_symbol, "name": company_name(row.name),
                                         "sector": getattr(row, "sector", None), "spx_weight": weights.get(row.yahoo_symbol)})
    started, fetched = time.monotonic(), 0
    buys: dict[int, list[dict]] = defaultdict(list)
    days_seen = days_complete = expected = read = 0
    read_through, contiguous = None, True
    for n in range(window + 1):
        day = as_of - timedelta(days=n)
        if day.weekday() >= 5:
            continue
        try:
            rows = sec.daily_form_index(day)
        except Exception:
            continue
        if rows is None:
            continue
        days_seen += 1
        filings = {r["path"]: r for r in rows if r["cik"] in members}
        complete = True
        for path, r in filings.items():
            expected += 1
            name = f"{r['cik']}-{path.rsplit('/', 1)[-1].removesuffix('.txt')}"
            target = cache.path_for(f"{sec.NAMESPACE}/form4-strict", name, ".json")
            if not cache.is_fresh(target, "archive") and (fetched >= max_new or time.monotonic() - started > budget):
                complete = False
                continue

            def parse(path=path, r=r) -> str:
                xml = sec.ownership_xml(path)
                return json.dumps(V.strict_form4_buys(xml, issuer_cik=r["cik"], filed=r["filed"],
                                                      filing_url=_filing_link(path, r["cik"])) if xml else [])

            try:
                if not cache.is_fresh(target, "archive"):
                    fetched += 1
                parsed = json.loads(cache.fetch_text(f"{sec.NAMESPACE}/form4-strict", name, parse, kind="archive", suffix=".json"))
            except Exception:
                complete = False
                continue
            read += 1
            buys[r["cik"]].extend(parsed)
        if complete:
            days_complete += 1
        # The oldest day back to which every filing day has been read in full.
        contiguous = contiguous and complete
        if contiguous:
            read_through = day.isoformat()
    sessions = ctx.index_closes[ctx.primary.symbol].dropna().index
    clusters, purchases = [], []
    for cik, rows in buys.items():
        info = members[cik]
        rows = [t for t in rows if t.get("date") and t["date"] <= ctx.as_of]
        for t in rows:
            purchases.append({**info, **t})
        cluster = V.strict_buy_cluster(rows, sessions, min_value=min_value)
        if cluster:
            clusters.append({**info, **cluster})
    clusters.sort(key=lambda c: (c["available"], c["value"]), reverse=True)
    recent_cut = (as_of - timedelta(days=int(settings.get("insider_recent_days", 30)))).isoformat()
    largest = sorted((p for p in purchases if p["filed"] >= recent_cut), key=lambda p: p["value"], reverse=True)
    # Weeks older than the read-through day are only partly read; drawing them
    # would show missing filings as quiet weeks.
    weekly: dict[str, dict] = {}
    for p in (purchases if read_through is None else [p for p in purchases if p["filed"] >= read_through]):
        week = (date.fromisoformat(p["filed"]) - timedelta(days=date.fromisoformat(p["filed"]).weekday())).isoformat()
        entry = weekly.setdefault(week, {"week": week, "value": 0.0, "companies": set()})
        entry["value"] += p["value"]
        entry["companies"].add(p["ticker"])
    return {
        "window_days": window,
        "clusters": clusters,
        "largest": largest[: int(settings.get("insider_top", 20))],
        "weekly": [{"week": w["week"], "value": round(w["value"], 0), "companies": len(w["companies"])}
                   for w in sorted(weekly.values(), key=lambda w: w["week"])],
        "coverage": {"members": len(members), "days": days_seen, "days_complete": days_complete,
                     "complete": days_complete == days_seen and days_seen > 0,
                     "read_through": read_through, "filings_expected": expected, "filings_read": read,
                     "fetched_this_build": fetched},
    }


def build(ctx, *, inputs: dict | None = None) -> dict:
    inputs = inputs or {}
    settings = dict(ctx.config.get("positioning", {}))
    trends = [t for spec in ctx.indices if (t := _trend(ctx, spec, settings))]
    try:
        shorts = _short_interest(ctx, settings)
        ctx.log.add(SourceRecord("finra_short_interest", "FINRA consolidated short interest", finra.HOME_URL,
                                 shorts["settlement_date"], rows=shorts["covered"], policy="biweekly_release"))
    except Exception as exc:
        shorts = {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
        ctx.log.add(SourceRecord("finra_short_interest", "FINRA consolidated short interest", finra.HOME_URL,
                                 status="error", error=str(exc)[:ERROR_DETAIL_CHARS]))
    try:
        blackout = _blackout(ctx, settings, inputs.get("catalysts"), inputs.get("evidence"))
    except Exception as exc:
        blackout = {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
    try:
        trend_check = _trend_check(ctx, settings) if trends else None
    except Exception as exc:
        trend_check = {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
    try:
        insiders = _insiders(ctx, settings)
        cover = insiders["coverage"]
        ctx.log.add(SourceRecord("sec_form4_daily", "SEC Form 4 filings for index members (EDGAR daily index)",
                                 "https://www.sec.gov/Archives/edgar/daily-index/", ctx.as_of, rows=cover["filings_read"],
                                 policy="filings", status="ok" if cover["complete"] else "partial",
                                 error=None if cover["complete"] else
                                 f"{cover['days_complete']} of {cover['days']} days fully read; the rest fill in on later builds"))
    except Exception as exc:
        insiders = {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
        ctx.log.add(SourceRecord("sec_form4_daily", "SEC Form 4 filings for index members (EDGAR daily index)",
                                 "https://www.sec.gov/Archives/edgar/daily-index/", status="error",
                                 error=str(exc)[:ERROR_DETAIL_CHARS]))
    return {
        "as_of": ctx.as_of,
        "trend": trends,
        "trend_check": trend_check,
        "short_interest": shorts,
        "blackout": blackout,
        "insiders": insiders,
        "lookbacks": P.LOOKBACKS,
        "index_put_call": build_component(ctx.as_of, settings["index_put_call"], ctx.log) if settings.get("index_put_call") else None,
    }

