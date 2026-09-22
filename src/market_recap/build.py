"""Build every artifact the static site reads."""

from __future__ import annotations

import time

from .config import ARTIFACT_DIR, ensure_dirs, load_config
from .context import build_context
from .panels import dcf, fixed_income, heatmaps, macro, markets
from .panels import technicals as technicals_panel
from .util import utc_now_iso, write_json

PANELS = {
    "markets": markets.build,
    "heatmaps": heatmaps.build,
    "fixed_income": fixed_income.build,
    "macro": macro.build,
    "technicals": technicals_panel.build,
}


def run(*, panels: list[str] | None = None, history_period: str = "10y", skip_dcf: bool = False) -> dict:
    started = time.monotonic()
    ensure_dirs()
    config = load_config()
    ctx = build_context(history_period=history_period)

    selected = panels or list(PANELS)
    written: list[str] = []
    for name in selected:
        builder = PANELS.get(name)
        if builder is None:
            continue
        try:
            payload = builder(ctx)
        except Exception as exc:
            # A panel that fails leaves a named gap. The page renders the gap
            # instead of an empty tab that looks like a quiet market.
            ctx.log.fail(name, exc)
            continue
        write_json(ARTIFACT_DIR / f"{name}.json", payload)
        written.append(name)

    if not skip_dcf and (panels is None or "dcf" in selected):
        try:
            write_json(ARTIFACT_DIR / "dcf.json", dcf.build(ctx))
            written.append("dcf")
        except Exception as exc:
            ctx.log.fail("dcf", exc)

    manifest = {
        "brand": config["brand"],
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "generated_at": utc_now_iso(),
        "build_seconds": round(time.monotonic() - started, 1),
        "constituents": int(len(ctx.holdings)),
        "constituents_priced": int(ctx.closes.shape[1]),
        "ndx_constituents": int(len(ctx.ndx_holdings)),
        "panels": written,
        **ctx.log.to_dict(),
    }
    write_json(ARTIFACT_DIR / "manifest.json", manifest)
    return manifest
