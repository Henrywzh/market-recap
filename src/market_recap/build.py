"""Build every artifact the static site reads.

One command produces the whole site: fetch, compute, write, validate, prune.
A step a human has to remember is a step that does not happen on a schedule.
"""

from __future__ import annotations

import time

from . import cache, site
from .config import ARTIFACT_DIR, BUILD_AGE_HOURS, ensure_dirs, load_config
from .context import build_context
from .panels import catalysts, cross_listing, dcf, financials, fixed_income, heatmaps, macro, markets, valuation, xray
from .panels import technicals as technicals_panel
from .sources import sec
from .util import SourceRecord, utc_now_iso, write_json

# Order matters only for readability; panels do not depend on each other.
PANELS = {
    "markets": markets.build,
    "catalysts": catalysts.build,
    "heatmaps": heatmaps.build,
    "fixed_income": fixed_income.build,
    "macro": macro.build,
    "technicals": technicals_panel.build,
    "cross_listing": cross_listing.build,
    "xray": xray.build,
    # The SEC panels come last: they are the slowest, and the ones a quick
    # local rebuild skips. They share one parse of each filer (sec.filer).
    "financials": financials.build,
    "valuation": valuation.build,
    "dcf": dcf.build,
}
SEC_PANELS = {"financials", "valuation", "dcf"}


def run(
    *,
    panels: list[str] | None = None,
    history_period: str = "10y",
    skip_sec: bool = False,
    prune_cache: bool = True,
) -> dict:
    started = time.monotonic()
    ensure_dirs()
    config = load_config()
    ctx = build_context(history_period=history_period)

    selected = [name for name in (panels or list(PANELS)) if name in PANELS]
    if skip_sec:
        selected = [name for name in selected if name not in SEC_PANELS]

    written: list[str] = []
    for name in selected:
        try:
            payload = PANELS[name](ctx)
        except Exception as exc:
            # A panel that fails leaves a named gap. The page renders the gap
            # instead of an empty tab that looks like a quiet market.
            ctx.log.fail(name, exc)
            continue
        write_json(ARTIFACT_DIR / f"{name}.json", payload)
        written.append(name)

    check = sec.filing_check()
    if check["checked"]:
        ctx.log.add(SourceRecord(
            "sec_submissions", "SEC submissions index (new 10-K / 10-Q since the last fetch)",
            "https://data.sec.gov/submissions/",
            observed_date=check["latest_filed"],
            rows=check["checked"],
            policy="filings",
            status="ok" if not check["failed"] else "partial",
            error=f"{check['failed']} of {check['checked']} indexes unreadable" if check["failed"] else None,
        ))

    manifest = {
        "brand": config["brand"],
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "generated_at": utc_now_iso(),
        "build_seconds": round(time.monotonic() - started, 1),
        "build_age_hours": BUILD_AGE_HOURS,
        # Per index, not as a union: ``closes`` spans every basket, so one
        # "priced" number would overstate each index's own coverage.
        "indices": [
            {
                "key": spec.key,
                "label": spec.label,
                "symbol": spec.symbol,
                "holdings_etf": spec.holdings_etf,
                "members": int(len(ctx.members.get(spec.key, ()))),
                "priced": len(ctx.symbols_for(spec.key)),
                "holdings_as_of": ctx.holdings_dates.get(spec.key),
                "primary": spec.primary,
            }
            for spec in ctx.indices
        ],
        "series_priced": int(ctx.closes.shape[1]),
        "panels": written,
        "skipped_panels": sorted(set(selected) - set(written)),
        # Filers whose company facts were refetched because a newer 10-K/10-Q was accepted.
        "sec_filings": check,
        **ctx.log.to_dict(),
    }
    if prune_cache:
        manifest["cache_pruned"] = cache.prune()
    write_json(ARTIFACT_DIR / "manifest.json", manifest)
    # Assemble the deployable tree last, so it contains the manifest that was
    # just written rather than the previous build's.
    manifest["site"] = site.build()
    return manifest
