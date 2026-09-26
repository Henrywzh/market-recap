"""PRICED PATH: what the rates and event markets expect, and how that moved.

The policy path is computed here from fed funds futures (compute.priced),
beside Kalshi's and Polymarket's own prices for the same meetings; where they
disagree by more than the configured gap the page says so rather than
averaging. The longer path comes from three-month SOFR futures. Release
distributions are every open Kalshi ladder in the configured series, whatever
its date: pricing is not hidden behind the calendar's event window.

Yahoo serves daily history for fed funds futures but only the latest quote
for SOFR futures, so the SOFR path a week and a month ago is read from the
snapshot branch once it has that much history.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..compute import expectations as E
from ..compute import priced as P
from ..snapshots.expectations import fed_funds_symbols, sofr_symbols
from ..sources import calendars, fred, futures, snapshot_store
from ..sources import expectations as X
from ..util import SourceRecord, describe_error, to_iso_date

LAGS = {"today": 0, "1 week ago": 7, "1 month ago": 30}
ANCHORS = {
    "EFFR": ("Effective fed funds rate", "pct"),
    "DFEDTARL": ("Target range, lower", "pct"),
    "DFEDTARU": ("Target range, upper", "pct"),
    "T5YIE": ("5Y breakeven inflation", "pct"),
    "T10YIE": ("10Y breakeven inflation", "pct"),
    "T5YIFR": ("5Y5Y forward inflation", "pct"),
    "DFII5": ("5Y real yield", "pct"),
    "DFII10": ("10Y real yield", "pct"),
    "GDPNOW": ("Atlanta Fed GDPNow, current quarter", "pct"),
}
RELEASE_KEYS = ("cpi_yoy", "core_cpi_yoy", "cpi_mom", "core_cpi_mom", "core_pce_mom", "nfp", "unrate", "claims", "gdp")


def _meetings(as_of: date, kalshi_events: list[dict]) -> tuple[list[date], dict[str, str]]:
    """FOMC decision dates: the Fed's calendar, then Kalshi's for meetings the
    Fed has not listed yet. Returns the dates and each one's source."""
    source: dict[str, str] = {}
    try:
        for event in calendars.fetch_fed():
            if (event.get("title") or "").strip() == "FOMC Meeting" and event.get("date"):
                source[event["date"]] = "Federal Reserve calendar"
    except Exception:
        pass
    last_fed = max(source) if source else None
    for event in kalshi_events:
        closes = sorted(str(m.get("close_time"))[:10] for m in event.get("markets") or [] if m.get("close_time"))
        if closes and (last_fed is None or closes[0] > last_fed):
            source.setdefault(closes[0], "Kalshi contract close (not yet on the Fed calendar)")
    days = sorted(date.fromisoformat(d) for d in source if date.fromisoformat(d) > as_of - timedelta(days=40))
    return days, source


def _zq_history(as_of: date, months: int) -> tuple[pd.DataFrame, list[str]]:
    """Daily closes of the fed funds contracts, one column per contract month.

    Contracts are listed from 40 days before the page's session so that the
    path a month ago can be rebuilt from the contracts that were front then.
    """
    start = as_of - timedelta(days=40)
    columns, missing = {}, []
    for symbol, month in fed_funds_symbols(start.replace(day=1), months + 2):
        series = futures.fetch_history(symbol)
        if series.empty:
            missing.append(symbol)
            continue
        columns[month] = series
    frame = pd.DataFrame(columns).sort_index()
    frame = frame[frame.index <= pd.Timestamp(as_of)]
    return frame, missing


