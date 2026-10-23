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
others down.
"""

from __future__ import annotations

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


def build(ctx, inputs: dict | None = None) -> dict:
    inputs = inputs or {}
    out: dict = {"as_of": ctx.as_of}
    for key, module in SECTIONS:
        try:
            out[key] = module.build(ctx, inputs)
        except Exception as exc:  # a section's bug is its own gap, not the page's
            out[key] = {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
            ctx.log.add(SourceRecord(f"flows_{key}", f"FLOWS section {key}", "", status="error",
                                     error=str(exc)[:ERROR_DETAIL_CHARS]))
    return out
