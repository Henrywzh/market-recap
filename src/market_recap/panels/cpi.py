"""CPI release, official contribution and descriptive persistence, not nowcasts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re

import pandas as pd

from .. import cache
from ..compute import cpi as C
from ..compute import expectations as E
from ..sources import cpi as bls, expectations, fred
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float


def _history(series: pd.Series, years: int) -> dict:
    # Unlike the general price helper, keep null monthly points. Otherwise
    # a line connects across a cancelled release / an incomplete 3M window.
    if series.empty:
        return {"dates": [], "values": []}
    full = series.reindex(pd.date_range(series.index.min(), series.index.max(), freq="MS"))
    full = full.loc[full.index >= full.index.max() - pd.DateOffset(years=years)]
    return {"dates": full.index.strftime("%Y-%m-%d").tolist(),
            "values": [clean_float(v, 4) for v in full]}


def _series(spec: dict) -> tuple[dict, pd.Series | None, str | None]:
    try:
        frame, _ = fred.fetch_series(spec["series_id"])
        return spec, frame.set_index("date")["value"].sort_index(), None
    except Exception as exc:
        return spec, None, str(exc)[:ERROR_DETAIL_CHARS]


def release_comparison(release: dict, calendar: list[dict]) -> list[dict]:
    """Exact date, reference month and series join; never borrow a forecast."""
    day = release["published_at"][:10]
    rows = []
    for key, category in (("cpi", "All items"), ("core_cpi", "All items less food and energy")):
        for basis in ("mom", "yoy"):
            metric = f"{key}_{basis}"
            spec = E.CATALOG[metric]
            matches = [r for r in calendar if r.get("country") == "US" and str(r.get("date", ""))[:10] == day
                       and str(r.get("referenceDate", ""))[:7] == release["month"]
                       and re.search(spec["tv"], r.get("title", ""), re.I)]
            # Duplicate/ambiguous source records are a gap, not first-row-wins.
            raw = matches[0] if len(matches) == 1 else {}
            actual = release["rows"][category][basis]
            forecast = clean_float(raw.get("forecast"), 4)
            rows.append({"key": metric, "label": ("Headline" if key == "cpi" else "Core"),
                         "basis": "MoM SA" if basis == "mom" else "YoY NSA",
                         "actual": actual, "consensus": forecast,
                         "surprise_pp": clean_float(actual - forecast, 4) if forecast is not None else None,
                         "previous": clean_float(raw.get("previous"), 4),
                         "previous_basis": "Calendar previous; may include revisions",
                         "previous_mom_bls": release["rows"][category]["previous_mom"] if basis == "mom" else None,
                         "consensus_provenance": "retrospective calendar; not a frozen pre-release snapshot",
                         "source_url": "https://www.tradingview.com/economic-calendar/"})
    return rows


def unavailable(ctx, source_id: str, label: str, url: str, exc: Exception) -> dict:
    """The named gap for a release panel that could not build, whatever the cause.

    Shared with ppi.py. A source record from an earlier step of the same failed
    build is replaced, so the footer never lists one source as both ok and error.
    """
    reason = str(exc)[:ERROR_DETAIL_CHARS]
    ctx.log.sources[:] = [r for r in ctx.log.sources if r.source_id != source_id]
    ctx.log.add(SourceRecord(source_id, label, url, status="error", error=reason, policy="monthly_release"))
    return {"status": "unavailable", "reason": reason}


def build(ctx) -> dict:
    # build() runs inside macro.build, and a macro failure publishes no
    # macro.json at all, so no release-side surprise may escape it.
    try:
        return _build(ctx)
    except Exception as exc:
        return unavailable(ctx, "bls_cpi", "BLS CPI release", bls.LATEST_URL, exc)


def _build(ctx) -> dict:
    config = ctx.config["macro"]["cpi"]
    years = config["history_years"]
    release = bls.fetch_release()
    ctx.log.add(SourceRecord("bls_cpi", "BLS CPI release and official effects", release["source_url"],
                             release["month"] + "-01", rows=len(release["rows"]), policy="monthly_release"))
    published = datetime.fromisoformat(release["published_at"])
    try:
        calendar = expectations.fetch_tradingview(published.date(), published.date())
        consensus_note = None
        path = cache.path_for(expectations.NAMESPACE,
                              f"tradingview-{published.date()}-{published.date()}", ".json")
        fetched = cache.modified(path)
        consensus_retrieved = fetched.isoformat() if fetched else None
    except Exception as exc:
        calendar, consensus_retrieved = [], None
        consensus_note = str(exc)[:ERROR_DETAIL_CHARS]
    comparisons = release_comparison(release, calendar)
    ctx.log.add(SourceRecord("cpi_consensus", "TradingView CPI calendar forecast (retrospective)",
                             "https://www.tradingview.com/economic-calendar/", published.date().isoformat(),
                             rows=sum(r["consensus"] is not None for r in comparisons),
                             status="partial" if any(r["consensus"] is None for r in comparisons) else "ok",
                             error=consensus_note, policy="monthly_release"))

    failed, components, persistence = {}, [], []
    series_book = {}
    specs = config["components"] + config["persistence"]
    # Bounded concurrency, sharing the same FRED cache as all existing panels.
    with ThreadPoolExecutor(max_workers=3) as pool:
        for spec, series, error in pool.map(_series, specs):
            if series is None or series.empty:
                failed[spec["series_id"]] = error or "empty series"
                ctx.log.add(SourceRecord(f"cpi_fred_{spec['series_id'].lower()}", spec["label"],
                                         f"https://fred.stlouisfed.org/series/{spec['series_id']}",
                                         status="error", error=failed[spec["series_id"]], policy="monthly_release"))
                continue
            # No future observation relative to the official release month.
            series = series.loc[series.index <= pd.Timestamp(release["month"] + "-01")]
            if series.empty:
                failed[spec["series_id"]] = "no observations through release month"
                continue
            series_book[spec["key"]] = series
            ctx.log.add(SourceRecord(f"cpi_fred_{spec['series_id'].lower()}", spec["label"],
                                     f"https://fred.stlouisfed.org/series/{spec['series_id']}",
                                     series.index[-1].date().isoformat(), rows=len(series), policy="monthly_release"))

    for spec in config["components"]:
        official = release["rows"].get(spec["bls"], {})
        series = series_book.get(spec["key"])
        row = {**spec, **official, "history": {"observations": []},
               "consensus": None, "surprise_effect_pp": None,
               "source_url": release["source_url"], "month": release["month"]}
        if not official:
            failed[spec["bls"]] = "category absent from BLS release"
        if series is not None:
            # Retain a full trailing baseline but only ship the displayed years.
            start = pd.Timestamp(release["month"]) - pd.DateOffset(years=2 * years)
            row["history"] = C.component_history(series.loc[series.index >= start], years=years,
                                                  minimum=config["percentile_min_months"])
            cutoff = (pd.Timestamp(release["month"]) - pd.DateOffset(years=years)).strftime("%Y-%m")
            row["history"]["observations"] = [r for r in row["history"]["observations"] if r["month"] >= cutoff]
        components.append(row)

    core = series_book.get("core")
    for months in (3, 6):
        series = C.annualized(core, months) if core is not None else pd.Series(dtype=float)
        latest = series.reindex([pd.Timestamp(release["month"])]).iloc[0]
        persistence.append({"key": f"core_{months}m", "label": f"Core CPI · {months}M annualized",
                            "unit": f"{months}M ann. %", "value": clean_float(latest, 4),
                            "latest_month": release["month"], "status": "ok" if pd.notna(latest) else "pending",
                            "history": _history(series, years),
                            "source_url": f"https://fred.stlouisfed.org/series/{next(s['series_id'] for s in config['components'] if s['key'] == 'core')}"})
    for spec in config["persistence"]:
        series = series_book.get(spec["key"])
        latest_month = series.index[-1].strftime("%Y-%m") if series is not None else None
        matched = latest_month == release["month"]
        persistence.append({**spec, "value": clean_float(series.iloc[-1], 4) if matched else None,
                            "latest_value": clean_float(series.iloc[-1], 4) if series is not None else None,
                            "latest_month": latest_month, "status": "ok" if matched else "pending",
                            "history": _history(series, years) if series is not None else {"dates": [], "values": []},
                            "source_url": f"https://fred.stlouisfed.org/series/{spec['series_id']}"})
    partition = [r for key in config["contribution_keys"] for r in components if r["key"] == key]
    valid = (len(partition) == len(config["contribution_keys"])
             and len(set(config["contribution_keys"])) == len(partition)
             and all(r.get("effect_pp") is not None and r.get("weight_pct") is not None for r in partition)
             and abs(sum(r["weight_pct"] for r in partition) - 100) <= .01)
    if not valid:
        failed["contribution_partition"] = "Official effects/weights incomplete or partition does not cover 100% of CPI"
    effect_sum = sum(r["effect_pp"] for r in partition) if valid else None
    headline = release["rows"]["All items"]["mom"]
    # BLS rounds the published headline to 0.1; the FRED index change is the
    # unrounded figure the component effects actually add up to.
    headline_row = next((c for c in components if c["key"] == "headline"), {"history": {"observations": []}})
    index_mom = next((r["mom"] for r in headline_row["history"]["observations"]
                      if r["month"] == release["month"]), None)
    return {"status": "partial" if failed else "ok", "month": release["month"],
            "published_at": release["published_at"], "retrieved_at": release["retrieved_at"],
            "source_url": release["source_url"], "source_sha256": release["sha256"],
            "weight_month": release["weight_month"], "comparisons": comparisons,
            "consensus_retrieved_at": consensus_retrieved, "consensus_note": consensus_note,
            "components": components, "persistence": persistence, "failed_sources": failed,
            "contributions": {"keys": config["contribution_keys"], "sum_pp": clean_float(effect_sum, 4),
                              "headline_mom": headline,
                              "residual_pp": clean_float(headline - effect_sum, 4) if valid else None,
                              "headline_mom_index": index_mom,
                              "residual_index_pp": (clean_float(index_mom - effect_sum, 4)
                                                    if valid and index_mom is not None else None)},
            "note": "BLS release tables are dated snapshots, not a reconstructed first-print ledger. "
                    "FRED histories are current vintage; annual seasonal revisions apply. "
                    "Calendar consensus is retrospective, not independently timestamped before release. "
                    "No component consensus or model forecast is supplied. "
                    "Sticky and median inflation are descriptive measures, not proof of energy pass-through. "
                    "Fed-derived series may contain publisher-imputed 2025 shutdown observations; "
                    "they are not a ledger of observed first releases.",
            "refresh_note": "Updated by each dashboard build, not a live release-window service."}
