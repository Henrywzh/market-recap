"""FLOWS section B: who holds the index futures, by trader type.

The CFTC's Traders in Financial Futures report, weekly: each category's long
and short contracts on the Tuesday, published the following Friday. Four
contracts (S&P 500, Nasdaq-100, Russell 2000 and VIX futures), each with its
category positions as contracts, dollars and percent of open interest, the
three-year percentile, and a weekly history since 2010 for the chart.

A report is used only once it is published: its Tuesday plus three days must fall
on or before the session date.
The VIX future is valued at the spot VIX, which is an approximation of its price.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ..compute import cot as C
from ..sources import cftc, yahoo
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, describe_error, to_iso_date

# Positions are as of Tuesday and published on the Friday after.
RELEASE_LAG = timedelta(days=3)
HISTORY_START = "2010-01-01"
# Index closes are read from the session's own frames first; the rest come from
# Yahoo for this period, which covers the latest report's session.
PRICE_PERIOD = "2y"
# The trend check reads the S&P 500 model, the trend key in the positioning panel.
TREND_KEY = "SPX"
CONTRACT_SOURCE = "CFTC Traders in Financial Futures (futures only, weekly)"
PRICE_SOURCE = "Yahoo daily closes for the four index and volatility symbols"
YAHOO_HOME = "https://finance.yahoo.com"
# Categories that report traders per side; non-reportables have no such count.
TRADER_CATEGORIES = {"dealer", "asset_mgr", "lev_money", "other"}


def _num(value, digits: int | None = None) -> float | None:
    return clean_float(value, digits)


def _last(frame: pd.DataFrame, column: str) -> float | None:
    """Latest value of a column, or None if the dataset did not return the column."""
    if column not in frame.columns:
        return None
    clean = frame[column].dropna()
    if clean.empty or clean.index[-1] != frame.index[-1]:
        return None
    return _num(clean.iloc[-1])


def _closes(ctx, symbols: list[str]) -> dict[str, pd.Series]:
    """Daily closes by symbol: the session's own frames first, then Yahoo for the rest."""
    found: dict[str, pd.Series] = {}
    for symbol in symbols:
        for frame in (ctx.index_closes, ctx.etf_closes, ctx.closes):
            if isinstance(frame, pd.DataFrame) and symbol in frame.columns and frame[symbol].dropna().size:
                found[symbol] = frame[symbol]
                break
    missing = [s for s in symbols if s not in found]
    if missing:
        try:
            fetched = yahoo.fetch_closes(missing, period=PRICE_PERIOD)
        except Exception as exc:
            fetched = pd.DataFrame()
            ctx.log.add(SourceRecord("cftc_prices", PRICE_SOURCE, YAHOO_HOME, status="error",
                                     error=describe_error(exc)))
        for symbol in missing:
            if symbol in fetched.columns and fetched[symbol].dropna().size:
                found[symbol] = fetched[symbol]
    still = [s for s in symbols if s not in found]
    if still:
        # A missing close leaves only that contract's dollar figures empty.
        ctx.log.add(SourceRecord("cftc_prices", PRICE_SOURCE, YAHOO_HOME, status="partial",
                                 error=f"no closes for {', '.join(still)}"))
    elif missing:
        ctx.log.add(SourceRecord("cftc_prices", PRICE_SOURCE, YAHOO_HOME,
                                 to_iso_date(max(found[s].dropna().index[-1] for s in symbols)),
                                 rows=len(symbols)))
    return found


def _categories(rows: pd.DataFrame, multiplier: float, price: float | None, oi: pd.Series) -> tuple[list[dict], dict[str, pd.Series]]:
    out: list[dict] = []
    shares: dict[str, pd.Series] = {}
    for key, label in C.CATEGORIES:
        net = C.net(rows[f"{key}_long"], rows[f"{key}_short"])
        pct = C.net_pct_oi(net, oi)
        shares[key] = pct
        now = _num(net.iloc[-1])
        traders = None
        if key in TRADER_CATEGORIES:
            traders = {"long": _last(rows, f"traders_{key}_long"), "short": _last(rows, f"traders_{key}_short")}
        out.append({
            "key": key, "label": label,
            "long": _last(rows, f"{key}_long"), "short": _last(rows, f"{key}_short"),
            "net": now,
            "net_usd_bn": _num(C.dollar_net_bn(now, multiplier, price), 2),
            "net_pct_oi": _num(pct.iloc[-1], 2),
            "change_1w": _num(C.change_1w(net), 0),
            "pctile_3y": _num(C.percentile_3y(pct), 1),
            "z_3y": _num(C.z_3y(pct), 2),
            "traders": traders,
        })
    return out, shares


