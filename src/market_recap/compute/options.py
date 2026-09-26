"""Option-chain summaries for the nightly snapshot.

Yahoo's per-contract ``impliedVolatility`` is not used: it is computed from
the last trade, which for a thin strike can be hours old, and deep
in-the-money quotes come back with single-digit vols. Every vol here is
solved from the bid/ask mid of an out-of-the-money contract under Black-76,
against a forward implied by put-call parity at the strike nearest spot. The
forward absorbs dividends and borrow, so no dividend assumption is needed.

A figure that cannot be solved honestly (no two-sided quote, a mid outside
no-arbitrage bounds, no strike on one side of the target delta) is ``None``.
"""

from __future__ import annotations

from datetime import date
import math
from typing import Iterable, Mapping, Sequence

CALENDAR_DAYS_PER_YEAR = 365.0
# Solver bounds on volatility. Anything outside is a bad quote, not a market.
VOL_FLOOR = 0.005
VOL_CAP = 5.0
SOLVER_ITERATIONS = 100
SOLVER_TOLERANCE = 1e-7
# A quote is two-sided when both sides are positive and the spread is no wider
# than this share of the mid. Wider than that, the mid is a guess.
MAX_RELATIVE_SPREAD = 0.5
TARGET_DELTA = 0.25


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76(forward: float, strike: float, years: float, vol: float, discount: float, *, call: bool) -> float:
    """Undiscounted-forward Black price, discounted by ``discount``."""
    if years <= 0 or vol <= 0:
        intrinsic = max(forward - strike, 0.0) if call else max(strike - forward, 0.0)
        return discount * intrinsic
    sd = vol * math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if call:
        return discount * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2))
    return discount * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1))


def black76_delta(forward: float, strike: float, years: float, vol: float, *, call: bool) -> float:
    """Forward delta: N(d1) for a call, N(d1) - 1 for a put."""
    sd = vol * math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * sd * sd) / sd
    return _norm_cdf(d1) if call else _norm_cdf(d1) - 1.0


def implied_vol(price: float, forward: float, strike: float, years: float, discount: float, *, call: bool) -> float | None:
    """Bisection on Black-76. ``None`` when the price is outside the bounds a
    vol in [VOL_FLOOR, VOL_CAP] can produce."""
    if not (price > 0 and forward > 0 and strike > 0 and years > 0 and discount > 0):
        return None
    low, high = VOL_FLOOR, VOL_CAP
    p_low = black76(forward, strike, years, low, discount, call=call)
    p_high = black76(forward, strike, years, high, discount, call=call)
    if not (p_low <= price <= p_high):
        return None
    for _ in range(SOLVER_ITERATIONS):
        mid = 0.5 * (low + high)
        if black76(forward, strike, years, mid, discount, call=call) < price:
            low = mid
        else:
            high = mid
        if high - low < SOLVER_TOLERANCE:
            break
    return 0.5 * (low + high)


def mid_quote(bid, ask) -> float | None:
    """Mid of a usable two-sided quote, else ``None``."""
    try:
        bid, ask = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(bid) and math.isfinite(ask)) or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = 0.5 * (bid + ask)
    if (ask - bid) / mid > MAX_RELATIVE_SPREAD:
        return None
    return mid


def select_expiries(expiries: Iterable[str], today: date, *, min_days: int, targets: Sequence[int]) -> list[str]:
    """The nearest expiry at least ``min_days`` out, plus the expiries either
    side of each target (calendar days), so a constant-maturity vol can be
    interpolated later rather than approximated now."""
    dated = sorted((date.fromisoformat(e), e) for e in expiries)
    ahead = [(d, e) for d, e in dated if (d - today).days >= min_days]
    if not ahead:
        return []
    chosen = {ahead[0][1]}
    for target in targets:
        before = [e for d, e in ahead if (d - today).days <= target]
        after = [e for d, e in ahead if (d - today).days >= target]
        if before:
            chosen.add(before[-1])
        if after:
            chosen.add(after[0])
    return sorted(chosen)


