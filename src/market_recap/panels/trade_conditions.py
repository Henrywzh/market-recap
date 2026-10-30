"""TRADE DESK -> MARKET STRUCTURE: the backdrop on each past session, for conditioning.

One artifact of daily states (as runs, see compute.trade_conditions) with today's
state of each, so the Trade Desk can keep only the signals that fired in a
backdrop like a chosen one and fill "like today" in one click.
"""

from __future__ import annotations

import json

import pandas as pd

from ..compute import trade_conditions as T
from ..config import ARTIFACT_DIR, REGIME_QUADRANT_HISTORY_PATH
from ..context import YAHOO_URL
from ..sources import fred, yahoo
from ..util import SourceRecord, clean_float, to_iso_date

# The growth / inflation quadrant's daily nowcast ledger.
INPUTS = ("macro",)

LABELS = {
    "fed": "FED CYCLE",
    "rates": "10Y YIELD TREND",
    "trend": "MARKET TREND",
    "vix": "VIX",
    "breadth": "EQUAL WEIGHT VS CAP WEIGHT",
    "quadrant": "GROWTH / INFLATION",
}


def _definitions(cfg: dict) -> dict:
    return {
        "fed": f"Fed funds target (upper bound since Dec 2008) against {cfg['fed_lookback_days']} days earlier: up = hiking, down = cutting, unchanged = hold.",
        "rates": f"10-year Treasury yield against its {cfg['long_ma']}-session average.",
        "trend": f"{cfg['market']} against its {cfg['long_ma']}-session average.",
        "vix": f"VIX close: below {cfg['vix_calm']:g} calm, above {cfg['vix_stressed']:g} stressed, normal between.",
        "breadth": (f"z-score of log({cfg['equal_weight']} / {cfg['market']}) against its trailing {cfg['ew_z_window']} sessions; "
                    f"beyond ±{cfg['ew_z_band']:g} = equal weight leading / lagging."),
        "quadrant": ("Real-time growth (ADS, on the Chicago Fed scale) and the 3-month change in core PCE inflation (Cleveland nowcast): "
                     "month-end readings 2014-2026 from the archived vintages, then the MACRO tab's daily nowcast. "
                     "Applies from the session after it was read. Starts 2014."),
    }


def _ledger(macro: dict | None) -> list:
    if macro is None:
        # A partial build without MACRO: the last written ledger is still what was known.
        try:
            macro = json.loads((ARTIFACT_DIR / "macro.json").read_text())
        except (OSError, ValueError):
            return []
    return ((macro or {}).get("regime_nowcast") or {}).get("ledger") or []


