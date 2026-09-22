"""CROSS-LISTING tab: one company, two listings, and what the gap does not mean.

The premium between a US line and its home-market line is two different
things at once, and a panel that shows only the number invites reading the
wrong one:

* Its **level** can be a real dislocation. SK hynix's Nasdaq ADS has traded
  around a 35-40% premium since listing, which a small free float and
  restricted conversion can sustain.
* Its **daily change** mostly is not. Seoul closes about fourteen hours before
  New York, so a same-date comparison puts a fresh US close against a home
  close that is most of a day old. Measured on this pair, the change in the
  premium correlates +0.55 with the US leg's own return and -0.63 with the
  home leg's, which is what "one leg moved and the other had already closed"
  looks like.

So the panel ships its own diagnostics. Without them there is no way to tell a
widening dislocation from a wrong depositary ratio or a misaligned session,
and all three produce a moving line.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import period_sessions
from ..context import completed_sessions
from ..sources import yahoo
from ..util import SourceRecord, clean_float, to_iso_date


def _diagnostics(frame: pd.DataFrame, *, min_pairs: int) -> dict:
    """Numbers that say whether the premium series is measuring anything.

    A real cross-listing premium is persistent: it drifts over weeks. A series
    whose day-to-day changes are larger than its own level dispersion, or whose
    daily autocorrelation is negative, is reporting a session gap or a wrong
    ratio rather than a dislocation.
    """
    premium = frame["premium_pct"]
    changes = premium.diff()
    us_return = frame["us"].pct_change(fill_method=None) * 100
    home_return = frame["home"].pct_change(fill_method=None) * 100

    def _corr(a: pd.Series, b: pd.Series) -> float | None:
        pair = pd.concat([a, b], axis=1).dropna()
        if len(pair) < min_pairs:
            return None
        value = pair.iloc[:, 0].corr(pair.iloc[:, 1])
        return clean_float(value, 3)

    return {
        "sessions": int(len(frame)),
        "level_sd_pp": clean_float(premium.std(), 2),
        "daily_change_sd_pp": clean_float(changes.std(), 2),
        "autocorr_1d": clean_float(premium.autocorr(1), 3),
        "corr_change_vs_us_leg": _corr(changes, us_return),
        "corr_change_vs_home_leg": _corr(changes, home_return),
        # The one reading the timing gap makes useful rather than useless.
        "corr_us_today_vs_home_next": _corr(us_return, home_return.shift(-1)),
        "corr_us_today_vs_home_today": _corr(us_return, home_return),
    }


def _verdict(diag: dict, *, min_autocorrelation: float) -> dict:
    """Turn the diagnostics into a plain statement about what is usable."""
    change_sd = diag.get("daily_change_sd_pp")
    level_sd = diag.get("level_sd_pp")
    autocorr = diag.get("autocorr_1d")
    timing_dominated = (
        change_sd is not None and level_sd is not None and change_sd > level_sd
    ) or (autocorr is not None and autocorr < min_autocorrelation)
    return {
        "level_usable": True,
        "daily_change_usable": not timing_dominated,
        "statement": (
            "Daily changes in this premium are dominated by the gap between the two sessions, "
            "not by the dislocation itself: the day-to-day move is larger than the spread of the "
            "level and shows no persistence. Read the level, not the change."
            if timing_dominated
            else "Daily changes in this premium persist from one session to the next, so they are "
            "not purely a session-timing artifact."
        ),
    }


def _build_pair(spec: dict, log, settings: dict, chart_sessions: int) -> dict | None:
    us_ticker = str(spec["us_ticker"]).upper()
    home_ticker = str(spec["home_ticker"])
    fx_ticker = str(spec["fx_ticker"])
    ratio = float(spec["ratio"])

    # Same completed-session guard the rest of the page uses. Without it this
    # tab could date itself to a session still in progress while every other
    # tab showed the previous close -- one page, two "todays".
    closes = completed_sessions(
        yahoo.fetch_closes(
            [us_ticker, home_ticker, fx_ticker], period=str(settings["history_period"])
        )
    )
    missing = [t for t in (us_ticker, home_ticker, fx_ticker) if t not in closes.columns]
    if missing:
        log.add(
            SourceRecord(
                f"cross_listing_{us_ticker.lower()}",
                f"{spec.get('label', us_ticker)} cross-listing legs",
                "https://finance.yahoo.com",
                status="error",
                error="no data for: " + ", ".join(missing),
            )
        )
        return None

    frame = closes[[us_ticker, home_ticker, fx_ticker]].copy()
    frame.columns = ["us", "home", "fx"]
    frame = frame.dropna()
    if len(frame) < int(settings["min_sessions"]):
        return None

    # One US line represents `ratio` home shares, so the comparable price is
    # the home share converted to USD and scaled by that ratio. The ratio is
    # the depositary's, not one fitted to today's prices.
    frame["home_usd_equivalent"] = frame["home"] / frame["fx"] * ratio
    frame["premium_pct"] = (frame["us"] / frame["home_usd_equivalent"] - 1.0) * 100.0

    diag = _diagnostics(frame, min_pairs=int(settings["min_correlation_pairs"]))
    tail = frame.tail(chart_sessions)
    premium = frame["premium_pct"]
    latest = float(premium.iloc[-1])

    log.add(
        SourceRecord(
            f"cross_listing_{us_ticker.lower()}",
            f"{spec.get('label', us_ticker)} cross-listing legs",
            "https://finance.yahoo.com",
            to_iso_date(frame.index[-1]),
            rows=int(len(frame)),
        )
    )

    return {
        "label": spec.get("label", us_ticker),
        "us_ticker": us_ticker,
        "home_ticker": home_ticker,
        "home_market": spec.get("home_market"),
        "fx_ticker": fx_ticker,
        "fx_note": spec.get("fx_note"),
        "ratio": ratio,
        "ratio_text": f"1 {us_ticker} = {ratio:g} {home_ticker}",
        "ratio_source": spec.get("ratio_source"),
        "ratio_url": spec.get("ratio_url"),
        "home_close_lead_hours": spec.get("home_close_lead_hours"),
        "as_of": to_iso_date(frame.index[-1]),
        "first_session": to_iso_date(frame.index[0]),
        "latest": {
            "premium_pct": clean_float(latest, 2),
            "us_price": clean_float(frame["us"].iloc[-1], 2),
            "home_price": clean_float(frame["home"].iloc[-1], 2),
            "fx": clean_float(frame["fx"].iloc[-1], 2),
            "home_usd_equivalent": clean_float(frame["home_usd_equivalent"].iloc[-1], 2),
            "percentile": clean_float(float((premium <= latest).mean() * 100), 1),
            "mean_pct": clean_float(float(premium.mean()), 2),
        },
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
            "premium_pct": [clean_float(v, 3) for v in tail["premium_pct"].to_numpy()],
            "us": [clean_float(v, 2) for v in tail["us"].to_numpy()],
            "home_usd_equivalent": [clean_float(v, 2) for v in tail["home_usd_equivalent"].to_numpy()],
        },
        "diagnostics": diag,
        "verdict": _verdict(diag, min_autocorrelation=float(settings["min_autocorrelation"])),
    }


def build(ctx) -> dict:
    specs = list(ctx.config.get("cross_listing") or [])
    settings = ctx.config["cross_listing_diagnostics"]
    chart_sessions = period_sessions(ctx.config["periods"]["chart_window"])
    pairs = []
    for spec in specs:
        try:
            pair = _build_pair(spec, ctx.log, settings, chart_sessions)
        except Exception as exc:
            ctx.log.fail(f"cross_listing:{spec.get('us_ticker')}", exc)
            continue
        if pair:
            pairs.append(pair)

    return {
        "as_of": ctx.as_of,
        "pairs": pairs,
        "thresholds": dict(settings),
        "note": (
            "The premium is the US line's price against its home-market line converted at spot and "
            "scaled by the depositary ratio from the issuer's own filing. Two cautions travel with "
            "it. The home market closes hours before New York, so a same-date comparison sets a "
            "fresh US close against a stale home close -- the diagnostics below say how much of the "
            "daily movement that accounts for. And the ratio is never inferred from prices: doing "
            "that would force the premium to zero and draw a flat line that looks like data."
        ),
    }
