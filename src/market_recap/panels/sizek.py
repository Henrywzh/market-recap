"""RELATIVE VALUE -> SIZE K: one arm of a pair against the other.

For each configured pair (the S&P 500 and Nasdaq-100 cap-weighted against
equal-weight, large against small and mid caps, the FTSE 100 against the
FTSE 250, and style pairs such as value against growth, staples against the
market, low volatility against the market): the two arms' price series and
their ratio with where today's ratio sits among its own weeks, returns by
window, the rolling one-year return gap and how often and how long the first
arm led, and each calendar year's gap. Each pair names its arms (``big_arm`` /
``small_arm``, default LARGE / SMALL).
Prices only: a fund's own P/E is not a measured figure here (no look-through
to its holdings is kept), and the page says so. See compute.sizek.
A pair with ``source = "french"`` takes its arms from Kenneth French's daily
portfolio returns instead of Yahoo: factor series (the Fama-French value and
size sorts), not funds, and published monthly with a lag. See sources.french.
"""

from __future__ import annotations

import pandas as pd

from ..compute import kshape as K
from ..compute import sizek as S
from ..config import PERIOD_TRADING_DAYS
from ..context import YAHOO_URL
from ..sources import french, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date
from .kshape import _series_payload

NOTES = (
    "Prices only. Whether either arm is dearer than the other on earnings is not measured here: a fund's reported P/E is a snapshot "
    "of its holdings today, not a history, and none is kept.",
    "A ratio's percentile is where today's value sits among its own past weeks. A ratio that has risen for years says only that "
    "the first arm has led, not that it must turn.",
    "Some pairs differ in how they are built: the equal-weight funds rebalance on a schedule and hold more small and mid-sized names than "
    "the cap-weighted ones, so part of such a gap is construction, not only the names.",
)


FRENCH_LABEL = "Kenneth French's daily size and book-to-market portfolios (value-weighted)"
# A French arm is an equal mix of the daily returns of the portfolios it names,
# compounded from 100: VALUE and GROWTH are HML's own two halves, so their
# ratio follows HML's compounded return.
FRENCH_ARMS = {
    "FF_VALUE": ("SMALL HiBM", "BIG HiBM"),
    "FF_GROWTH": ("SMALL LoBM", "BIG LoBM"),
    "FF_BIG_VALUE": ("BIG HiBM",),
    "FF_BIG_GROWTH": ("BIG LoBM",),
}


