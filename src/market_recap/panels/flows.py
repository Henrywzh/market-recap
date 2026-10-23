"""FLOWS view: who is buying, from published records rather than a model.

Five readings, each from its own public source and at its own speed:

- ETF flows: daily creations and redemptions, the change in each fund's
  published shares outstanding priced at NAV (flows_etf).
- Futures by trader type: the CFTC's weekly Traders in Financial Futures for
  the equity index and VIX contracts (flows_cot).
- Who bought US equities: the Federal Reserve's Z.1 net purchases by holding
  sector, quarterly (flows_z1).
- Hedge-fund leverage: Form PF aggregates from the OFR Hedge Fund Monitor,
  quarterly and months late (flows_hf_leverage).
- Hedge-fund crowding: 13F long holdings of a curated list of managers,
  45 days after each quarter (flows_hf_13f).

A section whose source fails says so in its own place; it never takes the
others down. The sections read different publishers and nothing of each
other, so they are fetched side by side: the build waits for the slowest
(the 13F filings at the SEC's pace), not for all five in turn.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time

from ..util import ERROR_DETAIL_CHARS, SourceRecord
from . import flows_cot, flows_etf, flows_hf_13f, flows_hf_leverage, flows_z1

INPUTS = ("positioning", "heatmaps")

SECTIONS = (
    ("etf", flows_etf),
    ("cot", flows_cot),
    ("z1", flows_z1),
    ("hf_leverage", flows_hf_leverage),
    ("hf_13f", flows_hf_13f),
)


def _section(ctx, inputs: dict, key: str, module) -> tuple[dict, float]:
    started = time.monotonic()
    try:
        payload = module.build(ctx, inputs)
    except Exception as exc:  # a section's bug is its own gap, not the page's
        payload = {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
        ctx.log.add(SourceRecord(f"flows_{key}", f"FLOWS section {key}", "", status="error",
                                 error=str(exc)[:ERROR_DETAIL_CHARS]))
    return payload, round(time.monotonic() - started, 1)


def build(ctx, inputs: dict | None = None) -> dict:
    inputs = inputs or {}
    with ThreadPoolExecutor(len(SECTIONS)) as pool:
        futures = {key: pool.submit(_section, ctx, inputs, key, module) for key, module in SECTIONS}
        results = {key: future.result() for key, future in futures.items()}
    if hasattr(ctx, "diagnostics"):
        # Seconds per section, each on its own thread: the panel takes the longest.
        ctx.diagnostics["flows"] = {"seconds": {key: seconds for key, (_, seconds) in results.items()}}
    return {"as_of": ctx.as_of, **{key: payload for key, (payload, _) in results.items()}}
