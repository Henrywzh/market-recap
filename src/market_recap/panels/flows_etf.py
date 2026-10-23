"""FLOWS · ETF creations and redemptions (section A of the FLOWS tab).

Each fund's daily flow is the change in its issuer's published share count,
priced at that day's NAV. The issuer files come through heatmaps' provider chain
(State Street, then BlackRock, then Invesco's nightly record), so the heat map
and this page read the same history and share the same stale-count rule.
"""

from __future__ import annotations

import pandas as pd

from ..compute import etf_flows as F
from ..panels import heatmaps as H
from ..snapshots.risk import INVESCO_RECORDED
from ..sources import vanguard, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

# Issuer files are dated to the trading day and published after the close, so
# the page's session can run a day ahead of a fund's own latest date.
# Below the stale threshold, an issuer count that has not moved for this many
# sessions is still worth saying out loud on the fund's row.
LAGGING_SHARE_SESSIONS = 5
# An issuer file more than this many calendar days behind the page's session is named as behind.
BEHIND_DAYS = 3

LAG_NOTE = ("Each fund's as-of date is its issuer's last published date, which can differ from "
            "the page's session by a day. The lag between a session and its publication is not measured.")


def _fetch(ticker: str, errors: list) -> dict | None:
    """The first provider that publishes this fund's share history, or None.

    A fund a provider does not cover is a normal miss. Anything else (a
    challenge page, a timeout, a malformed file) is recorded as an error and
    the next provider is tried; it is never worked around.
    """
    for provider_id, label, fetch, home in H.FLOW_PROVIDERS:
        try:
            frame, url = fetch(ticker, use_cache=True)
        except Exception as exc:
            if not getattr(exc, "not_found", False):
                errors.append((ticker, provider_id, describe_error(exc)))
            continue
        if frame is not None and not frame.empty and "shares_outstanding" in frame:
            return {"frame": frame, "provider_id": provider_id, "label": label, "home": home, "url": url}
    return None


def _empty_row(ticker: str, label: str, group: str, error: str | None) -> dict:
    note = ("the issuer's file could not be read this build" if error
            else "Invesco publishes only today's count; it is recorded each evening and a flow appears "
                 "once two days are on record" if ticker in INVESCO_RECORDED
            else "no issuer share-count history on the providers this page reads")
    return {
        "ticker": ticker, "label": label, "group": group, "source": None, "source_id": None,
        "as_of": None, "history_start": None, "sessions": 0, "aum": None,
        "flow_1d": None, "flow_1w": None, "flow_1m": None, "flow_3m": None,
        "flow_1m_pct_aum": None, "pct_rank_1w": None, "stale": False,
        "shares_unchanged_since": None, "note": note,
    }


