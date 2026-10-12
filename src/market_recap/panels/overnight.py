"""INDICES -> OVERNIGHT VS INTRADAY: where each fund's return was made.

Every session split into the move from the previous close to the open and
the move from the open to the close (compute.overnight), for the funds in
``[overnight]``: the growth of each leg held alone since the fund's first
day, each leg's return by window and by calendar year, and the last ten
sessions. A description, not a strategy; see the notes.
"""

from __future__ import annotations

import pandas as pd

from ..compute import overnight as O
from ..config import PERIOD_TRADING_DAYS
from ..context import YAHOO_URL
from ..sources import yahoo
from ..util import SourceRecord, clean_float, to_iso_date

NOTES = (
    "Overnight is the previous close to the open; intraday is the open to the close. The two multiply to the session's total return; "
    "the dividend sits in the overnight leg, because the price drops by it at the open of the ex-date.",
    "A description of where the gains came from, not a strategy: holding only overnight means buying every close and selling every open, "
    "and those trading costs are not counted.",
    "The open is the fund's first trade of the session, which can sit away from the index's own opening level.",
)
DAILY_SESSIONS = PERIOD_TRADING_DAYS["2Y"]
STALE_OPEN_PCT = 5.0   # a year with more of its opens equal to the previous close is flagged


def _path(frame: pd.DataFrame, digits: int = 4) -> dict:
    return {"dates": [to_iso_date(d) for d in frame.index],
            **{leg: [clean_float(v, digits) for v in frame[leg]] for leg in ("overnight", "intraday", "total")}}


def _view(spec: dict, adjusted: pd.DataFrame, prices: pd.DataFrame, opens: pd.DataFrame, as_of: str, windows: list[str]) -> dict:
    symbol = spec["symbol"]
    out = {"symbol": symbol, "label": spec.get("label", symbol), "available": False}
    if any(symbol not in f.columns for f in (adjusted, prices, opens)):
        return out
    cut = pd.Timestamp(as_of)
    daily = O.legs(adjusted[symbol][adjusted.index <= cut], prices[symbol], opens[symbol])
    if len(daily) < 2:
        return out
    grown = O.growth(daily)
    weekly = grown.groupby(grown.index.to_period("W-FRI")).tail(1)
    recent = O.growth(daily.tail(DAILY_SESSIONS))
    stale = O.stale_opens(opens[symbol], prices[symbol])
    rows = []
    for label in windows:
        w = O.window(daily, None if label == "MAX" else PERIOD_TRADING_DAYS[label])
        if w is None:
            continue
        rows.append({"period": label, "from": to_iso_date(w.pop("from")), **{k: (v if k == "sessions" else clean_float(v, 2)) for k, v in w.items()}})
    return {
        **out, "available": True,
        "since": to_iso_date(daily.index[0]), "sessions": int(len(daily)), "through": to_iso_date(daily.index[-1]),
        "weekly": _path(weekly, 3),
        "daily": _path(recent),
        "windows": rows,
        "years": [{k: (clean_float(v, 2) if isinstance(v, float) else v) for k, v in r.items()} for r in O.calendar_years(daily)],
        "last": [{"date": to_iso_date(d), "overnight": clean_float(r["overnight"] * 100, 2), "intraday": clean_float(r["intraday"] * 100, 2),
                  "total": clean_float(r["total"] * 100, 2)} for d, r in daily.tail(10).iloc[::-1].iterrows()],
        "stale_open_years": {str(y): clean_float(v, 0) for y, v in stale.items() if v > STALE_OPEN_PCT},
    }


def build(ctx) -> dict:
    cfg = ctx.config["overnight"]
    specs = cfg["funds"]
    wanted = [s["symbol"] for s in specs]
    adjusted = yahoo.fetch_closes(wanted, period="max", need_ohlcv=True)
    prices = yahoo.fetch_prices("max")
    opens = yahoo.fetch_ohlcv_cache("max")["open"]
    if not opens.empty:
        opens.index = pd.to_datetime(opens.index).tz_localize(None)
    missing = [s for s in wanted if any(s not in f.columns for f in (adjusted, prices, opens))]
    # Dated by the last session the split uses, not a bar of the session in progress.
    used = adjusted.index[adjusted.index <= pd.Timestamp(ctx.as_of)]
    ctx.log.add(SourceRecord("overnight_prices", "Opens and closes since inception for the overnight / intraday split", YAHOO_URL,
                             to_iso_date(used[-1]) if len(used) else None, rows=len(wanted) - len(missing),
                             status="ok" if not missing else "partial", error=f"no opens or closes: {', '.join(missing)}" if missing else None))
    views = [_view(s, adjusted, prices, opens, ctx.as_of, cfg["windows"]) for s in specs]
    if not any(v["available"] for v in views):
        raise RuntimeError("no fund has both opens and closes for the overnight split")
    return {"as_of": ctx.as_of, "settings": {"windows": cfg["windows"]}, "views": views, "notes": list(NOTES)}