def assemble(*, closes: pd.DataFrame, fed_target: pd.Series, ten_year: pd.Series, quadrant_history: list,
             ledger: list, cfg: dict, as_of: str) -> dict:
    """Pure: the artifact from plain series."""
    start = pd.Timestamp(cfg["start"])
    market, equal = closes[cfg["market"]].dropna(), closes[cfg["equal_weight"]]
    sessions = market.index[(market.index >= start) & (market.index <= pd.Timestamp(as_of))]
    z, ew = T.equal_weight_z(equal, market, int(cfg["ew_z_window"]), float(cfg["ew_z_band"]))
    states = {
        "fed": T.fed_cycle(fed_target, sessions, int(cfg["fed_lookback_days"])),
        "rates": T.above_average(ten_year, sessions, int(cfg["long_ma"]), "RISING", "FALLING"),
        "trend": T.above_average(market, sessions, int(cfg["long_ma"]), "ABOVE 200D", "BELOW 200D"),
        "vix": T.vix_band(closes[cfg["vix"]], sessions, float(cfg["vix_calm"]), float(cfg["vix_stressed"])),
        "breadth": ew.reindex(sessions),
        "quadrant": T.quadrant_states(events := T.quadrant_events(quadrant_history, ledger), sessions),
    }
    options = {
        "fed": ["HIKING", "HOLD", "CUTTING"], "rates": ["RISING", "FALLING"], "trend": ["ABOVE 200D", "BELOW 200D"],
        "vix": ["CALM", "NORMAL", "STRESSED"], "breadth": ["EW LEADING", "IN LINE", "EW LAGGING"], "quadrant": list(T.QUADRANTS),
    }
    defs = _definitions(cfg)
    readings = {
        "fed": clean_float(fed_target.dropna().iloc[-1], 2) if len(fed_target.dropna()) else None,
        "rates": clean_float(ten_year.dropna().iloc[-1], 2) if len(ten_year.dropna()) else None,
        "trend": clean_float((market.iloc[-1] / market.rolling(int(cfg["long_ma"])).mean().iloc[-1] - 1) * 100, 1),
        "vix": clean_float(closes[cfg["vix"]].dropna().iloc[-1], 1),
        "breadth": clean_float(z.dropna().iloc[-1], 2) if len(z.dropna()) else None,
        "quadrant": None,
    }
    conditions = []
    for key, series in states.items():
        known = series.dropna()
        conditions.append({"key": key, "label": LABELS[key], "definition": defs[key], "options": options[key],
                           # The quadrant read after this close applies from the next session; "like today" wants it now.
                           "today": (events[-1][1] if events else None) if key == "quadrant"
                           else series.iloc[-1] if len(series) and isinstance(series.iloc[-1], str) else None,
                           "reading": readings[key],
                           "from": to_iso_date(known.index[0]) if len(known) else None,
                           "runs": T.runs(series)})
    return {
        "as_of": as_of,
        "sessions_through": to_iso_date(sessions[-1]),
        "conditions": conditions,
        "settings": {k: cfg[k] for k in ("min_trades", "min_stretches", "stretch_gap_days")},
        "notes": [
            "Each condition is read at the signal session's close, from what was known then: no revised series, no thresholds fitted on later data.",
            "Every condition you add shrinks the sample. The page shows the unconditioned result beside it, the number of separate stretches the trades come from, and how often a random draw of the same number of trades did as well.",
            "The growth / inflation quadrant has not sorted next-month market returns in the real-time test (MACRO tab, nowcast track record): read it as context, not as a signal.",
        ],
    }


def build(ctx, inputs: dict | None = None) -> dict:
    cfg = ctx.config["trade_conditions"]
    symbols = [cfg["market"], cfg["equal_weight"], cfg["vix"]]
    closes = yahoo.fetch_closes(symbols, period=cfg["history_period"])
    missing = sorted(set(symbols) - set(closes.columns))
    ctx.log.add(SourceRecord("trade_conditions_prices", "Daily closes: market fund, equal-weight fund, VIX", YAHOO_URL,
                             to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if not missing else "partial", error=f"no data: {', '.join(missing)}" if missing else None))
    if missing:
        raise RuntimeError(f"no prices for {', '.join(missing)}")
    targets = []
    for series_id in cfg["fed_target_series"]:
        frame, url = fred.fetch_series(series_id)
        targets.append(frame.set_index("date")["value"])
        ctx.log.add(SourceRecord(f"fred_trade_conditions_{series_id.lower()}", f"Fed funds target ({series_id})", url,
                                 to_iso_date(frame["date"].iloc[-1]), rows=len(frame)))
    fed_target = pd.concat(targets).sort_index()
    fed_target = fed_target[~fed_target.index.duplicated(keep="last")]
    frame, url = fred.fetch_series(cfg["ten_year_series"])
    ctx.log.add(SourceRecord("fred_trade_conditions_dgs10", "10-year Treasury yield", url, to_iso_date(frame["date"].iloc[-1]), rows=len(frame)))
    history = json.loads(REGIME_QUADRANT_HISTORY_PATH.read_text())["rows"]
    return assemble(closes=closes, fed_target=fed_target, ten_year=frame.set_index("date")["value"], quadrant_history=history,
                    ledger=_ledger((inputs or {}).get("macro")), cfg=cfg, as_of=ctx.as_of)