def _fund_row(ticker: str, label: str, group: str, got: dict, sessions, cut_days_back: pd.DateOffset,
              excluded: list, session: pd.Timestamp) -> tuple[dict, pd.Series]:
    frame = got["frame"].drop_duplicates("date", keep="last").set_index("date").sort_index()
    shares = pd.to_numeric(frame["shares_outstanding"], errors="coerce")
    nav = pd.to_numeric(frame["nav"], errors="coerce")
    flow = F.daily_flow(shares, nav, sessions=sessions)

    for stamp, reason in F.excluded_days(shares, nav, sessions=sessions):
        if stamp >= frame.index[-1] - cut_days_back:
            excluded.append({"ticker": ticker, "date": to_iso_date(stamp), "reason": reason})

    # Latest assets: the issuer's total net assets where it publishes them,
    # else NAV times units -- the same quantity, as the heat map sizes funds.
    latest = frame.dropna(subset=["nav", "shares_outstanding"]).iloc[-1]
    aum = latest["total_net_assets"] if "total_net_assets" in frame and pd.notna(latest.get("total_net_assets")) \
        else latest["nav"] * latest["shares_outstanding"]

    summary = F.fund_summary(flow, aum=aum)
    last_change, unchanged = H._unchanged_run(shares)
    stale = unchanged >= H.STALE_SHARE_SESSIONS
    # A window that lies wholly inside an unchanged share count is unknown, not zero.
    windows = H._mask_unchanged(
        {period: summary[f"flow_{period.lower()}"] for period in F.WINDOW_SESSIONS},
        list(F.WINDOW_SESSIONS), last_change, unchanged, frame.index[-1],
    )
    month_pct = clean_float(windows["1M"] / summary["aum"], 6) if windows["1M"] is not None and summary["aum"] else None
    rank = summary["pct_rank_1w"] if windows["1W"] is not None else None

    notes = []
    if got["provider_id"] == "invesco_recorded":
        notes.append(f"Invesco publishes only today's count; flow recorded nightly since {to_iso_date(frame.index[0])}")
    if summary["pct_rank_1w"] is None and frame.index[0] > frame.index[-1] - pd.DateOffset(years=1):
        notes.append(f"history from {to_iso_date(frame.index[0])}; no percentile before a year")
    if stale:
        notes.append(f"share count unchanged since {to_iso_date(last_change)}; windows inside that stretch are blank")
    elif unchanged >= LAGGING_SHARE_SESSIONS:
        notes.append(f"share count unchanged for {unchanged} sessions; the issuer may be lagging, so recent flows may read low")
    if frame.index[-1] < session - pd.Timedelta(days=BEHIND_DAYS):
        notes.append(f"last published {to_iso_date(frame.index[-1])}, behind this page's session")

    row = {
        "ticker": ticker, "label": label, "group": group, "source": got["label"], "source_id": got["provider_id"],
        "as_of": to_iso_date(frame.index[-1]), "history_start": to_iso_date(frame.index[0]),
        "sessions": int(len(frame)), "aum": summary["aum"],
        "flow_1d": windows["1D"], "flow_1w": windows["1W"], "flow_1m": windows["1M"], "flow_3m": windows["3M"],
        "flow_1m_pct_aum": month_pct, "pct_rank_1w": rank,
        "stale": bool(stale), "shares_unchanged_since": to_iso_date(last_change) if stale else None,
        "note": " · ".join(notes) or None,
    }
    return row, flow


def _not_covered(ctx, inputs: dict) -> list[dict]:
    """The large funds this page cannot measure, with their assets where a
    publisher states them: Vanguard's month-end share-class figure (the heat
    map's own size for VOO and VTI), Yahoo's total assets for the rest."""
    heat = {e["ticker"]: e for e in ((inputs or {}).get("heatmaps") or {}).get("etfs") or []}
    others = [t for t, _, _, reason in F.NOT_COVERED if reason != F.VANGUARD and t not in heat]
    try:
        snapshot = yahoo.fetch_fund_snapshot(others) if others else pd.DataFrame()
        sizes = snapshot.set_index("ticker")["aum"].to_dict() if not snapshot.empty else {}
    except Exception:
        sizes = {}
    out = []
    for ticker, label, group, reason in F.NOT_COVERED:
        aum, basis = None, None
        if ticker in heat and heat[ticker].get("aum"):
            aum, basis = heat[ticker]["aum"], heat[ticker].get("aum_source")
        elif reason == F.VANGUARD:
            try:
                aum, _ = vanguard.fetch_share_class_assets(ticker)
                basis = "vanguard_share_class" if aum else None
            except Exception:
                aum = None
        elif sizes.get(ticker):
            aum, basis = sizes[ticker], "yahoo_total_assets"
        out.append({"ticker": ticker, "label": label, "group": group, "reason": reason,
                    "aum": clean_float(aum), "aum_basis": basis})
    return out


def _coverage(funds: list[str], aum: dict, missing: list[dict]) -> dict:
    """How much of a group's money the total measures: the assets of the funds
    in its latest week against those plus the funds it leaves out -- its own
    funds without a current record (a fund recorded nightly that is behind or
    not yet recorded) and the large funds it cannot read. Approximate: the
    missing funds' assets are month-end or a vendor's figure, or unknown."""
    covered = sum(aum.get(t) or 0 for t in funds)
    absent = sum(n["aum"] or 0 for n in missing)
    return {
        "covered_aum": clean_float(covered, 0) if covered else None,
        "missing_aum": clean_float(absent, 0) if absent else None,
        "pct": clean_float(100 * covered / (covered + absent), 0) if covered else None,
        "missing": [n["ticker"] for n in missing],
    }


