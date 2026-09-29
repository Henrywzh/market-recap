"""POSITIONING view: who is forced to trade.

Two readings, each from its own public source:

- Trend followers: a rules-based proxy for systematic trend books on the
  S&P 500 and Nasdaq-100 (compute.positioning), with the price at which each
  lookback flips tomorrow.
- Short interest: FINRA's twice-monthly consolidated short interest for the
  index members, the watchlist and the broad ETFs -- days to cover, the
  change since the last round, and the members' total short value over a
  year of rounds.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..compute import positioning as P
from ..sources import finra
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, history_payload, to_iso_date


def _trend(ctx, spec, settings) -> dict | None:
    close = ctx.index_closes[spec.symbol].dropna() if spec.symbol in ctx.index_closes else pd.Series(dtype=float)
    if len(close) < max(P.LOOKBACKS.values()) + 2:
        return None
    score = P.trend_score(close)
    now = float(score.iloc[-1])
    scorecard_start = close.index[-1] - pd.DateOffset(years=int(settings.get("history_years", 10)))
    scorecard_close = close[close.index > scorecard_start]
    scorecard_score = score.reindex(scorecard_close.index)
    return {
        "key": spec.key, "label": spec.label, "symbol": spec.symbol,
        "as_of": to_iso_date(close.index[-1]),
        "close": clean_float(close.iloc[-1], 2),
        "score": clean_float(now, 2),
        "state": P.label(now),
        "flips": [{k: (clean_float(v, 2) if isinstance(v, float) else v) for k, v in row.items()} for row in P.flip_levels(close)],
        "averages": [{k: (clean_float(v, 2) if isinstance(v, float) else v) for k, v in row.items()} for row in P.ma_levels(close)],
        "history": {
            "score": history_payload(score, years=int(settings.get("history_years", 10)), digits=2),
            "close": history_payload(close, years=int(settings.get("history_years", 10)), digits=2),
        },
        # Chart history above intentionally thins older observations to
        # weekly. Forward outcomes need actual consecutive trading sessions.
        "scorecard_history": {
            "dates": [d.strftime("%Y-%m-%d") for d in scorecard_close.index],
            "score": [clean_float(v, 2) for v in scorecard_score],
            "close": [clean_float(v, 2) for v in scorecard_close],
        },
    }


def _universe(ctx, settings) -> tuple[dict[str, dict], list[str]]:
    """FINRA symbol -> {ticker, name, group}; members first, then the ETFs."""
    names: dict[str, dict] = {}
    for spec in ctx.indices:
        for row in ctx.priced(spec.key).itertuples():
            entry = names.setdefault(finra.finra_symbol(row.yahoo_symbol), {
                "ticker": row.yahoo_symbol, "name": str(row.name).title(), "sector": getattr(row, "sector", None),
                "indices": [],
            })
            entry["indices"].append(spec.key)
    for row in (ctx.watchlist.itertuples() if not ctx.watchlist.empty and "ticker" in ctx.watchlist else []):
        names.setdefault(finra.finra_symbol(str(row.ticker)), {"ticker": str(row.ticker), "name": None, "sector": None, "indices": ["watchlist"]})
    etfs = [str(t) for t in settings.get("short_interest_etfs", [])]
    for ticker in etfs:
        names.setdefault(finra.finra_symbol(ticker), {"ticker": ticker, "name": None, "sector": "ETF", "indices": ["etf"]})
    return names, etfs


def _price_on(frame: pd.DataFrame, ticker: str, day: pd.Timestamp) -> float | None:
    if ticker not in frame.columns:
        return None
    series = frame[ticker].dropna()
    series = series[series.index <= day]
    return float(series.iloc[-1]) if not series.empty else None


def _short_interest(ctx, settings) -> dict:
    names, etfs = _universe(ctx, settings)
    rounds = int(settings.get("short_interest_rounds", 24))
    until = date.fromisoformat(ctx.as_of) if ctx.as_of else date.today()
    frames = []
    for nominal in finra.candidate_dates(until, rounds + 1):
        frame = finra.fetch_round(nominal, sorted(names))
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise ValueError("FINRA returned no short-interest round")
    data = pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "settlement_date"], keep="first")
    data = data[data["symbol"].isin(names)]
    dates = sorted(data["settlement_date"].unique())[-rounds:]
    data = data[data["settlement_date"].isin(dates)]
    latest_day = dates[-1]
    prices = pd.concat([ctx.closes, ctx.etf_closes], axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]

    def row(r) -> dict:
        info = names[r.symbol]
        price = _price_on(prices, info["ticker"], r.settlement_date)
        return {
            "ticker": info["ticker"], "name": info["name"], "sector": info["sector"], "indices": info["indices"],
            "shares_short": clean_float(r.shares_short, 0),
            "change_pct": clean_float(r.change_pct, 2),
            "days_to_cover": clean_float(r.days_to_cover, 2),
            "short_value": clean_float(r.shares_short * price, 0) if price else None,
            "average_daily_volume": clean_float(r.average_daily_volume, 0),
        }

    latest = [row(r) for r in data[data["settlement_date"] == latest_day].itertuples()]
    members = [r for r in latest if "etf" not in r["indices"] and "watchlist" not in r["indices"]]
    # Each member's short shares over the rounds shown, for the table's sparkline.
    history = data.pivot_table(index="settlement_date", columns="symbol", values="shares_short", aggfunc="last")
    spark = {names[s]["ticker"]: [clean_float(v, 0) for v in history[s].to_numpy()] for s in history.columns}

    # The members' total short value per round, priced at each settlement date's close.
    spx = {finra.finra_symbol(t) for t in ctx.symbols_for(ctx.primary.key)}
    aggregate = []
    for day in dates:
        rows = data[(data["settlement_date"] == day) & data["symbol"].isin(spx)]
        value = sum((r.shares_short * p) for r in rows.itertuples()
                    if (p := _price_on(prices, names[r.symbol]["ticker"], day)))
        aggregate.append({
            "date": to_iso_date(day),
            "short_value_bn": clean_float(value / 1e9, 1),
            "median_days_to_cover": clean_float(rows["days_to_cover"].median(), 2),
            "names": int(len(rows)),
        })

    top = int(settings.get("short_interest_top", 15))
    by = lambda key, reverse=True: sorted((r for r in members if r[key] is not None), key=lambda r: r[key], reverse=reverse)[:top]
    return {
        "settlement_date": to_iso_date(latest_day),
        "previous_settlement_date": to_iso_date(dates[-2]) if len(dates) > 1 else None,
        "rounds": [to_iso_date(d) for d in dates],
        "aggregate": aggregate,
        "etfs": sorted((r for r in latest if r["ticker"] in etfs), key=lambda r: etfs.index(r["ticker"])),
        "most_days_to_cover": by("days_to_cover"),
        "biggest_increase": by("change_pct"),
        "biggest_decrease": by("change_pct", reverse=False),
        "watchlist": [r for r in latest if "watchlist" in r["indices"]],
        "spark": {r["ticker"]: spark.get(r["ticker"]) for group in (by("days_to_cover"), by("change_pct"), by("change_pct", False)) for r in group}
                 | {t: spark.get(t) for t in etfs},
        "covered": len(latest),
    }


def build(ctx) -> dict:
    settings = dict(ctx.config.get("positioning", {}))
    trends = [t for spec in ctx.indices if (t := _trend(ctx, spec, settings))]
    try:
        shorts = _short_interest(ctx, settings)
        ctx.log.add(SourceRecord("finra_short_interest", "FINRA consolidated short interest", finra.HOME_URL,
                                 shorts["settlement_date"], rows=shorts["covered"], policy="biweekly_release"))
    except Exception as exc:
        shorts = {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}
        ctx.log.add(SourceRecord("finra_short_interest", "FINRA consolidated short interest", finra.HOME_URL,
                                 status="error", error=str(exc)[:ERROR_DETAIL_CHARS]))
    return {
        "as_of": ctx.as_of,
        "trend": trends,
        "short_interest": shorts,
        "lookbacks": P.LOOKBACKS,
    }
