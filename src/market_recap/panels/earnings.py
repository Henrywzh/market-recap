"""EARNINGS (a CATALYSTS view): where S&P 500 estimates are going, and the season.

Three blocks, each dated and counted:

- FactSet's own Earnings Insight figures, from its latest articles: growth,
  beat rate, forward P/E against the 10-year average, and the quarter's and
  year's revision against FactSet's history of a typical one.
- A daily bottom-up tracker built here from every member's consensus trend:
  the current quarter, this calendar year and next, over 7 to 90 days, by
  sector, with the names that moved it.
- The reporting season so far, from Nasdaq's calendar: how many reported,
  beat, by how much, and growth against the year-ago EPS captured before
  each report.

The year-ago EPS disappears from Nasdaq once a company reports, so the
captured values are carried between builds in this artifact. Cloud builds
restore them from the published copy; losing it only thins the growth
figure for companies that already reported, and the page says so.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import os

import pandas as pd

from ..compute import catalysts as C
from ..compute import earnings as E
from ..compute.xray import ticker_key
from ..config import ARTIFACT_DIR
from ..sources import estimates, factset, nasdaq
from ..sources.http import FetchError, get_text
from ..util import ERROR_DETAIL_CHARS, SourceRecord

# Days back beyond which a Nasdaq calendar day is treated as settled.
SETTLED_AFTER_DAYS = 3
# How far ahead the calendar is read for year-ago EPS before a report.
CAPTURE_AHEAD_DAYS = 30
SNAPSHOT_FIELDS = (
    "blended_earnings_growth_yoy", "blended_revenue_growth_yoy", "eps_beat_rate", "eps_surprise_pct",
    "revenue_beat_rate", "revenue_surprise_pct", "forward_12m_pe", "forward_12m_pe_10y_avg",
)
HISTORY_QUARTERS = 12


def _universe(ctx) -> dict[str, dict]:
    """Primary-index members with float shares in proportion: weight / price
    on the holdings date. Only ratios are formed from these."""
    frame = ctx.holdings
    when = pd.Timestamp(ctx.holdings_as_of) if ctx.holdings_as_of else None
    out = {}
    for row in frame.drop_duplicates("yahoo_symbol").itertuples():
        symbol = row.yahoo_symbol
        if symbol not in ctx.prices.columns or not row.weight:
            continue
        series = ctx.prices[symbol].dropna()
        if when is not None:
            series = series[series.index <= when]
        if series.empty or series.iloc[-1] <= 0:
            continue
        out[symbol] = {"sector": row.sector, "shares": float(row.weight) / float(series.iloc[-1])}
    return out


def _previous(ctx) -> tuple[dict | None, str | None]:
    """Last build's artifact: the published one on a cloud build."""
    if os.environ.get("MONITOR_PUBLISHED_STATE") == "1":
        url = ctx.config["monitor"]["published_base_url"].rstrip("/") + "/artifacts/earnings.json"
        try:
            payload = json.loads(get_text(url, timeout=20.0, retries=1))
        except FetchError as exc:
            return None, None if exc.not_found else f"previous season ledger unreadable: {exc}"
        except ValueError:
            # Before the first publish the site answers its index page here.
            return None, "no published season ledger yet; year-ago EPS captured from this build on"
        return (payload if isinstance(payload, dict) else None), None
    path = ARTIFACT_DIR / "earnings.json"
    try:
        return json.loads(path.read_text()), None
    except (OSError, ValueError):
        return None, None


def _calendar(dates: list[date], today: date, use_cache: bool) -> tuple[list[dict], list[str]]:
    rows, failed = [], []
    for day in dates:
        kind = "archive" if (today - day).days > SETTLED_AFTER_DAYS else "daily_file"
        try:
            rows += [{**row, "date": day.isoformat()} for row in nasdaq.fetch_earnings(day.isoformat(), use_cache=use_cache, kind=kind)]
        except Exception:
            failed.append(day.isoformat())
    return rows, failed