def build(ctx) -> dict:
    settings = ctx.config.get("priced", {})
    as_of = date.fromisoformat(ctx.as_of)
    failed: dict[str, str] = {}

    anchors: dict[str, pd.Series] = {}
    for series_id in ANCHORS:
        try:
            frame, _ = fred.fetch_series(series_id)
            anchors[series_id] = frame.set_index("date")["value"]
        except Exception as exc:
            failed[f"fred {series_id}"] = describe_error(exc)

    kalshi: dict[str, list[dict]] = {}
    for series in ["KXFEDDECISION"] + sorted({E.CATALOG[k]["kalshi"]["series"] for k in RELEASE_KEYS}):
        try:
            kalshi[series] = X.fetch_kalshi(series)
        except Exception as exc:
            failed[f"kalshi {series}"] = describe_error(exc)
    try:
        polymarket = X.fetch_polymarket()
    except Exception as exc:
        polymarket, failed["polymarket"] = [], describe_error(exc)

    meetings, meeting_source = _meetings(as_of, kalshi.get("KXFEDDECISION", []))
    history, missing = _zq_history(as_of, int(settings.get("fed_funds_months", 13)))
    # An expired contract has no quote; only a live one missing is a gap.
    live_missing = [sym for sym, month in fed_funds_symbols(as_of, int(settings.get("fed_funds_months", 13))) if sym in missing]
    if live_missing:
        failed["yahoo fed funds futures"] = f"no history for {', '.join(live_missing[:6])}"
    effr = anchors.get("EFFR", pd.Series(dtype=float))
    lower = P.rate_on(anchors.get("DFEDTARL", pd.Series(dtype=float)), pd.Timestamp(as_of))
    upper = P.rate_on(anchors.get("DFEDTARU", pd.Series(dtype=float)), pd.Timestamp(as_of))

    # --- policy path, today and lagged -------------------------------------------
    paths = {}
    last_session = history.index[-1] if not history.empty else pd.Timestamp(as_of)
    for label, lag in LAGS.items():
        day = last_session - timedelta(days=lag)
        start = P.rate_on(effr, day)
        upcoming = [m for m in meetings if pd.Timestamp(m) > day]
        if start is None or history.empty:
            paths[label] = {"date": day.strftime("%Y-%m-%d"), "meetings": []}
            continue
        paths[label] = {"date": day.strftime("%Y-%m-%d"), "start_rate": start,
                        "meetings": P.policy_path(P.prices_on(history, day), upcoming, start)}

    kalshi_by_date = {}
    for event in kalshi.get("KXFEDDECISION", []):
        reading = P.kalshi_meeting(event)
        if reading and reading["date"]:
            kalshi_by_date[reading["date"]] = reading
    gap_bp = float(settings.get("disagreement_bp", 10))
    rows = []
    for meeting in paths["today"]["meetings"]:
        step = P.step_probabilities(meeting["change_bp"])
        k = kalshi_by_date.get(meeting["date"])
        poly = E.pick_polymarket(meeting["date"], polymarket) if polymarket else None
        lagged = {label: next((m for m in paths[label]["meetings"] if m["date"] == meeting["date"]), None)
                  for label in LAGS if label != "today"}
        futures_p_hike = step["p_next_step"] if step["direction"] == "hike" and step["whole_steps"] == 0 else (
            1.0 if step["direction"] == "hike" else 0.0)
        rows.append({
            **meeting,
            "source": meeting_source.get(meeting["date"]),
            "step": step,
            "futures_p_hike": round(futures_p_hike, 3),
            "ranges": P.two_nearest(meeting["cumulative_bp"], lower, upper) if lower is not None and upper is not None else [],
            # The expected rate after this meeting, then and now. Cumulative
            # changes are not comparable across dates: a meeting in between
            # moves the rate they start from.
            "change_1w_bp": round((meeting["post"] - lagged["1 week ago"]["post"]) * 100, 1) if lagged["1 week ago"] else None,
            "change_1m_bp": round((meeting["post"] - lagged["1 month ago"]["post"]) * 100, 1) if lagged["1 month ago"] else None,
            "kalshi": k,
            "polymarket": poly,
            "disagree": bool(k and abs(k["expected_bp"] - meeting["change_bp"]) > gap_bp),
        })

    # --- next-meeting pricing through time ----------------------------------------
    trace = P.next_meeting_history(history, effr, meetings)

    # --- SOFR path ------------------------------------------------------------------
    sofr_today = []
    for symbol, quarter in sofr_symbols(as_of, int(settings.get("sofr_quarters", 8))):
        series = futures.fetch_history(symbol, range_="5d")
        if not series.empty:
            sofr_today.append({"quarter": quarter, "contract": symbol, "rate": round(100 - float(series.iloc[-1]), 4)})
    sofr = {"today": {"date": as_of.isoformat(), "points": sofr_today}}
    for label, lag in LAGS.items():
        if lag == 0:
            continue
        run = snapshot_store.expectation_run_on_or_before(as_of - timedelta(days=lag))
        if run is None:
            sofr[label] = None
            continue
        rows_sofr = run[run["series"] == "sofr_3m"]
        sofr[label] = {
            "date": str(rows_sofr["fetched_at"].iloc[0])[:10] if not rows_sofr.empty else None,
            "points": [{"contract": r.contract, "rate": round(100 - float(r.price), 4)}
                       for r in rows_sofr.itertuples() if pd.notna(r.price)],
        }

    # --- release distributions ------------------------------------------------------------
    releases = []
    for key in RELEASE_KEYS:
        spec = E.CATALOG[key]["kalshi"]
        catalog = E.CATALOG[key]
        for event in kalshi.get(spec["series"], []):
            release = E.kalshi_close(event)
            if release is None or release < as_of.isoformat():
                continue
            loose = {name: value for name, value in spec.items() if name != "quarter"}
            if not E.kalshi_fits(event, loose, release):
                continue
            quote = E.kalshi_quote(event, spec)
            if quote:
                releases.append({"key": key, "label": catalog.get("label"), "unit": catalog.get("unit"),
                                 "release": release, **quote})
    releases.sort(key=lambda r: (r["release"], r["key"]))
    per_key: dict[str, int] = {}
    kept = []
    for r in releases:
        per_key[r["key"]] = per_key.get(r["key"], 0) + 1
        if per_key[r["key"]] <= int(settings.get("releases_per_series", 2)):
            kept.append(r)

    anchor_rows = []
    for series_id, (label, unit) in ANCHORS.items():
        series = anchors.get(series_id)
        if series is None or series.dropna().empty:
            continue
        clean = series.dropna()
        last = clean.index[-1]
        # GDPNow is one reading per quarter on FRED; a week-on-week change of it is meaningless.
        quarterly = series_id == "GDPNOW"
        week = None if quarterly else P.rate_on(clean, last - timedelta(days=7))
        month = None if quarterly else P.rate_on(clean, last - timedelta(days=30))
        anchor_rows.append({
            "key": series_id, "label": label, "unit": unit, "value": round(float(clean.iloc[-1]), 3),
            "date": last.strftime("%Y-%m-%d"),
            "change_1w": round(float(clean.iloc[-1]) - week, 3) if week is not None else None,
            "change_1m": round(float(clean.iloc[-1]) - month, 3) if month is not None else None,
        })

    ctx.log.add(SourceRecord("yahoo_fed_funds", "Fed funds futures daily closes (Yahoo, delayed)",
                             "https://finance.yahoo.com", to_iso_date(last_session), rows=history.shape[1],
                             status="ok" if not missing else "partial"))
    ctx.log.add(SourceRecord("kalshi_priced", "Kalshi Fed decision and release markets", "https://kalshi.com",
                             ctx.as_of, rows=sum(len(v) for v in kalshi.values()),
                             status="ok" if not any(k.startswith("kalshi") for k in failed) else "partial",
                             policy="daily_close"))

    return {
        "as_of": ctx.as_of,
        "target": {"lower": lower, "upper": upper, "effr": P.rate_on(effr, pd.Timestamp(as_of))},
        "meetings": rows,
        "paths": {label: {"date": p["date"], "points": [{"date": m["date"], "post": m["post"], "cumulative_bp": m["cumulative_bp"]}
                                                          for m in p["meetings"]]} for label, p in paths.items()},
        "next_meeting_trace": [{"date": r.date.strftime("%Y-%m-%d"), "meeting": r.meeting, "change_bp": r.change_bp}
                               for r in trace.itertuples()] if not trace.empty else [],
        "sofr": sofr,
        "releases": kept,
        "anchors": anchor_rows,
        "disagreement_bp": gap_bp,
        "snapshots": {"available": snapshot_store.available()},
        "failed": failed,
    }
