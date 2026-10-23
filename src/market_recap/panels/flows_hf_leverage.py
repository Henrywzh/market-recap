"""FLOWS · HEDGE FUNDS: leverage and equity exposure from SEC Form PF.

The OFR Hedge Fund Monitor publishes the Form PF filings of qualifying hedge
funds as quarterly aggregates. This panel reads six of them, two of which are
ratios formed here from the raw sums. Everything is quarter-end and months
behind the market: the page states the lag from the dataset itself.
"""

from __future__ import annotations

import pandas as pd

from ..compute import hf_leverage as H
from ..sources import ofr
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, to_iso_date

LABEL = "OFR Hedge Fund Monitor: SEC Form PF aggregates (qualifying hedge funds)"
POLICY = "quarterly_filing"

# The OFR mnemonics read from the dataset. GAV and NAV form the leverage ratio;
# NAV is also the base for net equity exposure.
GAV = "FPF-ALLQHF_GAV_SUM"                  # gross assets, all qualifying funds, $
NAV = "FPF-ALLQHF_NAV_SUM"                  # net assets, all qualifying funds, $
LONG_EQUITY = "FPF-ASSETCLASS_EQUITIES_LGNE_SUM"    # long equity notional, $
SHORT_EQUITY = "FPF-ASSETCLASS_EQUITIES_SGNE_SUM"   # short equity notional, $
EQUITY_DOWN_20 = "FPF-ALLQHF_EQDOWN20P_P50"          # % change in net assets, 20% equity fall, median fund
EQUITY_BORROWING = "FPF-STRATEGY_EQUITY_BORROWING_SUM"  # borrowing, equity strategy funds, $

BILLION = 1e9


def _series(dataset: dict) -> list[dict]:
    """The six output series, each with its own unit, digits and whether a percentage change is meaningful."""
    raw = {m: H.points(dataset, m) for m in (GAV, NAV, LONG_EQUITY, SHORT_EQUITY, EQUITY_DOWN_20, EQUITY_BORROWING)}
    nav = raw[NAV]
    billions = lambda s: s / BILLION
    return [
        {"id": "gross_leverage", "label": "Gross assets ÷ net assets", "unit": "x", "digits": 2, "relative": True,
         "sources": [GAV, NAV], "series": H.ratio(raw[GAV], nav)},
        {"id": "equity_long", "label": "Long equity exposure (notional)", "unit": "$bn", "digits": 0, "relative": True,
         "sources": [LONG_EQUITY], "series": billions(raw[LONG_EQUITY])},
        {"id": "equity_short", "label": "Short equity exposure (notional)", "unit": "$bn", "digits": 0, "relative": True,
         "sources": [SHORT_EQUITY], "series": billions(raw[SHORT_EQUITY])},
        {"id": "equity_net_pct_nav", "label": "Net equity exposure, % of net assets", "unit": "%", "digits": 1,
         "relative": False, "sources": [LONG_EQUITY, SHORT_EQUITY, NAV],
         "series": H.net_share_of_base(raw[LONG_EQUITY], raw[SHORT_EQUITY], nav)},
        {"id": "equity_down20", "label": "Change in net assets if equities fall 20% (median fund)", "unit": "%",
         "digits": 1, "relative": False, "sources": [EQUITY_DOWN_20], "series": raw[EQUITY_DOWN_20]},
        {"id": "equity_borrowing", "label": "Borrowing, equity strategy funds", "unit": "$bn", "digits": 0,
         "relative": True, "sources": [EQUITY_BORROWING], "series": billions(raw[EQUITY_BORROWING])},
    ]


def _entry(spec: dict, dataset: dict) -> dict:
    series: pd.Series = spec["series"].dropna().sort_index()
    digits = spec["digits"]
    latest = H.latest_row(series, relative=spec["relative"])
    return {
        "id": spec["id"],
        "label": spec["label"],
        "unit": spec["unit"],
        "sources": spec["sources"],
        "ofr_names": [H.metadata(dataset, m)["name"] for m in spec["sources"]],
        "dates": [to_iso_date(d) for d in series.index],
        "values": [clean_float(v, digits) for v in series],
        "latest": {
            "period": latest["period"],
            "value": clean_float(latest["value"], digits),
            "q_change": clean_float(latest["q_change"], digits),
            "q_change_pct": clean_float(latest["q_change_pct"], 1),
            "y_change": clean_float(latest["y_change"], digits),
            "y_change_pct": clean_float(latest["y_change_pct"], 1),
            "percentile": clean_float(latest["percentile"], 0),
            "n_obs": latest["n_obs"],
        },
    }


def build(ctx, inputs: dict | None = None) -> dict:
    """The HF leverage section. A failed fetch is logged and returned as `unavailable`, never raised."""
    try:
        dataset = ofr.fetch_dataset()
        series = _series(dataset)
        latest_period = max(s["series"].dropna().index[-1] for s in series if not s["series"].dropna().empty)
        last_update = max(H.metadata(dataset, m)["last_update"] for m in (GAV, NAV, LONG_EQUITY))
    except Exception as exc:
        reason = str(exc)[:ERROR_DETAIL_CHARS]
        ctx.log.add(SourceRecord("ofr_formpf", LABEL, ofr.HOME_URL, status="error", error=reason))
        return {"unavailable": reason}

    entries = [_entry(spec, dataset) for spec in series]
    lag_days = int((pd.Timestamp(last_update) - latest_period).days)
    ctx.log.add(SourceRecord("ofr_formpf", LABEL, ofr.HOME_URL, to_iso_date(latest_period),
                             rows=sum(len(e["dates"]) for e in entries), policy=POLICY))
    return {
        "as_of": ctx.as_of,
        "source": {
            "label": LABEL,
            "url": ofr.HOME_URL,
            "dataset": ofr.DATASET,
            "vintage": "current vintage, as of the OFR's last update",
            "latest_period": to_iso_date(latest_period),
            "first_period": min(e["dates"][0] for e in entries if e["dates"]),
            "last_update": pd.Timestamp(last_update).strftime("%Y-%m-%d"),
            "lag_days": lag_days,
            "lag": (f"Quarter-end data. The latest quarter ({to_iso_date(latest_period)}) was in the dataset "
                    f"{lag_days} days after it ended; Form PF filings arrive months after each quarter."),
        },
        "series": entries,
        "latest": [{"id": e["id"], "label": e["label"], "unit": e["unit"], **e["latest"]} for e in entries],
    }