def _season(ctx, universe: dict, trends: dict, previous: dict | None, today: date, use_cache: bool) -> tuple[dict, list[str]]:
    quarter = E.season_quarter(today)
    label = E.quarter_label(quarter)
    start = date(quarter[0], 3 * quarter[1] - 2, 1) + timedelta(days=31)
    past = C.sessions(start - timedelta(days=1), today)
    ahead = C.sessions(today + timedelta(days=1), today + timedelta(days=CAPTURE_AHEAD_DAYS))
    rows, failed = _calendar(past + ahead, today, use_cache)
    # Nasdaq writes class shares BRK.B, Yahoo BRK-B: match without separators.
    own = {ticker_key(symbol): symbol for symbol in universe}
    rows = [{**row, "symbol": own.get(ticker_key(row["symbol"]), row["symbol"])} for row in rows]

    # Year-ago EPS, captured while it is still published. Nasdaq first (the
    # same vendor basis as its reported actuals), Yahoo's trend as fallback.
    old = ((previous or {}).get("season") or {})
    captured: dict[str, dict] = dict(old.get("captured") or {}) if old.get("quarter") == label else {}
    for row in rows:
        symbol = row["symbol"]
        if symbol in universe and row.get("eps") is None and row.get("last_year_eps") is not None \
                and E.nasdaq_quarter(row.get("fiscal_quarter")) == quarter:
            captured[symbol] = {"year_ago_eps": row["last_year_eps"], "source": "nasdaq", "captured": today.isoformat()}
    for symbol, trend in trends.items():
        period = E.pick_period(trend, ("quarter", *quarter))
        if symbol in universe and symbol not in captured and period and period.get("year_ago_eps") is not None:
            captured[symbol] = {"year_ago_eps": period["year_ago_eps"], "source": "yahoo", "captured": today.isoformat()}

    reports = []
    for row in rows:
        if row.get("eps") is None or row["date"] > today.isoformat():
            continue
        reports.append({**row, "year_ago_eps": (captured.get(row["symbol"]) or {}).get("year_ago_eps")})
    out = E.season(reports, universe, quarter)
    upcoming = [r for r in rows if r["symbol"] in universe and r["date"] > today.isoformat()
                and E.nasdaq_quarter(r.get("fiscal_quarter")) == quarter]
    next_week = set(C.next_sessions(today, 5))
    out.update({
        "first_day": start.isoformat(),
        "upcoming_next_5_sessions": sum(1 for r in upcoming if date.fromisoformat(r["date"]) in next_week),
        "upcoming_known": len({r["symbol"] for r in upcoming}),
        "captured": captured,
        "failed_dates": failed,
    })
    for item in out["latest"]:
        item["sector"] = universe[item["symbol"]]["sector"]
    return out, failed


def _forward_pe(rows: list[dict], insight: list[dict]) -> list[dict]:
    """The S&P 500's forward P/E, weekly: the blog's articles, with the
    Earnings Insight PDF taking a week the PDF covers (it states the figure
    every week; the blog only in season)."""
    points = {r["report_date"]: {"date": r["report_date"], "forward_12m_pe": r["forward_12m_pe"],
                                 "ten_year_average": r.get("forward_12m_pe_10y_avg")}
              for r in rows if r.get("forward_12m_pe") is not None}
    for r in insight:
        day = date.fromisoformat(r["report_date"])
        # The blog's update and the PDF of the same week are one observation.
        for other in [d for d in points if abs((date.fromisoformat(d) - day).days) <= 3]:
            del points[other]
        points[r["report_date"]] = {"date": r["report_date"], "forward_12m_pe": r["forward_12m_pe"],
                                    "ten_year_average": r.get("forward_12m_pe_10y_avg"),
                                    "five_year_average": r.get("forward_12m_pe_5y_avg"),
                                    "trailing_12m_pe": r.get("trailing_12m_pe"), "source": "pdf"}
    return [points[d] for d in sorted(points)]


