"""Build every artifact the static site reads.

One command produces the whole site: fetch, compute, write, validate, prune.
A step a human has to remember is a step that does not happen on a schedule.
"""

from __future__ import annotations

import json
import os
import time

from . import cache, site
from .config import ARTIFACT_DIR, BUILD_AGE_HOURS, ensure_dirs, load_config
from .context import build_context
from .panels import anchor, catalysts, cross_listing, dcf, earnings, evidence, financials, fixed_income, heatmaps, macro, markets, monitor, overview, positioning, priced, risk, rotation, valuation, xray
from .panels import technicals as technicals_panel
from .sources import sec
from .sources.monitor_state import carry_published, load_previous, validate_previous
from .util import SourceRecord, describe_error, utc_now_iso, write_json

# MONITOR consumes same-session valuation and calendar outputs, and runs last.
PANELS = {
    "markets": markets.build,
    "catalysts": catalysts.build,
    "priced": priced.build,
    "earnings": earnings.build,
    "heatmaps": heatmaps.build,
    "rotation": rotation.build,
    "risk": risk.build,
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
    "evidence": evidence.build,
    # Reads this session's catalysts and evidence (report dates), so after them.
    "positioning": positioning.build,
    "anchor": anchor.build,
    "monitor": monitor.build,
    # OVERVIEW reads this session's other panels and so runs last.
    "overview": overview.build,
}
SEC_PANELS = {"financials", "valuation", "dcf"}


def _carry_monitor(base_url: str, ctx, exc: Exception) -> dict | None:
    """Republish the live MONITOR ledger unchanged after a failed rebuild.

    The ledger is the one artifact a rebuild cannot recreate, so a failure
    must never reset it -- and it must not hold every other tab hostage
    either. Without this, one MONITOR failure blocked the whole deploy; and
    when the cause lay in the published ledger itself, every later night hit
    the same wall and the site froze. The build is still reported as failed
    (validate flags the carry), so the run turns red while the page updates.

    Returns the manifest record, or None when the live ledger cannot be read
    consistently either: then nothing may be published.
    """
    reason = describe_error(exc)
    try:
        text, record = carry_published(base_url, today=ctx.as_of, reason=reason)
    except Exception as carry_exc:
        ctx.log.fail("monitor_carry", carry_exc)
        return None
    pending = ARTIFACT_DIR / "monitor.pending"
    pending.write_text(text, encoding="utf-8")
    pending.replace(ARTIFACT_DIR / "monitor.json")
    return record


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
    generated_at = utc_now_iso()

    selected = [name for name in (panels or list(PANELS)) if name in PANELS]
    if skip_sec:
        selected = [name for name in selected if name not in SEC_PANELS]
    # Also honor dependency order when the user passes --panels monitor valuation.
    if "monitor" in selected:
        selected = [name for name in selected if name != "monitor"] + ["monitor"]
    if "overview" in selected:
        selected = [name for name in selected if name != "overview"] + ["overview"]

    written: list[str] = []
    built: dict[str, dict] = {}

    def optional_panel(name: str) -> dict | None:
        if name in selected:
            # A failed selected dependency must not resurrect an older artifact.
            return built.get(name)
        path = ARTIFACT_DIR / f"{name}.json"
        try:
            payload = json.loads(path.read_text())
            return payload if payload.get("as_of") == ctx.as_of else None
        except (OSError, ValueError, AttributeError):
            return None

    published_base_url = (config["monitor"]["published_base_url"]
                          if os.environ.get("MONITOR_PUBLISHED_STATE") == "1" else None)
    monitor_carried: dict | None = None

    for name in selected:
        try:
            if name == "monitor":
                previous = load_previous(
                    local_path=ARTIFACT_DIR / "monitor.json",
                    published_base_url=published_base_url,
                )
                payload = PANELS[name](ctx, valuation=optional_panel("valuation"),
                                      catalysts=optional_panel("catalysts"), previous=previous)
                payload["generated_at"] = generated_at
                validate_previous(payload)
                # Replace atomically: interruption must not truncate the ledger.
                pending = ARTIFACT_DIR / "monitor.pending"
                write_json(pending, payload)
                pending.replace(ARTIFACT_DIR / "monitor.json")
            elif name == "overview":
                payload = PANELS[name](ctx, inputs={dep: optional_panel(dep) for dep in overview.INPUTS})
            elif name == "positioning":
                payload = PANELS[name](ctx, inputs={dep: optional_panel(dep) for dep in positioning.INPUTS})
            else:
                payload = PANELS[name](ctx)
        except Exception as exc:
            if name == "monitor" and published_base_url:
                monitor_carried = _carry_monitor(published_base_url, ctx, exc)
                if monitor_carried is not None:
                    written.append(name)
                    continue
            # A panel that fails leaves a named gap. The page renders the gap
            # instead of an empty tab that looks like a quiet market.
            ctx.log.fail(name, exc)
            continue
        if name != "monitor":
            write_json(ARTIFACT_DIR / f"{name}.json", payload)
        built[name] = payload
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
        "generated_at": generated_at,
        "monitor_schema_version": 1,
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
        # Sessions Yahoo skipped, filled from iShares holdings and Nasdaq closes.
        "filled_sessions": ctx.filled_sessions,
        "session_check": ctx.session_check,
        "panels": written,
        "skipped_panels": sorted(set(selected) - set(written)),
        # Set when MONITOR could not be rebuilt and the published ledger was
        # republished unchanged: its dates, the first session it missed, why.
        **({"monitor_carried": monitor_carried} if monitor_carried else {}),
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