def _contract(spec: dict, rows: pd.DataFrame, close: pd.Series | None) -> tuple[dict, pd.Series]:
    """One contract's latest report, its history, and the leveraged-money share series."""
    latest = rows.index[-1]
    priced = C.price_on(close, latest) if close is not None else None
    price_date, price = priced if priced else (None, None)
    multiplier = spec["multiplier"]
    categories, shares = _categories(rows, multiplier, price, rows["open_interest"])
    contract = {
        "key": spec["key"], "label": spec["label"], "code": spec["code"], "index": spec["index_label"],
        "multiplier": multiplier,
        "report_date": to_iso_date(latest),
        "released": to_iso_date(latest + RELEASE_LAG),
        "open_interest": _num(rows["open_interest"].iloc[-1]),
        "price": {"symbol": spec["symbol"], "date": to_iso_date(price_date), "close": _num(price, 2)},
        "approximate": bool(spec.get("approximate")),
        "categories": categories,
        "history": {
            "dates": [d.strftime("%Y-%m-%d") for d in rows.index],
            "categories": {key: [_num(v, 2) for v in shares[key]] for key, _ in C.CATEGORIES},
        },
    }
    return contract, shares


# The categories set against the trend model, the one that moves with it first. Over
# 2010-2026, asset managers' four-week change in E-mini net % OI correlates about
# +0.5 with the model's; leveraged money's about -0.4: it is mostly the other side of
# asset managers' futures (basis and relative-value books), not the trend followers.
CHECK_CATEGORIES = ("asset_mgr", "lev_money")


def _trend_check(inputs: dict, shares: dict) -> dict:
    """Asset managers' and leveraged money's net % OI in E-mini S&P 500 against the S&P 500 trend model's position."""
    positioning = inputs.get("positioning")
    if not positioning:
        return {"unavailable": "positioning panel not built this session"}
    trend = next((t for t in positioning.get("trend") or [] if t.get("key") == TREND_KEY), None)
    model = (trend or {}).get("model")
    if not model:
        return {"unavailable": "no S&P 500 trend model this session"}
    history = model["history"]["position"]
    if not history.get("dates"):
        return {"unavailable": "trend model has no history"}
    position = pd.Series(history["values"], index=pd.to_datetime(history["dates"]), dtype=float)
    labels = dict(C.CATEGORIES)
    rows = []
    for key in CHECK_CATEGORIES:
        check = C.trend_check(shares[key], position)
        rows.append({"key": key, "label": labels[key], "n": check["n"],
                     "corr_levels": _num(check["corr_levels"], 2),
                     "corr_changes_4w": _num(check["corr_changes_4w"], 2)})
    return {
        "window_weeks": C.WINDOW,
        "categories": rows,
        "position_as_of": to_iso_date(position.index[-1]),
    }


def build(ctx, inputs: dict | None = None) -> dict:
    inputs = inputs or {}
    codes = [spec["code"] for spec in C.CONTRACTS]
    try:
        frame = cftc.fetch_tff_categories(codes, start=HISTORY_START)
    except Exception as exc:
        reason = describe_error(exc)[:ERROR_DETAIL_CHARS]
        ctx.log.add(SourceRecord("cftc_tff_categories", CONTRACT_SOURCE, cftc.HOME_URL, status="error", error=reason))
        return {"unavailable": reason}

    # Only reports known at the session: the Friday after the Tuesday must be on or before as_of.
    if ctx.as_of:
        frame = frame[frame["date"] + RELEASE_LAG <= pd.Timestamp(ctx.as_of)]
    if frame.empty:
        return {"unavailable": "no published CFTC report at this session"}
    latest = frame["date"].max()
    ctx.log.add(SourceRecord("cftc_tff_categories", CONTRACT_SOURCE, cftc.HOME_URL, to_iso_date(latest),
                             rows=int(len(frame)), policy="weekly_release"))

    closes = _closes(ctx, sorted({spec["symbol"] for spec in C.CONTRACTS}))
    contracts: list[dict] = []
    trend_check = None
    for spec in C.CONTRACTS:
        rows = frame[frame["code"] == spec["code"]].set_index("date").sort_index()
        if rows.empty:
            contracts.append({"key": spec["key"], "label": spec["label"], "code": spec["code"],
                              "unavailable": "no published report for this contract"})
            continue
        contract, shares = _contract(spec, rows, closes.get(spec["symbol"]))
        contracts.append(contract)
        if spec["key"] == "es":
            trend_check = _trend_check(inputs, shares)

    return {
        "as_of": ctx.as_of,
        "report_date": to_iso_date(latest),
        "released": to_iso_date(latest + RELEASE_LAG),
        "history_start": HISTORY_START,
        "lag": "Tuesday positions, known the following Friday",
        "contracts": contracts,
        "trend_check": trend_check,
        "trend_check_note": "A check, not a validation: the trend model is a daily price rule, and the "
                            "Tuesday reports are matched to its last reading on or before each date. "
                            "Asset managers are the category that has moved with it; leveraged money has "
                            "mostly taken the other side.",
    }