def _factset(rows: list[dict], insight: list[dict] = ()) -> dict:
    def latest(fields: tuple[str, ...]) -> dict | None:
        found = [r for r in rows if any(r.get(f) is not None for f in fields)]
        return found[-1] if found else None

    def narrative(row: dict | None) -> dict:
        try:
            return json.loads(row.get("narrative_json") or "{}") if row else {}
        except ValueError:
            return {}

    snapshot = latest(SNAPSHOT_FIELDS)
    revisions = [r for r in rows if r.get("quarterly_eps_revision_pct") is not None]
    revision = revisions[-1] if revisions else None
    prior = revisions[-2] if len(revisions) > 1 else None

    # One point per quarter for the charts: the last print FactSet made
    # about that quarter, so a season is read at its end.
    by_quarter: dict[str, dict] = {}
    for row in rows:
        if row.get("eps_beat_rate") is not None or row.get("blended_earnings_growth_yoy") is not None:
            by_quarter[row["reference_quarter"]] = row
    season_history = [
        {"quarter": q, "report_date": r["report_date"], "eps_beat_rate": r.get("eps_beat_rate"),
         "blended_earnings_growth_yoy": r.get("blended_earnings_growth_yoy"),
         "eps_surprise_pct": r.get("eps_surprise_pct")}
        for q, r in sorted(by_quarter.items())[-HISTORY_QUARTERS:]
    ]
    first_revision: dict[str, dict] = {}
    for row in revisions:
        # The early-quarter note ("during the first two months") is the one
        # FactSet compares with its typical history; keep the latest per quarter.
        first_revision[row["reference_quarter"]] = row
    revision_history = [
        {"quarter": q, "report_date": r["report_date"], "quarterly_eps_revision_pct": r["quarterly_eps_revision_pct"],
         "annual_eps_revision_pct": r.get("annual_eps_revision_pct")}
        for q, r in sorted(first_revision.items())[-HISTORY_QUARTERS:]
    ]
    pe = _forward_pe(rows, list(insight))

    def sectors(row: dict | None) -> dict:
        try:
            return json.loads(row.get("sector_revision_json") or "{}") if row else {}
        except ValueError:
            return {}

    def pick(row: dict | None, fields: tuple[str, ...]) -> dict | None:
        if row is None:
            return None
        return {"report_date": row["report_date"], "reference_quarter": row["reference_quarter"],
                "source_url": row["source_url"], **{f: row.get(f) for f in fields}}

    picked = pick(snapshot, SNAPSHOT_FIELDS)
    # The forward P/E tile reads the newest weekly point, which between
    # seasons is the PDF's, not the last in-season article's.
    if picked and pe and pe[-1]["date"] > (picked.get("report_date") or ""):
        picked |= {"forward_12m_pe": pe[-1]["forward_12m_pe"], "forward_12m_pe_10y_avg": pe[-1].get("ten_year_average"),
                   "forward_pe_date": pe[-1]["date"]}
    return {
        "articles": len(rows),
        "first_date": rows[0]["report_date"] if rows else None,
        "newest_date": rows[-1]["report_date"] if rows else None,
        "snapshot": picked,
        "revision": {
            **pick(revision, ("quarterly_eps_revision_pct", "annual_eps_revision_pct")),
            "sectors": sectors(revision),
            "typical": narrative(revision).get("typical") or [],
            "window": narrative(revision).get("window"),
            "prior": pick(prior, ("quarterly_eps_revision_pct", "annual_eps_revision_pct")),
        } if revision else None,
        "season_history": season_history,
        "revision_history": revision_history,
        "forward_pe": pe[-260:],
    }