def _rows(contracts: Iterable[Mapping]) -> dict[float, Mapping]:
    out = {}
    for row in contracts:
        try:
            strike = float(row["strike"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(strike) and strike > 0:
            out[strike] = row
    return out


def _total(contracts: Iterable[Mapping], key: str) -> int | None:
    values = []
    for row in contracts:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return int(sum(values)) if values else None


def _interpolate_at_delta(points: list[tuple[float, float]], target: float) -> float | None:
    """Linear in delta between the two solved strikes that bracket it."""
    points = sorted(points)
    for (d0, v0), (d1, v1) in zip(points, points[1:]):
        if d0 <= target <= d1:
            if d1 == d0:
                return v0
            return v0 + (v1 - v0) * (target - d0) / (d1 - d0)
    return None


def summarize_expiry(
    calls: Sequence[Mapping],
    puts: Sequence[Mapping],
    *,
    spot: float,
    expiry: date,
    today: date,
    rate: float,
) -> dict:
    """One row per underlying and expiry. ``rate`` is a continuously
    compounded decimal; it only discounts, the forward comes from parity."""
    days = (expiry - today).days
    out: dict = {
        "expiry": expiry.isoformat(), "days": days, "spot": spot,
        "forward": None, "atm_strike": None, "atm_iv": None,
        "straddle_mid": None, "straddle_pct": None,
        "put_25d_iv": None, "call_25d_iv": None,
        "call_oi": _total(calls, "openInterest"), "put_oi": _total(puts, "openInterest"),
        "call_volume": _total(calls, "volume"), "put_volume": _total(puts, "volume"),
        "quoted_strikes": 0, "note": None,
    }
    # Same-day expiries are recorded for open interest only; a vol with hours
    # left is dominated by the time-of-day convention, not by the market.
    years = max(days, 0) / CALENDAR_DAYS_PER_YEAR
    if days <= 0 or not (spot and spot > 0):
        out["note"] = "expires today" if days <= 0 else "no spot"
        return out
    discount = math.exp(-rate * years)
    call_rows, put_rows = _rows(calls), _rows(puts)
    both = sorted(set(call_rows) & set(put_rows))
    quoted = [
        k for k in both
        if mid_quote(call_rows[k].get("bid"), call_rows[k].get("ask")) is not None
        and mid_quote(put_rows[k].get("bid"), put_rows[k].get("ask")) is not None
    ]
    out["quoted_strikes"] = len(quoted)
    if not quoted:
        out["note"] = "no strike quoted on both sides"
        return out

    atm = min(quoted, key=lambda k: abs(k - spot))
    call_mid = mid_quote(call_rows[atm].get("bid"), call_rows[atm].get("ask"))
    put_mid = mid_quote(put_rows[atm].get("bid"), put_rows[atm].get("ask"))
    forward = atm + (call_mid - put_mid) / discount
    if not forward > 0:
        out["note"] = "parity forward not positive"
        return out
    out.update({
        "forward": forward, "atm_strike": atm,
        "straddle_mid": call_mid + put_mid, "straddle_pct": (call_mid + put_mid) / spot * 100.0,
    })

    atm_vols = [
        v for v in (
            implied_vol(call_mid, forward, atm, years, discount, call=True),
            implied_vol(put_mid, forward, atm, years, discount, call=False),
        ) if v is not None
    ]
    out["atm_iv"] = sum(atm_vols) / len(atm_vols) if atm_vols else None

    # Out-of-the-money wings only: an in-the-money mid is mostly intrinsic
    # value, and a cent of spread there moves the solved vol by points.
    put_points, call_points = [], []
    for strike, row in put_rows.items():
        if strike >= forward:
            continue
        mid = mid_quote(row.get("bid"), row.get("ask"))
        vol = implied_vol(mid, forward, strike, years, discount, call=False) if mid else None
        if vol is not None:
            put_points.append((-black76_delta(forward, strike, years, vol, call=False), vol))
    for strike, row in call_rows.items():
        if strike <= forward:
            continue
        mid = mid_quote(row.get("bid"), row.get("ask"))
        vol = implied_vol(mid, forward, strike, years, discount, call=True) if mid else None
        if vol is not None:
            call_points.append((black76_delta(forward, strike, years, vol, call=True), vol))
    out["put_25d_iv"] = _interpolate_at_delta(put_points, TARGET_DELTA)
    out["call_25d_iv"] = _interpolate_at_delta(call_points, TARGET_DELTA)
    return out


def trim_contracts(contracts: Sequence[Mapping], spot: float, band: float) -> list[Mapping]:
    """Contracts with a strike within ``band`` (a fraction) of spot."""
    low, high = spot * (1 - band), spot * (1 + band)
    return [row for row in contracts if low <= float(row.get("strike") or 0) <= high]
