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
"""

from __future__ import annotations

import pandas as pd

from ..compute import kshape as K
from ..compute import sizek as S
from ..config import PERIOD_TRADING_DAYS
from ..context import YAHOO_URL
from ..sources import yahoo
from ..util import SourceRecord, clean_float, to_iso_date
from .kshape import _series_payload

NOTES = (
    "Prices only. Whether either arm is dearer than the other on earnings is not measured here: a fund's reported P/E is a snapshot "
    "of its holdings today, not a history, and none is kept.",
    "A ratio's percentile is where today's value sits among its own past weeks. A ratio that has risen for years says only that "
    "the first arm has led, not that it must turn.",
    "Some pairs differ in how they are built: the equal-weight funds rebalance on a schedule and hold more small and mid-sized names than "
    "the cap-weighted ones, so part of such a gap is construction, not only the names.",
)


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
        "since": to_iso_date(both.index[0]), "sessions": int(len(both)),
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


def build(ctx) -> dict:
    cfg = ctx.config["sizek"]
    pairs = cfg["pairs"]
    wanted = sorted({s for p in pairs for s in (p["big"], p["small"])})
    closes = yahoo.fetch_closes(wanted, period=f"{int(cfg['history_years'])}y")
    missing = sorted(set(wanted) - set(closes.columns))
    ctx.log.add(SourceRecord("sizek_prices", "Closes for the SIZE K pairs: cap-weighted and equal-weight funds, size, style and index pairs", YAHOO_URL,
                             to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if not missing else "partial", error=f"no data: {', '.join(missing)}" if missing else None))
    if closes.empty:
        raise RuntimeError("no prices for the size-K pairs")
    closes = closes[closes.index <= pd.Timestamp(ctx.as_of)]
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