def build(ctx, *, use_cache: bool = True) -> dict:
    today = date.fromisoformat(ctx.as_of)
    settings = ctx.config.get("earnings") or {}
    universe = _universe(ctx)
    notices: list[str] = []
    previous, problem = _previous(ctx)
    if problem:
        notices.append(problem)

    trends: dict[str, dict] = {}
    if settings.get("estimates", True):
        trends, missing = estimates.fetch_trends(sorted(universe), use_cache=use_cache)
        if len(missing) > 0.5 * max(len(universe), 1):
            notices.append(f"estimates unavailable for {len(missing)} of {len(universe)} members")
    companies = [{"symbol": s, **meta, "trend": trends.get(s)} for s, meta in universe.items()]
    current = E.calendar_quarter(today)
    tracker = {
        "quarter": {"label": E.quarter_label(current), **E.revisions(companies, ("quarter", *current))},
        "year": {"label": f"CY{today.year}", **E.revisions(companies, ("year", today.year))},
        "next_year": {"label": f"CY{today.year + 1}", **E.revisions(companies, ("year", today.year + 1))},
        "members": len(universe),
        "with_estimates": len(trends),
    }

    season, failed = _season(ctx, universe, trends, previous, today, use_cache)
    ctx.log.add(SourceRecord(
        "earnings_season_nasdaq", "Nasdaq earnings calendar, season to date", nasdaq.PAGE_URL,
        rows=season["reported"], observed_date=ctx.as_of, policy="daily_close",
        status="ok" if not failed else "partial",
        error=f"dates not fetched: {', '.join(failed)}" if failed else None,
    ))

    try:
        rows, errors, stats = factset.observations(use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001 - FactSet is optional context
        rows, errors, stats = factset.load_seed(), {"factset": str(exc)[:ERROR_DETAIL_CHARS]}, {}
    ctx.log.add(SourceRecord(
        "factset_insight", "FactSet Earnings Insight (article figures)", factset.TOPIC_URL,
        rows=len(rows), observed_date=rows[-1]["report_date"] if rows else None, policy="weekly_article",
        status="ok" if not errors else "partial",
        error="; ".join(f"{k}: {v}" for k, v in list(errors.items())[:3]) or None,
    ))

    # The weekly PDF from the blog's last forward P/E (at most a year back).
    last_blog = max((r["report_date"] for r in rows if r.get("forward_12m_pe") is not None), default=None)
    since = max(date.fromisoformat(last_blog) - timedelta(days=7) if last_blog else today - timedelta(days=365),
                today - timedelta(days=365))
    try:
        insight, insight_failed = factset.insight_observations(since, today)
    except Exception as exc:  # noqa: BLE001 - optional context
        insight, insight_failed = [], [str(exc)[:ERROR_DETAIL_CHARS]]
    ctx.log.add(SourceRecord(
        "factset_insight_pdf", "FactSet Earnings Insight weekly PDF (forward P/E)",
        factset.PDF_URL.format(stamp="MMDDYY"), rows=len(insight),
        observed_date=insight[-1]["report_date"] if insight else None, policy="weekly_article",
        status="ok" if not insight_failed else "partial",
        error="; ".join(insight_failed[:3]) or None,
    ))

    return {
        "as_of": ctx.as_of,
        "index": ctx.primary.key,
        "holdings_as_of": ctx.holdings_as_of,
        "factset": {**_factset(rows, insight), "collection": stats, "source_url": factset.TOPIC_URL},
        "tracker": tracker,
        "season": season,
        "notices": notices,
        "note": (
            "FactSet figures are read from FactSet's Earnings Insight articles (dated and linked); "
            "FactSet calendarizes and uses its own consensus. The tracker is built here from Yahoo's "
            "consensus trend for every member, weighted by float-adjusted shares (index weight over "
            "price): fiscal periods count toward the calendar period holding most of their months, "
            "without pro-rating, so it will not equal FactSet's number. Season figures use Nasdaq's "
            "calendar (Zacks consensus and actuals); a beat is an actual strictly above that "
            "consensus. Growth compares each reported actual with the year-ago EPS captured before "
            "the report and covers only those companies."
        ),
    }
