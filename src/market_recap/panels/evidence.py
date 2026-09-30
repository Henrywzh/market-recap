"""Evidence and options layer for NAMES -> TICKER and CATALYSTS -> EARNINGS.

Two reaches, because the sources cost differently:

- every index member: past earnings reactions, from the SEC submissions
  indexes the build already reads (8-K Item 2.02 acceptance times) and the
  members' own closes -- no extra requests;
- focus names (the watchlist, the MONITOR queue and the largest index
  weights): insider transactions (Form 4), short interest and
  rating changes, which cost a request or more per name, and the implied
  move and IV from the options snapshot, which records about 50 names.

Form 4 documents never change and are cached; a build that runs out of its
time budget carries on from the cache next time rather than failing.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import time

import pandas as pd

from ..compute import evidence as V
from ..config import ARTIFACT_DIR
from ..snapshots.options import build_universe as snapshot_universe
from ..sources import nasdaq, ratings, sec, snapshot_store
from ..util import SourceRecord, describe_error
from .financials import cik_for

REACTIONS = 8


def _focus(ctx, settings: dict) -> list[str]:
    """Watchlist, the largest weights, and MONITOR candidates
    chosen by the options snapshot's own rule (reporting soon first, then the
    furthest behind peers, up to ``monitor_max``) so the two universes agree."""
    names = {str(s["ticker"]).upper() for s in ctx.config.get("watchlist") or []}
    try:
        monitor = json.loads((ARTIFACT_DIR / "monitor.json").read_text())
        snapshot_settings = dict(ctx.config.get("snapshots", {}).get("options", {}))
        snapshot_settings["monitor_max"] = int(settings.get("monitor_max", snapshot_settings.get("monitor_max", 15)))
        chosen, _ = snapshot_universe({**snapshot_settings, "fixed": [], "include_watchlist": False}, [],
                                      monitor.get("rows") or [], date.fromisoformat(ctx.as_of))
        names |= set(chosen)
    except (OSError, ValueError):
        pass
    holdings = ctx.holdings
    if not holdings.empty:
        names |= set(holdings.sort_values("weight", ascending=False)["yahoo_symbol"].head(int(settings.get("top_weights", 30))))
    return sorted(names)


def _options(symbol: str, summary_today: pd.DataFrame | None, history: pd.DataFrame, next_session: date | None,
             min_days: int) -> dict | None:
    if summary_today is None or summary_today.empty:
        return None
    rows = summary_today[summary_today["underlying"] == symbol]
    if rows.empty:
        return None
    term = [{"days": int(r.days), "expiry": r.expiry, "atm_iv": None if pd.isna(r.atm_iv) else round(float(r.atm_iv), 4),
             "put_25d_iv": None if pd.isna(r.put_25d_iv) else round(float(r.put_25d_iv), 4),
             "call_25d_iv": None if pd.isna(r.call_25d_iv) else round(float(r.call_25d_iv), 4),
             "straddle_pct": None if pd.isna(r.straddle_pct) else round(float(r.straddle_pct), 2)}
            for r in rows.sort_values("days").itertuples()]
    iv30 = V.constant_maturity_iv(rows)
    series = []
    if not history.empty:
        for day, group in history[history["underlying"] == symbol].groupby("day"):
            value = V.constant_maturity_iv(group)
            if value is not None:
                series.append((day, value))
    percentile = None
    if iv30 is not None and len(series) >= min_days:
        values = [v for _, v in series]
        percentile = round(100 * sum(v <= iv30 for v in values) / len(values))
    return {
        "term": term, "iv30": None if iv30 is None else round(iv30, 4),
        "iv30_history_days": len(series), "iv30_percentile": percentile,
        "implied_move": V.implied_move(rows, next_session) if next_session else None,
    }


def build(ctx) -> dict:
    settings = ctx.config.get("evidence", {})
    as_of = date.fromisoformat(ctx.as_of)
    failed: dict[str, str] = {}
    try:
        cik_map = sec.fetch_ticker_cik_map()
    except Exception as exc:
        raise RuntimeError(f"SEC ticker map: {describe_error(exc)}") from exc

    members = ctx.priced(ctx.primary.key)
    symbols = sorted(set(members["yahoo_symbol"]) | {str(s["ticker"]).upper() for s in ctx.config.get("watchlist") or []})
    index_close = ctx.index_closes[ctx.primary.symbol] if ctx.primary.symbol in ctx.index_closes.columns else pd.Series(dtype=float)
    focus = set(_focus(ctx, settings))

    # Next report per name, from the calendar the monitor reads.
    next_report: dict[str, dict] = {}
    try:
        catalysts = json.loads((ARTIFACT_DIR / "catalysts.json").read_text())
        for e in catalysts.get("events") or []:
            if e.get("event_type") == "earnings" and e.get("symbol") and e.get("date", "") > ctx.as_of:
                next_report.setdefault(e["symbol"], {"date": e["date"], "timing": e.get("timing")})
    except (OSError, ValueError):
        pass

    snapshot = snapshot_store.latest_options_summary(as_of)
    summary_today = snapshot[1] if snapshot else None
    history = snapshot_store.options_summaries(as_of - timedelta(days=400), as_of) if snapshot else pd.DataFrame()
    min_days = int(settings.get("iv_percentile_min_days", 60))

    names: dict[str, dict] = {}
    submissions_missing = 0
    started = time.monotonic()
    budget = float(settings.get("form4_budget_seconds", 300))
    form4_fetched, form4_skipped = 0, 0
    for symbol in symbols:
        cik = cik_for(symbol, cik_map)
        recent = None
        if cik:
            try:
                recent = sec.submissions_recent(cik)
            except Exception:
                submissions_missing += 1
        closes = ctx.closes[symbol] if symbol in ctx.closes.columns else pd.Series(dtype=float)
        six_k = (settings.get("six_k") or {}).get(symbol)
        announcements = (V.six_k_announcements(recent or {}, six_k["pattern"], six_k.get("timing", "bmo"))
                         if six_k else V.earnings_announcements(recent or {}, today=as_of))
        if cik and recent is not None and not six_k and len(announcements) < REACTIONS:
            # A heavy filer's recent block holds one year; read older pages
            # until eight releases are found or three years are covered.
            try:
                block = sec.submissions_until(cik, lambda b: len(V.earnings_announcements(b)) >= REACTIONS + 1,
                                              since=(as_of - timedelta(days=3 * 365)).isoformat())
                announcements = V.earnings_announcements(block, today=as_of)
            except Exception:
                pass
        entry: dict = {"reactions": V.reactions(closes, index_close, announcements, REACTIONS)}
        moves = [abs(r["move_pct"]) for r in entry["reactions"]]
        entry["mean_abs_move"] = round(sum(moves) / len(moves), 2) if moves else None
        upcoming = next_report.get(symbol)
        if upcoming:
            day = date.fromisoformat(upcoming["date"])
            session = day + timedelta(days=1) if upcoming.get("timing") == "amc" else day
            while session.weekday() >= 5:
                session += timedelta(days=1)
            entry["next"] = {**upcoming, "reaction_session": session.isoformat()}
        if symbol in focus:
            entry["focus"] = True
            options = _options(symbol, summary_today, history, date.fromisoformat(entry["next"]["reaction_session"]) if upcoming else None, min_days)
            if options:
                entry["options"] = {**options, "snapshot_day": snapshot[0].isoformat()}
            # Form 4s in the window, newest first, within the build's time budget.
            transactions = []
            strict_buys = []
            form4_expected = 0
            form4_read = 0
            if recent:
                window_start = (as_of - timedelta(days=int(settings.get("insider_window_days", 90)))).isoformat()
                forms = recent.get("form") or []
                for i, form in enumerate(forms):
                    if form != "4" or not window_start <= recent["filingDate"][i] <= ctx.as_of:
                        continue
                    form4_expected += 1
                    if time.monotonic() - started > budget:
                        form4_skipped += 1
                        continue
                    try:
                        xml = sec.fetch_form4(cik, recent["accessionNumber"][i], recent["primaryDocument"][i])
                        form4_fetched += 1
                        form4_read += 1
                    except Exception:
                        form4_skipped += 1
                        continue
                    transactions.extend(V.parse_form4(xml))
                    accession = recent["accessionNumber"][i].replace("-", "")
                    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{recent['primaryDocument'][i]}"
                    strict_buys.extend(V.strict_form4_buys(xml, issuer_cik=cik,
                                                            filed=recent["filingDate"][i], filing_url=url))
            entry["insiders"] = V.insider_summary(transactions, as_of, window_days=int(settings.get("insider_window_days", 90)),
                                                  min_value=float(settings.get("cluster_min_value", 250_000)))
            entry["insiders"]["strict_cluster"] = V.strict_buy_cluster(
                strict_buys, index_close.dropna().index,
                min_value=float(settings.get("cluster_min_value", 250_000))) if recent else None
            # Keep the inspectable filings behind the summary. The 90-day
            # window is bounded; this is not a historical market-wide panel.
            entry["insiders"]["strict_purchases"] = sorted(
                strict_buys, key=lambda r: (r["filed"], r["date"]), reverse=True)[:30]
            entry["insiders"]["form4_coverage"] = {
                "expected": form4_expected if recent else None,
                "read": form4_read,
                "complete": recent is not None and form4_read == form4_expected,
            }
            try:
                entry["short"] = V.short_summary(nasdaq.fetch_short_interest(symbol))
            except Exception as exc:
                failed[f"short interest {symbol}"] = describe_error(exc)
            try:
                entry["ratings"] = V.ratings_summary(ratings.fetch_changes(symbol), as_of)
            except Exception as exc:
                failed[f"ratings {symbol}"] = describe_error(exc)
            entry["evidence_for"], entry["evidence_against"] = V.evidence_lines(
                entry.get("insiders"), entry.get("short"), entry.get("ratings"), settings)
        names[symbol] = entry

    if form4_skipped:
        failed["form 4"] = f"{form4_skipped} filings not read this build (time budget or fetch errors); the cache carries on next build"
    ctx.log.add(SourceRecord("sec_form4", "SEC Form 4 insider transactions (focus names)", "https://www.sec.gov/cgi-bin/browse-edgar?type=4",
                             ctx.as_of, rows=form4_fetched, status="ok" if not form4_skipped else "partial", policy="filings"))
    ctx.log.add(SourceRecord("nasdaq_short_interest", "Nasdaq short interest (FINRA settlement dates, focus names)",
                             "https://www.nasdaq.com", ctx.as_of, rows=sum(1 for n in names.values() if n.get("short")),
                             policy="weekly_release"))
    ctx.log.add(SourceRecord("yahoo_ratings", "Analyst rating changes (Yahoo, focus names)", ratings.HOME_URL, ctx.as_of,
                             rows=sum(1 for n in names.values() if n.get("ratings"))))
    return {
        "as_of": ctx.as_of,
        "focus": sorted(focus),
        "focus_rule": f"watchlist, MONITOR queue and the {int(settings.get('top_weights', 30))} largest index weights",
        "options_snapshot": snapshot[0].isoformat() if snapshot else None,
        "iv_percentile_min_days": min_days,
        "names": names,
        "failed": failed,
    }
