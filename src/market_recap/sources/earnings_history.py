"""Past earnings reports of any listed company, in any market: when, and
against what consensus.

Two Yahoo answers, joined:

- the earnings-calendar archive (the visualization API yfinance's
  ``get_earnings_dates`` reads): every report back to about 2010 with its
  time of day, the EPS consensus and the surprise. It stopped taking new rows
  in mid-2025, so it is kept a year at a time as an archive.
- quoteSummary's ``earnings`` and ``calendarEvents`` modules: the last four
  quarters, each with the day it was reported, the fiscal period and the
  surprise; and the next report date.

Between them one quarter (the reports of July-September 2025) is missing for
a company whose reports come from nowhere else; it stays missing rather than
being filled in. A US filer's report day and timing come from its SEC
releases instead (EVIDENCE), when they are known.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pandas as pd

from .. import cache

NAMESPACE = "earnings-history"
ARCHIVE_ROWS = 100
PAGE_URL = "https://finance.yahoo.com/calendar/earnings?symbol={symbol}"


def _archive_fetch(symbol: str) -> str:
    import yfinance as yf

    frame = yf.Ticker(symbol).get_earnings_dates(limit=ARCHIVE_ROWS)
    rows = []
    if frame is not None and not frame.empty:
        for ts, row in frame.iterrows():
            rows.append({"ts": pd.Timestamp(ts).tz_convert("UTC").isoformat(), "local": pd.Timestamp(ts).isoformat(),
                         "type": row.get("Event Type"),
                         "eps_estimate": None if pd.isna(row.get("EPS Estimate")) else float(row["EPS Estimate"]),
                         "eps": None if pd.isna(row.get("Reported EPS")) else float(row["Reported EPS"]),
                         "surprise_pct": None if pd.isna(row.get("Surprise(%)")) else float(row["Surprise(%)"])})
    return json.dumps({"symbol": symbol, "rows": rows})


def _recent_fetch(symbol: str) -> str:
    import yfinance as yf

    payload = yf.Ticker(symbol)._quote._fetch(["earnings", "calendarEvents"])
    if not payload:
        raise RuntimeError("empty quoteSummary answer")
    return json.dumps(payload)


def _raw(node):
    if isinstance(node, dict):
        node = node.get("raw")
    return node if isinstance(node, (int, float)) and not isinstance(node, bool) else None


def _day(node) -> str | None:
    """A date Yahoo gives either as {"raw": epoch, "fmt": ...} or a bare epoch."""
    stamp = _raw(node)
    return None if stamp is None else datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()


def parse_archive(text: str) -> list[dict]:
    """Reports only (not shareholder meetings), oldest first: {ts (UTC),
    local (exchange time), timed (a clock time was given), eps,
    eps_estimate, surprise_pct}. A company the archive lists only by its
    results calls (Schneider, Siemens Energy: no EPS consensus) is read from
    its calls instead."""
    rows = json.loads(text).get("rows") or []
    kind = "Earnings" if any(r.get("type") == "Earnings" for r in rows) else "Call"
    out = []
    for r in rows:
        if r.get("type") != kind:
            continue
        local = pd.Timestamp(r["local"])
        out.append({"ts": r["ts"], "local": r["local"], "timed": not (local.hour == 0 and local.minute == 0),
                     "eps": r.get("eps"), "eps_estimate": r.get("eps_estimate"), "surprise_pct": r.get("surprise_pct"),
                     "source": "yahoo_archive"})
    return sorted(out, key=lambda r: r["ts"])


def parse_recent(text: str) -> tuple[list[dict], dict | None]:
    """(the last four reports, the next report) from the quoteSummary answer."""
    try:
        result = json.loads(text)["quoteSummary"]["result"][0]
    except (KeyError, IndexError, TypeError, ValueError):
        return [], None
    reports = []
    for q in ((result.get("earnings") or {}).get("earningsChart") or {}).get("quarterly") or []:
        stamp = _raw(q.get("reportedDate"))
        if stamp is None:
            continue
        ts = datetime.fromtimestamp(stamp, tz=timezone.utc)
        surprise = q.get("surprisePct")
        try:
            surprise = float(surprise) if surprise not in (None, "") else None
        except (TypeError, ValueError):
            surprise = None
        reports.append({"ts": ts.isoformat(), "local": None,
                        # A day with no clock time comes back as midnight UTC.
                        "timed": not (ts.hour == 0 and ts.minute == 0),
                        "eps": _raw(q.get("actual")), "eps_estimate": _raw(q.get("estimate")), "surprise_pct": surprise,
                        "period_end": _day(q.get("periodEndDate")), "fiscal_quarter": q.get("fiscalQuarter"),
                        "source": "yahoo_recent"})
    upcoming = None
    dates = ((result.get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate") or []
    stamps = [_raw(d) for d in dates if _raw(d) is not None]
    if stamps:
        first = datetime.fromtimestamp(min(stamps), tz=timezone.utc)
        upcoming = {"ts": first.isoformat(), "estimated": bool(((result.get("calendarEvents") or {}).get("earnings") or {}).get("isEarningsDateEstimate")),
                    "range": len(stamps) > 1}
    return sorted(reports, key=lambda r: r["ts"]), upcoming


def history(symbol: str, *, use_cache: bool = True) -> tuple[list[dict], dict | None, list[str]]:
    """Every known report, oldest first, the next one, and what failed.

    Reports within four days of each other are one report: the archive and
    the recent quarters overlap, and the recent row (which knows its fiscal
    period) wins."""
    errors = []
    archive, recent, upcoming = [], [], None
    safe = symbol.replace("/", "_")
    try:
        archive = parse_archive(cache.fetch_text(NAMESPACE, f"archive-{safe}", lambda: _archive_fetch(symbol),
                                                 kind="archive", suffix=".json", use_cache=use_cache))
    except Exception as exc:  # noqa: BLE001 - one source short is a gap, not a failure
        errors.append(f"archive: {type(exc).__name__}: {str(exc)[:120]}")
    try:
        recent, upcoming = parse_recent(cache.fetch_text(NAMESPACE, f"recent-{safe}", lambda: _recent_fetch(symbol),
                                                         kind="daily_file", suffix=".json", use_cache=use_cache))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"recent: {type(exc).__name__}: {str(exc)[:120]}")
    return merge(archive, recent), upcoming, errors


def merge(archive: list[dict], recent: list[dict], *, days: int = 4) -> list[dict]:
    out = list(recent)
    for row in archive:
        ts = pd.Timestamp(row["ts"])
        if not any(abs((pd.Timestamp(r["ts"]) - ts).days) <= days for r in recent):
            out.append(row)
    return sorted(out, key=lambda r: r["ts"])
