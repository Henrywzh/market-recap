"""MARKETS -> MARKET STATE: how narrow or stressed the market is, and what followed.

The latest reading of each breadth and stress measure (equal weight and small
caps against the market, the sector funds above their 200- and 50-day lines,
the distance from the high, the VIX) with a year of each, which sector funds
are above or below, and for each configured state: whether it holds today, how
many days and separate episodes it has held since 2009, and what the market
did over the next three months on those days against the others, with a 95%
range. A range that includes zero is "not detected" and the page says so; see
compute.market_state for what the history has shown.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..compute import market_state as M
from ..config import PERIOD_TRADING_DAYS
from ..context import YAHOO_URL
from ..sources import yahoo
from ..util import SourceRecord, clean_float, to_iso_date

UNITS = {"rsp_spy": "%", "iwm_spy": "%", "sector_above_200": "%", "sector_above_50": "%", "spy_drawdown": "%", "vix": "pts"}
OUTCOMES = {"ret": "RETURN", "worst_dd": "WORST FALL", "hit": "FELL BY THE FLOOR OR MORE"}
NOTES = (
    "Days in a state overlap: neighbouring days share most of their forward window, so the count of separate "
    "episodes (runs more than a horizon apart) is the honest sample size, and the ranges are from a block bootstrap.",
    "Funds, not constituents: the equal-weight, small-cap and sector funds exist for the whole history, so no reading "
    "here is built from today's index members. Constituent breadth is on the index sections below.",
    "The last horizon's worth of sessions has no outcome yet and is left out of every figure.",
    "A range that includes zero means no difference is detected, not that there is none.",
)


def _rule_text(conditions: list[dict], cfg: dict) -> str:
    names = {
        "rsp_spy": f"RSP / SPY ratio change over {cfg['relative_period']}", "iwm_spy": f"IWM / SPY ratio change over {cfg['relative_period']}",
        "sector_above_200": f"sector funds above {cfg['long_ma']}D", "sector_above_50": f"sector funds above {cfg['short_ma']}D",
        "spy_drawdown": f"market from its {cfg['high_period']} high", "vix": "VIX",
    }
    suffix = {"pp": " pp", "%": "%", "pts": ""}
    parts = [f"{names[c['reading']]} {'<' if c['op'] == 'lt' else '>'} {c['value']:g}{suffix[UNITS[c['reading']]]}" for c in conditions]
    return " and ".join(parts)


def _outcome(entry: dict, digits: int) -> dict:
    out = {k: clean_float(v, digits) for k, v in entry.items()}
    out["detected"] = bool(out["lo"] is not None and out["hi"] is not None and (out["lo"] > 0 or out["hi"] < 0))
    return out


def assemble(*, as_of: date, closes: pd.DataFrame, sectors: dict[str, str], market: str, cfg: dict) -> dict:
    """The panel from plain data: daily closes for the market, the funds, the
    VIX and the sector funds, and the sector -> fund map. Pure: no fetching."""
    closes = closes[(closes.index <= pd.Timestamp(as_of)) & closes[market].notna()].sort_index()
    relative, high = PERIOD_TRADING_DAYS[cfg["relative_period"]], PERIOD_TRADING_DAYS[cfg["high_period"]]
    horizon, chart = PERIOD_TRADING_DAYS[cfg["horizon_period"]], PERIOD_TRADING_DAYS[cfg["chart_period"]]
    present = [etf for etf in sectors.values() if etf in closes.columns]
    f = M.features(closes, market=market, equal_weight=cfg["equal_weight"], small_caps=cfg["small_caps"], vix=cfg["vix"],
                   sectors=present, relative_sessions=relative, high_sessions=high, long_ma=cfg["long_ma"], short_ma=cfg["short_ma"])
    last = f.iloc[-1]

    ma200 = closes[present].rolling(cfg["long_ma"]).mean().iloc[-1]
    ma50 = closes[present].rolling(cfg["short_ma"]).mean().iloc[-1]
    price = closes[present].iloc[-1]
    sector_rows = [{"sector": name, "etf": etf, "above_200": bool(price[etf] > ma200[etf]) if pd.notna(ma200[etf]) else None,
                    "above_50": bool(price[etf] > ma50[etf]) if pd.notna(ma50[etf]) else None,
                    "vs_200_pct": clean_float((price[etf] / ma200[etf] - 1) * 100, 2) if pd.notna(ma200[etf]) else None}
                   for name, etf in sectors.items() if etf in present]
    known_200 = sum(r["above_200"] is not None for r in sector_rows)
    readings = []
    for key in M.READINGS:
        series = f[key].iloc[-chart:]
        reading = {"key": key, "label": cfg["labels"][key], "unit": UNITS[key], "value": clean_float(last[key], 2),
                   "spark": [clean_float(v, 2) for v in series]}
        if key in ("sector_above_200", "sector_above_50"):
            flag = "above_200" if key == "sector_above_200" else "above_50"
            reading["count"] = {"above": sum(bool(r[flag]) for r in sector_rows if r[flag] is not None),
                                "of": sum(r[flag] is not None for r in sector_rows)}
        readings.append(reading)

    forward = M.forward_outcomes(closes[market], horizon, cfg["drawdown_floor_pct"])
    start = pd.Timestamp(cfg["history_start"])
    scored = f[(f.index >= start) & forward["ret"].notna()]
    fwd = forward.loc[scored.index]
    indices = M.block_indices(len(scored), horizon, int(cfg["resamples"]), int(cfg["seed"]))
    states = []
    for spec in cfg["states"]:
        mask_all = M.holds(f, spec["conditions"])
        mask = mask_all.loc[scored.index].to_numpy()
        days = int(mask.sum())
        entry: dict = {"key": spec["key"], "label": spec["label"], "rule": _rule_text(spec["conditions"], cfg),
                       "active_now": bool(mask_all.iloc[-1]), "days": days, "scored_days": len(scored),
                       "episodes": M.episodes(mask, horizon),
                       "first": to_iso_date(scored.index[mask][0]) if days else None,
                       "last": to_iso_date(scored.index[mask][-1]) if days else None,
                       "days_now": int(mask_all.astype(int).iloc[::-1].cumprod().sum())}
        if days >= cfg["min_days"]:
            entry["outcomes"] = {key: _outcome(M.mean_difference(fwd[key].to_numpy(dtype=float) * (100 if key == "hit" else 1), mask, indices),
                                               2) for key in OUTCOMES}
            entry["status"] = "ok"
        else:
            entry["outcomes"], entry["status"] = None, "insufficient"
        states.append(entry)

    return {
        "as_of": as_of.isoformat(),
        "settings": {k: cfg[k] for k in ("history_start", "relative_period", "high_period", "horizon_period", "long_ma", "short_ma",
                                         "drawdown_floor_pct", "resamples", "min_days")},
        "inputs": {"prices_through": to_iso_date(closes.index[-1]), "scored_through": to_iso_date(scored.index[-1]) if len(scored) else None,
                   "scored_days": int(len(scored)), "horizon_sessions": horizon, "sector_funds": len(present), "sector_funds_with_200d": known_200},
        "outcomes": OUTCOMES,
        "readings": readings,
        "sectors": sorted(sector_rows, key=lambda r: (r["vs_200_pct"] is None, -(r["vs_200_pct"] or 0))),
        "states": states,
        "notes": list(NOTES),
    }


def build(ctx) -> dict:
    cfg = ctx.config["market_state"]
    as_of = date.fromisoformat(ctx.as_of)
    market = ctx.config["universe"]["market_proxy"]
    sectors = ctx.sector_etfs
    symbols = sorted({market, cfg["equal_weight"], cfg["small_caps"], cfg["vix"], *sectors.values()})
    closes = yahoo.fetch_closes(symbols, period=f"{int(cfg['history_years'])}y")
    missing = sorted(set(symbols) - set(closes.columns))
    ctx.log.add(SourceRecord("market_state_prices", "Daily closes: market, equal-weight and small-cap funds, sector funds, VIX", YAHOO_URL,
                             to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if not missing else "partial", error=f"no data: {', '.join(missing)}" if missing else None))
    required = {market, cfg["equal_weight"], cfg["small_caps"], cfg["vix"]}
    if required & set(missing):
        raise RuntimeError(f"no prices for {', '.join(sorted(required & set(missing)))}")
    return assemble(as_of=as_of, closes=closes, sectors=sectors, market=market, cfg=cfg)
