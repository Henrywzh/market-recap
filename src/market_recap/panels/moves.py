"""MOVES: the last session's move of every covered stock in its own terms.

For each S&P 500 / Nasdaq 100 member and watchlist name: the return in units
of its own volatility, split into the part its market and sector betas
explain and its own part; the overnight gap and the session's own move;
volume against its usual; whether it reported; and the range its own history
implies for the next sessions. HEAT MAPS lists the unusual ones; a ticker page
shows its own row. Descriptive, not a signal: a large move says nothing by
itself about the next one.
"""

from __future__ import annotations

import json

import pandas as pd

from ..compute import moves as M
from ..compute import sector_selloff as S
from ..config import REPO_ROOT
from ..context import YAHOO_URL
from ..sources import yahoo
from ..util import SourceRecord, clean_float

# Same-session artifacts this panel reads (build.optional_panel).
INPUTS = ("catalysts",)


def _labels(ctx) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for frame in ctx.members.values():
        for row in frame.drop_duplicates("yahoo_symbol").itertuples():
            out.setdefault(row.yahoo_symbol, {"name": row.name, "sector": row.sector,
                                              "sub_sector": getattr(row, "sub_sector", None)})
    for entry in ctx.config.get("watchlist", []):
        out.setdefault(entry["ticker"], {"name": entry.get("label") or entry["ticker"], "sector": None, "sub_sector": None})
    return out


def _reported(catalysts: dict | None, as_of: str) -> set[str] | None:
    """Names whose report this session reacted to (before the open, or after
    the previous close); None when the calendar does not describe this session."""
    recent = (catalysts or {}).get("recent") or {}
    if recent.get("session") != as_of:
        return None
    return {e.get("symbol") for e in recent.get("earnings_reacted") or [] if e.get("symbol")}


def _pct(value, digits=2):
    return clean_float(100 * value, digits) if value is not None else None


def _row(symbol, label, parts, split, ratio, above, reported, band) -> dict:
    return {
        "ticker": symbol, "name": label["name"], "sector": label["sector"], "sub_sector": label["sub_sector"],
        "ret_pct": _pct(parts["ret"]), "z": clean_float(parts["z"], 2),
        "market_pct": _pct(parts["market"]), "sector_pct": _pct(parts["sector"]), "own_pct": _pct(parts["own"]),
        "z_own": clean_float(parts["z_own"], 2),
        "sigma_pct": _pct(parts["sigma"]), "sigma_own_pct": _pct(parts["sigma_own"]),
        "beta_market": clean_float(parts["beta_market"], 2), "beta_sector": clean_float(parts["beta_sector"], 2),
        "gap_pct": _pct(split["gap"]) if split else None, "intraday_pct": _pct(split["intraday"]) if split else None,
        "volume_ratio": clean_float(ratio, 2), "above_200d": above, "reported": reported, "range": band,
    }


def _session_flags(ctx, settings: dict, funds: pd.DataFrame, market_symbol: str) -> dict:
    """Market-wide facts at the last close that tag every shock: VIX above its
    median of the sessions before, and the market above its 200-session
    average. None where the input is missing or does not reach this session."""
    last = ctx.closes.index[-1]
    flags = {"vix_high": None, "market_above_200d": None}
    market = funds[market_symbol].dropna()
    if len(market) >= 200 and market.index[-1] == last:
        flags["market_above_200d"] = bool(market.iloc[-1] > market.iloc[-200:].mean())
    try:
        vix = yahoo.fetch_closes([settings["vix"]], period=ctx.history_period)[settings["vix"]].dropna()
        vix = vix[vix.index <= last]  # a bar for a session after the one described is not its close
    except Exception as exc:  # a missing VIX leaves the tag unknown, not the panel broken
        ctx.log.fail("moves_vix", exc)
        return flags
    window = settings["vix_median_sessions"]
    if len(vix) > window and vix.index[-1] == last:
        flags["vix_high"] = bool(vix.iloc[-1] > vix.iloc[-window - 1:-1].median())
    return flags


def _shock_fields(row: dict, parts: dict, settings: dict, flags: dict) -> None:
    """Direction on every row; for a shock the tags known at its close, the
    cause-calibrated range (the uncalibrated one kept as ``range_raw``) and why."""
    threshold = settings["threshold_sigma"]
    direction = M.shock_direction(parts["z_own"], threshold)
    row.update({"direction": direction, "tags": None, "range_raw": None, "range_factor": None, "range_reason": None})
    if direction is None:
        return
    tags = M.shock_tags(row, direction=direction, history=parts.get("z_own_history"), threshold=threshold, **flags)
    factor, reason = M.range_factor(tags, settings["range_factors"])
    row.update({"tags": tags, "range_raw": row["range"], "range_factor": factor, "range_reason": reason,
                "range": M.calibrate_range(row["range"], factor)})


def _move_states(settings: dict) -> dict | None:
    """The frozen research table (what shocks like this did next), or None when
    the file is not there: the card then simply omits it."""
    path = REPO_ROOT / settings["states_file"]
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    source = table.get("provenance", {})
    return {k: table[k] for k in ("units", "universe", "since", "outcome", "horizons", "threshold_sigma", "definitions", "rows") if k in table} | {
        "source": {"branch": source.get("branch"), "commit": source.get("commit"),
                   "runs": [source.get(v, {}).get("run") for v in ("v1", "v2")]}}