def build(ctx, inputs: dict) -> dict:
    """The ETF flow section. Unavailable only when no fund's share history could be read at all."""
    sessions = ctx.etf_closes.index if not ctx.etf_closes.empty else None
    errors: list = []
    rows: list[dict] = []
    flows: dict[str, pd.Series] = {}
    excluded: list[dict] = []
    providers: dict[str, dict] = {}
    cut = pd.DateOffset(years=F.HISTORY_YEARS)

    for ticker, label, group in F.FUNDS:
        got = _fetch(ticker, errors)
        if got is None:
            rows.append(_empty_row(ticker, label, group, next((e for e in errors if e[0] == ticker), None)))
            continue
        row, flow = _fund_row(ticker, label, group, got, sessions, cut, excluded, pd.Timestamp(ctx.as_of))
        rows.append(row)
        flows[ticker] = flow
        seen = providers.setdefault(got["provider_id"], {"label": got["label"], "home": got["home"], "rows": 0, "as_of": []})
        seen["rows"] += 1
        seen["as_of"].append(row["as_of"])

    for provider_id, info in providers.items():
        ctx.log.add(SourceRecord(
            f"flows_etf_{provider_id}", f"{info['label']} (NAV + shares outstanding, ETF flows)", info["home"],
            max(info["as_of"]), rows=info["rows"], policy="fund_holdings",
        ))
    if errors:
        ctx.log.add(SourceRecord(
            "flows_etf_errors", "ETF share-count files that could not be read", "", None,
            rows=len({e[0] for e in errors}), policy="fund_holdings",
            status="partial" if flows else "error",
            error="; ".join(f"{t} via {p}: {msg}" for t, p, msg in errors)[:300],
        ))
    if not flows:
        ctx.log.add(SourceRecord(
            "flows_etf", "ETF share-count history", "", None, status="error",
            error="no issuer share-count file was found for any fund on the providers this page reads",
            policy="fund_holdings",
        ))
        return {"unavailable": "no ETF share-count history could be read this build"}

    not_covered = _not_covered(ctx, inputs)
    aum = {r["ticker"]: r["aum"] for r in rows}
    group_of = {t: g for t, _, g in F.FUNDS}
    aggregates = []
    for name, members in F.AGGREGATES:
        total = F.aggregate({t: flows[t] for t in members if t in flows})
        groups = set(F.US_EQUITY_GROUPS) if name == "US equity" else {group_of[t] for t in members}
        aggregates.append({"name": name, "members": list(members), **total,
                           "coverage": _coverage(total["latest_funds"], aum,
                                                 [{"ticker": t, "aum": aum.get(t)} for t in members
                                                  if t not in total["latest_funds"]]
                                                 + [n for n in not_covered if n["group"] in groups])})
    us = next(a for a in aggregates if a["name"] == "US equity")

    sectors = [
        {"ticker": r["ticker"], "label": r["label"], "flow_1m": r["flow_1m"], "flow_1m_pct_aum": r["flow_1m_pct_aum"]}
        for r in rows if r["group"] == "Sectors"
    ]
    sectors.sort(key=lambda s: (s["flow_1m_pct_aum"] is None, -(s["flow_1m_pct_aum"] or 0)))

    # Only funds current to the headline's date: a stale record's week is another week.
    weekly = [(r["ticker"], r["flow_1w"]) for r in rows
              if r["flow_1w"] is not None and r["as_of"] == us["latest_date"]]
    top_in = sorted([x for x in weekly if x[1] > 0], key=lambda x: -x[1])[:3]
    top_out = sorted([x for x in weekly if x[1] < 0], key=lambda x: x[1])[:3]
    headline = {
        "date": us["latest_date"],
        "us_equity_1d": us["latest"].get("flow_1d"),
        "us_equity_1w": us["latest"].get("flow_1w"),
        "us_equity_1w_pct_rank": us["latest"].get("pct_rank_1w"),
        "top_in": [[t, clean_float(v, 0)] for t, v in top_in],
        "top_out": [[t, clean_float(v, 0)] for t, v in top_out],
    }

    starts = [r["history_start"] for r in rows if r["source_id"] == "invesco_recorded" and r["history_start"]]
    return {
        "as_of": ctx.as_of,
        "headline": headline,
        "funds": rows,
        "aggregates": aggregates,
        "sectors": sectors,
        "not_covered": not_covered,
        "excluded_days": sorted(excluded, key=lambda e: (e["date"], e["ticker"])),
        "invesco_recorded_since": min(starts) if starts else None,
        "lag": LAG_NOTE,
    }
