"""A technology-only sell-off session, and which technology names it hit hardest.

Research (quantamental-lab docs/sigma_move_states_v6.md): on days XLK fell at
least 2σ of its own part more than SPY explains, with SPY itself not at -2σ,
the hardest-hit technology names have been followed by a recovery against
their sector. This module only detects such a session and lists the losers
with the three facts the research split them by. It scores nothing.

Causal like compute/moves.py: the beta comes from the sessions before the one
measured, and so does the volatility the session is measured against.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..util import clean_float


def selloff_session(fund: pd.Series, market: pd.Series, *, beta_sessions: int, vol_sessions: int,
                    fund_z_max: float, market_z_floor: float) -> dict | None:
    """XLK's own part (return less beta times SPY's, OLS with intercept over the
    ``beta_sessions`` before) in units of its ``vol_sessions`` volatility, and
    SPY's own z; ``active`` when the fund is at or below ``fund_z_max`` while
    SPY is above ``market_z_floor``. None when there is too little history."""
    frame = pd.concat({"f": fund, "m": market}, axis=1).dropna()
    if len(frame) < vol_sessions + 2:
        return None
    today, past = frame.iloc[-1], frame.iloc[:-1].tail(beta_sessions)
    beta = float(np.polyfit(past["m"].to_numpy(), past["f"].to_numpy(), 1)[0])
    sigma_own = float((past["f"] - beta * past["m"]).tail(vol_sessions).std())
    sigma_market = float(past["m"].tail(vol_sessions).std())
    if not (sigma_own > 0 and sigma_market > 0):
        return None
    z = float((today["f"] - beta * today["m"]) / sigma_own)
    market_z = float(today["m"] / sigma_market)
    return {"session": frame.index[-1], "z": z, "spy_z": market_z,
            "active": bool(z <= fund_z_max and market_z > market_z_floor)}


def _led_by_session(row: dict) -> bool | None:
    gap, session = row.get("gap_pct"), row.get("intraday_pct")
    if gap is None or session is None:
        return None
    return abs(gap) < abs(session)


def losers(rows: list[dict], *, sector: str, share: float) -> tuple[list[dict], float | None]:
    """The sector's bottom ``share`` by the session's raw return, each with the
    three research tags; and the median sector beta they are compared with.

    A name ``fits_profile`` only when all three are known and hold: high sector
    beta (above the sector's median), the fall made during the session rather
    than at the open, and no report that session.
    """
    members = [r for r in rows if r.get("sector") == sector and r.get("ret_pct") is not None]
    if not members:
        return [], None
    betas = [r["beta_sector"] for r in members if r.get("beta_sector") is not None]
    median = float(np.median(betas)) if betas else None
    worst = sorted(members, key=lambda r: r["ret_pct"])[:max(1, round(share * len(members)))]
    out = []
    for r in worst:
        high_beta = median is not None and r.get("beta_sector") is not None and r["beta_sector"] > median
        led = _led_by_session(r)
        reported = r.get("reported")
        out.append({
            "ticker": r["ticker"], "name": r["name"], "sub_sector": r.get("sub_sector"),
            "ret_pct": r["ret_pct"], "own_pct": r.get("own_pct"), "z_own": r.get("z_own"),
            "beta_sector": r.get("beta_sector"),
            "high_beta": high_beta, "session_led": led, "reported": reported,
            "fits_profile": bool(high_beta and led is True and reported is False),
        })
    out.sort(key=lambda d: (not d["fits_profile"], d["ret_pct"]))
    return out, median


def build(funds: pd.DataFrame, rows: list[dict], settings: dict | None, *, market: str, as_of: str,
          beta_sessions: int, vol_sessions: int) -> dict | None:
    """The ``sector_selloff`` payload; None when the config has no such table."""
    if not settings:
        return None
    fund = settings["fund"]
    base = {"active": False, "fund": fund, "market": market, "z": None, "spy_z": None, "losers": [],
            "history": settings.get("history")}
    if fund not in funds.columns or market not in funds.columns:
        return base
    found = selloff_session(funds[fund].pct_change(), funds[market].pct_change(),
                            beta_sessions=beta_sessions, vol_sessions=vol_sessions,
                            fund_z_max=settings["fund_z_max"], market_z_floor=settings["market_z_floor"])
    if found is None or found["session"] != pd.Timestamp(as_of):
        return base  # a fund that did not trade this session says nothing about it
    base |= {"z": clean_float(found["z"], 2), "spy_z": clean_float(found["spy_z"], 2)}
    if not found["active"]:
        return base
    names, median = losers(rows, sector=settings["sector"], share=settings["loser_share"])
    return base | {"active": True, "losers": names, "beta_median": clean_float(median, 2) if median is not None else None,
                   "members": sum(r.get("sector") == settings["sector"] for r in rows)}