def build(ctx, *, inputs: dict | None = None) -> dict:
    settings = ctx.config["moves"]
    inputs = inputs or {}
    market_symbol = settings["market"]
    sector_funds = dict(ctx.config["universe"]["sectors"])
    funds = ctx.etf_closes
    if market_symbol not in funds.columns:
        raise RuntimeError(f"{market_symbol} has no closes; moves are measured against it")
    market = funds[market_symbol].pct_change()
    ohlcv = yahoo.fetch_ohlcv_cache(ctx.history_period)
    opens, volumes = ohlcv.get("open", pd.DataFrame()), ohlcv.get("volume", pd.DataFrame())
    for frame in (opens, volumes):
        if not frame.empty:
            frame.index = pd.to_datetime(frame.index).tz_localize(None)
    reported = _reported(inputs.get("catalysts"), ctx.as_of)
    quantiles = tuple(settings["range_quantiles"])
    flags = _session_flags(ctx, settings, funds, market_symbol)

    rows, skipped = [], []
    for symbol, label in sorted(_labels(ctx).items()):
        if symbol not in ctx.closes.columns:
            continue
        closes = ctx.closes[symbol].dropna()
        if closes.empty or closes.index[-1] != ctx.closes.index[-1]:
            skipped.append(symbol)  # no close this session: nothing to measure
            continue
        fund = sector_funds.get(label["sector"])
        sector = funds[fund].pct_change() if fund in funds.columns else None
        parts = M.decompose(closes.pct_change(), market, sector,
                            beta_sessions=settings["beta_sessions"], vol_sessions=settings["vol_sessions"],
                            history=settings["repeat_sessions"])
        if parts is None:
            skipped.append(symbol)
            continue
        split = (M.session_split(ctx.prices[symbol], opens[symbol])
                 if symbol in ctx.prices.columns and symbol in opens.columns else None)
        ratio = M.volume_ratio(volumes[symbol], settings["volume_sessions"]) if symbol in volumes.columns else None
        sma = closes.rolling(200).mean().iloc[-1]
        above = bool(closes.iloc[-1] > sma) if pd.notna(sma) else None
        band = M.forward_range(closes, horizon=settings["range_sessions"],
                               history_sessions=settings["range_history_sessions"], quantiles=quantiles)
        rows.append(_row(symbol, label, parts, split, ratio, above,
                         None if reported is None else symbol in reported, band))
        _shock_fields(rows[-1], parts, settings, flags)

    threshold = settings["threshold_sigma"]
    unusual = [r["ticker"] for r in rows
               if any(abs(r[k]) >= threshold for k in ("z", "z_own") if r[k] is not None)]
    with_open = sum(r["gap_pct"] is not None for r in rows)
    ctx.log.add(SourceRecord("moves_opens", "Session opens and volumes for the gap / session split", YAHOO_URL, ctx.as_of,
                             rows=with_open, status="ok" if with_open else "partial",
                             error=None if with_open else "no opens in the price cache this build"))
    # A technology-only sell-off flag for HEAT MAPS (research v6); absent without its config table.
    selloff = S.build(funds, rows, settings.get("sector_selloff"), market=market_symbol, as_of=ctx.as_of,
                      beta_sessions=settings["beta_sessions"], vol_sessions=settings["vol_sessions"])
    spy = market.dropna()
    return {
        "as_of": ctx.as_of,
        "market": {"symbol": market_symbol, "ret_pct": _pct(spy.iloc[-1]) if len(spy) else None,
                   "z": clean_float(spy.iloc[-1] / spy.iloc[-61:-1].std(), 2) if len(spy) > 61 else None},
        "settings": {k: settings[k] for k in ("threshold_sigma", "vol_sessions", "beta_sessions",
                                              "range_sessions", "range_history_sessions", "volume_sessions")}
                    | {"range_quantiles": list(quantiles)},
        "rows": rows,
        "move_states": _move_states(settings),
        "sector_selloff": selloff,
        "unusual": unusual,
        "skipped": skipped,
        "note": (
            f"σ: the standard deviation of the stock's daily returns over the {settings['vol_sessions']} sessions "
            f"before this one (own σ: of what its market and sector betas leave over). Betas: regression on "
            f"{market_symbol} and the sector fund's return over {market_symbol}, over the {settings['beta_sessions']} "
            "sessions before this one. Nothing is estimated with this session or later. Gap: previous close to "
            "the open; session: open to close (split-adjusted, not dividend-adjusted prices). Range: the stock's "
            f"own past {settings['range_sessions']}-session returns, each scaled by the volatility known when it "
            "started, re-scaled to today's (no normal distribution assumed). For a shock the range is widened or "
            "narrowed by one factor from how past bands covered shocks of its kind (a report, a repeat, VIX high); "
            "the uncalibrated band is kept. A large move is descriptive, not a "
            "signal; whether one is followed by a rebound or more of the same depends on why it happened."
        ),
    }
