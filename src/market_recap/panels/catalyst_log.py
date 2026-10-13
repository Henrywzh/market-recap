"""CALENDAR -> UNSCHEDULED CATALYSTS: what an event moved, and whether estimates followed.

A hand-kept log of dated events no calendar announces (a leak, a competitor's
announcement, a supply report), each with its source and the names the coverage
tied to it. For each event: the exposed names' price since the close before it,
and how far consensus EPS and revenue have moved since the nightly snapshot at
that close. A basket reads as price down / flat / up and estimates down / flat
/ up (the page words the pair); see compute.revisions for what that can and
cannot say. The exposed lists are judgments, and the snapshots start on
2026-10-01: an event before that has prices only.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..compute import revisions as R
from ..context import YAHOO_URL
from ..sources import snapshot_store, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

PATH_DIGITS = 2


def _name_row(name: str, closes: pd.DataFrame, ref: date, as_of: date, table: pd.DataFrame, periods: list[str],
              ref_day: str | None, latest_day: str | None, read_period: str) -> dict:
    series = closes[name].dropna() if name in closes.columns else pd.Series(dtype=float)
    base = R.last_on_or_before(series, ref)
    last = R.last_on_or_before(series, as_of)
    changes = R.estimate_changes(table, name, periods, ref_day, latest_day)
    row: dict = {
        "ticker": name,
        "price_since": to_iso_date(base[0]) if base else None,
        "price_pct": clean_float(R.pct_change(base[1], last[1]), 1) if base and last else None,
        "price_last": to_iso_date(last[0]) if last else None,
        "eps": {p: clean_float(changes[p]["eps"], 2) for p in periods},
        "revenue": {p: clean_float(changes[p]["revenue"], 2) for p in periods},
        "has_estimates": bool(not table.empty and (table["symbol"] == name).any()),
        "counts": None,
    }
    if latest_day is not None:
        sub = table[(table["symbol"] == name) & (table["date"] == latest_day) & (table["period"] == read_period)]
        if not sub.empty:
            r = sub.iloc[0]
            row["counts"] = {k: (None if pd.isna(r[k]) else int(r[k])) for k in ("up_7d", "down_7d", "up_30d", "down_30d", "analysts")}
    return row


def _item(spec: dict, closes: pd.DataFrame, table: pd.DataFrame, as_of: date, cfg: dict) -> dict:
    periods, read = list(cfg["periods"]), cfg["read_period"]
    event_day = date.fromisoformat(str(spec["date"]))
    ref = R.reference_day(event_day, bool(spec.get("after_close")))
    ref_day, latest_day = R.snapshot_days(table, ref)
    exposed = list(spec["exposed"])
    names = [_name_row(n, closes, ref, as_of, table, periods, ref_day, latest_day, read) for n in exposed]

    price = R.summarize([r["price_pct"] for r in names])
    eps = {p: R.summarize([r["eps"][p] for r in names]) for p in periods}
    revenue = {p: R.summarize([r["revenue"][p] for r in names]) for p in periods}
    path = R.basket_path(closes, exposed, ref, end=pd.Timestamp(as_of))
    spy = R.basket_path(closes, ["SPY"], ref, end=pd.Timestamp(as_of))
    enough = eps[read]["n"] >= int(cfg["min_names"])
    return {
        "key": spec["key"], "date": event_day.isoformat(), "title": spec["title"], "kind": spec.get("kind"),
        "detail": spec.get("detail"), "source": spec.get("source"), "url": spec.get("url"),
        "after_close": bool(spec.get("after_close")), "reference": ref.isoformat(), "exposed": exposed,
        "snapshots": {"reference": ref_day, "latest": latest_day,
                      "note": None if ref_day else "No estimate snapshot at or before the event: prices only."},
        "names": names,
        "basket": {
            "price": {k: (clean_float(v, 1) if k == "median" else v) for k, v in price.items()},
            "eps": {p: {k: (clean_float(v, 2) if k == "median" else v) for k, v in eps[p].items()} for p in periods},
            "revenue": {p: {k: (clean_float(v, 2) if k == "median" else v) for k, v in revenue[p].items()} for p in periods},
            "path": None if path.empty else {
                "dates": [d.strftime("%Y-%m-%d") for d in path.index],
                "basket": [clean_float(v, PATH_DIGITS) for v in path],
                "spy": [clean_float(v, PATH_DIGITS) for v in spy.reindex(path.index).ffill()] if not spy.empty else None},
        },
        "state": {"price": R.state(price["median"], float(cfg["price_move_pct"])),
                  "estimates": R.state(eps[read]["median"], float(cfg["revision_pct"])) if enough else None,
                  "read_period": read, "names_with_estimates": eps[read]["n"]},
    }


def build(ctx) -> dict:
    cfg = ctx.config["catalyst_log"]
    as_of = date.fromisoformat(ctx.as_of)
    items = cfg["items"]
    wanted = sorted({s for it in items for s in it["exposed"]} | {"SPY"})
    closes = ctx.closes.join(ctx.etf_closes[[c for c in ("SPY",) if c in ctx.etf_closes.columns and c not in ctx.closes.columns]], how="left")
    missing = [s for s in wanted if s not in closes.columns or closes[s].dropna().empty]
    fetch_error = None
    if missing:
        try:
            extra = yahoo.fetch_closes(missing, period="1y")
            closes = closes.join(extra.reindex(columns=[s for s in missing if s in extra.columns]), how="outer").sort_index()
        except Exception as exc:  # noqa: BLE001 -- those names then have no price, and the page says which
            fetch_error = describe_error(exc)
    closes = closes[closes.index <= pd.Timestamp(as_of)]            # a name fetched here can carry a session the build has not closed
    still = [s for s in wanted if s not in closes.columns or closes[s].dropna().empty]
    ctx.log.add(SourceRecord("catalyst_log_prices", "Closes for the names the catalyst log's events name (index members from the build; others fetched)",
                             YAHOO_URL, to_iso_date(closes.index[-1]) if not closes.empty else None, rows=len(wanted) - len(still),
                             status="ok" if not still else "partial",
                             error=(f"no prices: {', '.join(still)}" + (f"; {fetch_error}" if fetch_error else "")) if still else None))

    first_event = min(date.fromisoformat(str(it["date"])) for it in items) if items else as_of
    table = snapshot_store.consensus_table(first_event - timedelta(days=10), as_of)
    log = [_item(spec, closes, table, as_of, cfg) for spec in sorted(items, key=lambda i: str(i["date"]), reverse=True)]
    days = sorted(table["date"].unique()) if not table.empty else []
    return {
        "as_of": ctx.as_of,
        "settings": {k: cfg[k] for k in ("price_move_pct", "revision_pct", "min_names", "periods", "period_labels", "read_period")},
        "snapshots": {"first": days[0] if days else None, "last": days[-1] if days else None, "days": len(days)},
        "inputs": {"prices_through": to_iso_date(closes.index[-1]) if not closes.empty else None, "no_prices": still},
        "items": log,
        "notes": [
            "A hand-kept log: it holds only the events someone entered, with the source of each. It is not a news feed and not a complete record of what moved a stock.",
            "The exposed names are the ones the coverage tied to the event, a judgment and not a measured exposure.",
            "Estimates are Yahoo's consensus averages, recorded each evening since "
            + (days[0] if days else "the snapshots began")
            + ". They move days to weeks after analysts change their numbers, so 'estimates held' soon after an event is a statement about those days.",
            "Asian listings close before US news breaks: their first reaction to a US report is the next Asian session.",
        ],
    }
