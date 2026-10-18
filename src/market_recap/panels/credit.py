"""CREDIT: equity-implied default risk for every non-financial name VALUATION covers.

The distance to default (compute.credit) for each name, where today's reading sits
in its own history, and a check that the debt it counts is close to the debt the
filer reports. A description of credit stress, not a warning: in the lab its
changes track corporate bond spreads but do not lead them, and a borrowing plan
the market prices shows only once a 10-Q files it (quantamental-lab
docs/credit_proxy_v1.md). Banks and insurers are left out: deposits and policy
reserves are not the debt the model means.

The THEMES "AI borrowers" card and the TICKER page read this artifact.
"""
from __future__ import annotations

import pandas as pd

from ..compute import credit as C
from ..compute.valuation import split_lookup
from ..sources import fred, sec
from ..util import clean_float

INPUTS = ("valuation",)
METHOD = ("Distance to default (Bharath and Shumway 2008): the share price x shares as filed, the debt due within "
          "a year plus half the long-term debt as filed (each from its filing date), a year's equity volatility "
          "and the 1-year Treasury yield. A model reading of equity-implied credit stress, not a CDS or bond price; "
          "in the lab its monthly changes track corporate bond spreads (about -0.7 against BAA - 10Y, 2017-2026) "
          "but do not move first, and new borrowing counts only once a 10-Q or 10-K files it.")


def _rate(ctx) -> tuple[pd.Series, str]:
    for series in ("DGS1", "DGS10"):
        try:
            frame, _ = fred.fetch_series(series)
            return frame.set_index("date")["value"] / 100, series
        except Exception as exc:  # noqa: BLE001 - the next series, then a flat rate
            ctx.log.fail(f"credit:{series}", exc)
    return pd.Series(0.04, index=ctx.closes.index), "flat 4%"


def _round(value, digits=2):
    return clean_float(value, digits)


def _path(frame: pd.DataFrame, rule: str, periods: int) -> dict:
    series = frame["dd"].resample(rule).last().dropna().tail(periods)
    return {"dates": [d.strftime("%Y-%m-%d") for d in series.index], "dd": [_round(v) for v in series]}


def _check(frame: pd.DataFrame, kept: dict, liabilities: float | None, settings: dict) -> dict:
    """The debt counted, and a flag when it is a sliver of the filer's liabilities: debt
    filed under tags the measure does not read (Nebius before its first 10-K) would
    otherwise make a borrower look safe."""
    counted = C.total_debt(kept, frame.index, settings["stale_days"]).iloc[-1]
    counted = float(counted) if pd.notna(counted) else None
    thin = bool(liabilities and liabilities >= settings["check_min_liabilities"]
                and (counted or 0.0) < settings["check_debt_share"] * liabilities)
    return {"counted_debt_bn": _round(counted / 1e9, 2) if counted is not None else None,
            "liabilities_bn": _round(liabilities / 1e9, 1) if liabilities else None,
            "debt_check": ("little debt counted against its liabilities: it has little debt, or files it under "
                           "tags this does not read") if thin else None}


def _row(symbol: str, meta: dict, frame: pd.DataFrame, kept: dict, liabilities, settings: dict) -> dict:
    last = frame.iloc[-1]
    dd = float(last["dd"])
    history = frame["dd"].iloc[-settings["percentile_sessions"]:]
    return {
        "ticker": symbol, "name": meta.get("name"), "sector": meta.get("sector"),
        "dd": _round(dd), "pd_1y": _round(float(C.default_probability(dd)) * 100, 2),
        "own_percentile": _round(C.own_percentile(history, dd), 0),
        "equity_bn": _round(last["E"] / 1e9, 1), "default_point_bn": _round(last["F"] / 1e9, 2),
        "equity_vol": _round(last["sE"] * 100, 0), "leverage": _round(last["F"] / last["E"], 3),
        "since": frame.index[0].strftime("%Y-%m-%d"),
        "monthly": _path(frame, "ME", settings["monthly_points"]),
        **_check(frame, kept, liabilities, settings),
    }


def _aggregate(frames: dict[str, pd.DataFrame]) -> dict:
    """The median and the weak tail across names, month by month: for RISK's credit cell."""
    dd = pd.DataFrame({t: f["dd"] for t, f in frames.items()}).resample("ME").last()
    counts = dd.notna().sum(axis=1)
    keep = counts >= 100
    dd, counts = dd[keep], counts[keep]
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in dd.index],
        "median": [_round(v) for v in dd.median(axis=1)],
        "p10": [_round(v) for v in dd.quantile(0.10, axis=1)],
        "share_below_2": [_round(v * 100, 1) for v in (dd < 2).sum(axis=1) / counts],
        "names": [int(v) for v in counts],
    }


def build(ctx, *, inputs: dict | None = None) -> dict:
    settings = ctx.config["credit"]
    valuation = (inputs or {}).get("valuation") or {}
    rows_in = [r for r in valuation.get("rows") or [] if r.get("ticker") and r.get("cik")]
    rate, rate_name = _rate(ctx)
    excluded = set(settings["excluded_sectors"])
    frames, all_frames, rows, skipped, seen_ciks = {}, {}, [], {}, set()
    for meta in rows_in:
        symbol = meta["ticker"]
        if meta.get("sector") in excluded:
            continue
        if symbol not in ctx.prices.columns:
            skipped[symbol] = "no price history"
            continue
        try:
            filer = sec.filer(int(meta["cik"]))
            kept = dict(filer.credit_facts)
            liabilities = ((filer.trailing or {}).get("balance") or {}).get("total_liabilities")
        except Exception as exc:  # noqa: BLE001 - one filer never fails the panel
            skipped[symbol] = str(exc)[:160]
            continue
        if not kept:
            skipped[symbol] = "no debt or share counts in its filings"
            continue
        splits = ctx.splits[symbol] if symbol in ctx.splits.columns else None
        frame = C.distance_series(ctx.prices[symbol], kept, rate, split_after=split_lookup(splits),
                                  stale_days=settings["stale_days"], vol_sessions=settings["vol_sessions"],
                                  market_cap_now=meta.get("market_cap"))
        if frame.empty:
            skipped[symbol] = "no filed debt (or shares) to measure against"
            continue
        rows.append(_row(symbol, meta, frame, kept, liabilities, settings))
        all_frames[symbol] = frame
        # One listing per company in the aggregate: a second share class is the same balance sheet.
        if meta["cik"] not in seen_ciks:
            seen_ciks.add(meta["cik"])
            frames[symbol] = frame
    rows.sort(key=lambda r: (r["dd"] is None, r["dd"]))
    # Named groups (the AI borrowers) also get a weekly path, for THEMES.
    every = {**frames, **{s: f for s, f in all_frames.items() if s not in frames}}
    watched = {group: {"names": list(names),
                       "weekly": {s: _path(every[s], "W-FRI", settings["weekly_points"]) for s in names if s in every}}
               for group, names in (settings.get("watch") or {}).items()}
    return {
        "as_of": ctx.as_of,
        "method": METHOD,
        "rate": rate_name,
        "settings": settings,
        "rows": rows,
        "aggregate": _aggregate(frames) if len(frames) >= 100 else None,
        "watch": watched,
        "skipped": skipped,
        "excluded_sectors": sorted(excluded),
    }