def _french_arms(returns: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Each French arm as a price index over the window from ``start`` to ``end``.
    A missing return in a portfolio that an arm uses raises rather than being
    averaged away: the arm's history would then describe fewer names on that day."""
    used = sorted({leg for legs in FRENCH_ARMS.values() for leg in legs})
    if returns[used].isna().any().any():
        raise ValueError("missing daily returns in the French portfolios")
    index = {symbol: 100 * (1 + returns[list(legs)].mean(axis=1)).cumprod() for symbol, legs in FRENCH_ARMS.items()}
    frame = pd.DataFrame(index)
    return frame[(frame.index >= start) & (frame.index <= end)]


def _french_series(ctx, years: int) -> tuple[pd.DataFrame, SourceRecord]:
    """The French arms for the SIZE K window, and the record of the fetch. A
    failed fetch returns no columns, so its pairs read as having no prices."""
    end = pd.Timestamp(ctx.as_of)
    try:
        returns = french.fetch_value_weighted_daily()
    except Exception as exc:  # noqa: BLE001 - a missing factor file must not take the Yahoo pairs down with it
        return pd.DataFrame(), SourceRecord("french_portfolios", FRENCH_LABEL, french.URL, status="error",
                                            error=describe_error(exc), policy="monthly_release")
    try:
        arms = _french_arms(returns, end - pd.DateOffset(years=years), end)
    except Exception as exc:  # noqa: BLE001 - the same: the record says why, the rest of the page still builds
        return pd.DataFrame(), SourceRecord("french_portfolios", FRENCH_LABEL, french.URL, to_iso_date(returns.index[-1]),
                                            rows=int(len(returns)), status="error", error=describe_error(exc),
                                            policy="monthly_release")
    return arms, SourceRecord("french_portfolios", FRENCH_LABEL, french.URL, to_iso_date(returns.index[-1]),
                              rows=int(len(returns)), policy="monthly_release")


def _view(pair: dict, closes: pd.DataFrame, cfg: dict, periods: dict[str, int], gap_sessions: int) -> dict:
    big, small = pair["big"], pair["small"]
    out: dict = {"key": pair["key"], "label": pair["label"], "note": pair.get("note"), "big": big, "small": small,
                 "big_name": pair.get("big_name", big), "small_name": pair.get("small_name", small),
                 "big_arm": pair.get("big_arm", "LARGE"), "small_arm": pair.get("small_arm", "SMALL"),
                 "price_index": bool(pair.get("price_index")), "price": None}
    missing = [s for s in (big, small) if s not in closes.columns or closes[s].dropna().empty]
    out["no_prices"] = missing
    if missing:
        return out
    both = closes[[big, small]].dropna().sort_index()
    if len(both) < 2:
        return out
    # Both rebased to 100 on the first day both are priced, so the ratio starts at 1.
    rebased = 100 * both / both.iloc[0]
    ratio = K.ratio(rebased[big], rebased[small])
    weekly = ratio.groupby(ratio.index.to_period("W-FRI")).tail(1)
    gap = S.rolling_gap(both[big], both[small], gap_sessions)
    extremes = S.ratio_extremes(ratio)
    years = int(cfg["history_years"])
    frame = pd.DataFrame({"big": rebased[big], "small": rebased[small], "ratio": ratio})
    out["price"] = {
        **_series_payload(frame, years),
        "since": to_iso_date(both.index[0]), "through": to_iso_date(both.index[-1]), "sessions": int(len(both)),
        "ratio_now": clean_float(ratio.iloc[-1], 3),
        "ratio_percentile": clean_float(K.percentile(weekly, float(ratio.iloc[-1])), 0),
        "extremes": None if extremes is None else {
            "high": clean_float(extremes["high"], 3), "high_date": to_iso_date(extremes["high_date"]),
            "low": clean_float(extremes["low"], 3), "low_date": to_iso_date(extremes["low_date"]),
            "from_high_pct": clean_float(extremes["from_high_pct"], 1), "from_low_pct": clean_float(extremes["from_low_pct"], 1)},
        "spreads": [{k: (clean_float(v, 1) if k != "period" else v) for k, v in r.items()}
                    for r in K.spread_table(rebased[big], rebased[small], periods)],
    }
    out["gap"] = None
    if len(gap) >= 2:
        weekly_gap = gap.groupby(gap.index.to_period("W-FRI")).tail(1)
        out["gap"] = {
            **_series_payload(pd.DataFrame({"gap": gap}), years, 1),
            "window": cfg["gap_period"], "now": clean_float(gap.iloc[-1], 1),
            "percentile": clean_float(K.percentile(weekly_gap, float(gap.iloc[-1])), 0),
            "share_big_ahead": clean_float(S.share_of_windows(gap), 0),
            "longest_big": int(S.longest_run(gap) // 5), "longest_small": int(S.longest_run(gap, positive=False) // 5),
            "windows": int(len(gap)), "first": to_iso_date(gap.index[0]),
        }
    out["years"] = [{k: (clean_float(v, 1) if k in ("big", "small", "gap") else v) for k, v in r.items()}
                    for r in S.calendar_years(both[big], both[small])]
    return out


def _from_french(pair: dict) -> bool:
    return pair.get("source") == "french"


def build(ctx) -> dict:
    cfg = ctx.config["sizek"]
    pairs = cfg["pairs"]
    wanted = sorted({s for p in pairs if not _from_french(p) for s in (p["big"], p["small"])})
    closes = yahoo.fetch_closes(wanted, period=f"{int(cfg['history_years'])}y")
    missing = sorted(set(wanted) - set(closes.columns))
    ctx.log.add(SourceRecord("sizek_prices", "Closes for the SIZE K pairs: cap-weighted and equal-weight funds, size, style and index pairs", YAHOO_URL,
                             to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if not missing else "partial", error=f"no data: {', '.join(missing)}" if missing else None))
    if closes.empty:
        raise RuntimeError("no prices for the size-K pairs")
    closes = closes[closes.index <= pd.Timestamp(ctx.as_of)]
    french_wanted = sorted({s for p in pairs if _from_french(p) for s in (p["big"], p["small"])})
    if french_wanted:
        arms, record = _french_series(ctx, int(cfg["history_years"]))
        ctx.log.add(record)
        closes = closes.join(arms, how="outer")
        missing = sorted(set(missing) | (set(french_wanted) - set(arms.columns)))
    periods = {label: PERIOD_TRADING_DAYS[label] for label in cfg["price_periods"]}
    gap_sessions = PERIOD_TRADING_DAYS[cfg["gap_period"]]
    views = [_view(p, closes, cfg, periods, gap_sessions) for p in pairs]
    return {
        "as_of": ctx.as_of,
        "settings": {k: cfg[k] for k in ("history_years", "price_periods", "gap_period")},
        "inputs": {"prices_through": to_iso_date(closes.index[-1]), "no_prices": missing},
        "views": views,
        "notes": list(NOTES),
    }
