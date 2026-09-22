"""MARKETS tab: quote strip, index chart, breadth, movers, sector tables."""

from __future__ import annotations

import pandas as pd

from ..compute import returns as R
from ..config import PERIOD_TRADING_DAYS
from ..util import clean_float, to_iso_date

BREADTH_WINDOWS = [5, 20, 50, 100, 200]
SLOPE_WINDOWS = [5, 20, 50, 100, 200]
CHART_PERIODS = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252, "3Y": 756, "5Y": 1260, "10Y": 2520}


def _series_payload(series: pd.Series) -> dict:
    clean = series.dropna()
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in clean.index],
        "values": [clean_float(v, 4) for v in clean.to_numpy()],
    }


def _windowed(series: pd.Series, sessions: int | None) -> pd.Series:
    clean = series.dropna()
    if sessions is None:  # YTD
        last = clean.index[-1]
        return clean[clean.index >= pd.Timestamp(year=last.year, month=1, day=1)]
    return clean.tail(sessions + 1)


def build(ctx) -> dict:
    holdings, closes = ctx.holdings, ctx.closes
    priced = holdings[holdings["yahoo_symbol"].isin(closes.columns)].copy()

    # --- Quote strip -------------------------------------------------------
    quotes = []
    for ticker in ctx.config["universe"]["quote_tickers"]:
        if ticker not in ctx.etf_closes.columns:
            continue
        series = ctx.etf_closes[ticker].dropna()
        if len(series) < 2:
            continue
        last, prior = float(series.iloc[-1]), float(series.iloc[-2])
        quotes.append(
            {
                "ticker": ticker,
                "price": clean_float(last, 2),
                "change": clean_float(last - prior, 2),
                "change_pct": clean_float((last / prior - 1) * 100, 2),
                "as_of": to_iso_date(series.index[-1]),
            }
        )

    # --- Index drawdown ----------------------------------------------------
    drawdowns = []
    for label, symbol in (("SPX", ctx.config["universe"]["spx_index"]), ("NDX", ctx.config["universe"]["ndx_index"])):
        if symbol not in ctx.index_closes.columns:
            continue
        stats = R.drawdown_from_high(ctx.index_closes[symbol])
        drawdowns.append(
            {
                "label": label,
                "drawdown_pct": clean_float(stats["drawdown_pct"], 2),
                "trading_days_since_high": stats["trading_days_since_high"],
                "high_date": stats["high_date"],
            }
        )

    # --- Advance / decline, on each index's own members --------------------
    # ``closes`` now spans both baskets, so counting every column would credit
    # the S&P 500 with Nasdaq-only names.
    spx_symbols = [s for s in priced["yahoo_symbol"] if s in closes.columns]
    spx_ad = R.advance_decline(closes[spx_symbols])
    ndx_symbols = [s for s in ctx.ndx_holdings.get("yahoo_symbol", pd.Series(dtype=str)) if s in closes.columns]
    ndx_ad = R.advance_decline(closes[ndx_symbols]) if ndx_symbols else None

    # --- One block per index, built the same way so the two sections are
    #     genuinely comparable rather than two different calculations.
    def index_block(label: str, symbol: str, members: pd.DataFrame) -> dict | None:
        symbols = [s for s in members["yahoo_symbol"] if s in closes.columns]
        if symbol not in ctx.index_closes.columns or not symbols:
            return None
        full = ctx.index_closes[symbol]

        price_chart = {}
        for window_label, sessions in CHART_PERIODS.items():
            window = _windowed(full, sessions)
            if len(window) > 2:
                price_chart[window_label] = _series_payload(window)

        panel = closes[symbols]
        breadth = R.net_breadth_series(panel)
        breadth_chart = {}
        for window_label, sessions in (("1M", 21), ("3M", 63), ("6M", 126), ("YTD", None), ("1Y", 252), ("2Y", 504)):
            window = _windowed(breadth, sessions)
            if len(window) > 2:
                breadth_chart[window_label] = _series_payload(window)

        movers = []
        if panel.shape[0] >= 2:
            change = (panel.iloc[-1] / panel.iloc[-2] - 1.0) * 100.0
            meta = members.drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")
            for sym, value in change.dropna().items():
                if sym not in meta.index:
                    continue
                row = meta.loc[sym]
                movers.append(
                    {
                        "ticker": sym,
                        "name": str(row["name"]).title(),
                        "sector": row["sector"],
                        "sub_sector": row["sub_sector"],
                        "price": clean_float(panel[sym].iloc[-1], 2),
                        "change_pct": clean_float(value, 2),
                    }
                )
            movers.sort(key=lambda r: r["change_pct"], reverse=True)

        return {
            "label": label,
            "symbol": symbol,
            "members": len(symbols),
            "price_chart": price_chart,
            "breadth_chart": breadth_chart,
            "gainers": movers[:10],
            "losers": movers[-10:][::-1],
        }

    indices = {}
    spx_block = index_block("S&P 500", ctx.config["universe"]["spx_index"], priced)
    if spx_block:
        indices["SPX"] = spx_block
    if not ctx.ndx_holdings.empty:
        ndx_block = index_block("Nasdaq 100", ctx.config["universe"]["ndx_index"], ctx.ndx_holdings)
        if ndx_block:
            indices["NDX"] = ndx_block

    # --- Sector performance / weight / contribution ------------------------
    # Contribution is weight x return, using the issuer's published weight.
    # It is the only figure here that explains *why* the index moved, so it
    # must not be approximated from a sector ETF's own return.
    sector_rows = []
    total_weight = float(priced["weight"].sum())
    for sector, group in priced.groupby("sector"):
        symbols = [s for s in group["yahoo_symbol"] if s in closes.columns]
        if not symbols:
            continue
        weights = group.set_index("yahoo_symbol").loc[symbols, "weight"]
        weights = weights / weights.sum()
        basket = (closes[symbols] * weights).sum(axis=1)
        row = {
            "sector": sector,
            "etf": ctx.sector_etfs.get(sector),
            "weight_pct": clean_float(group["weight"].sum(), 2),
            "members": len(symbols),
        }
        for label in ("1D", "1W", "1M", "3M"):
            row[label] = clean_float(R.period_return(basket, PERIOD_TRADING_DAYS[label]), 2)
        row["YTD"] = clean_float(R.ytd_return(basket), 2)
        one_day = row["1D"]
        row["contribution_1d"] = clean_float(group["weight"].sum() / 100.0 * one_day, 3) if one_day is not None else None
        sector_rows.append(row)
    sector_rows.sort(key=lambda r: r["weight_pct"] or 0, reverse=True)

    index_basket = (closes * (priced.set_index("yahoo_symbol")["weight"].reindex(closes.columns).fillna(0) / total_weight)).sum(axis=1)
    index_row = {
        "sector": "S&P 500",
        "etf": None,
        "weight_pct": 100.0,
        "members": len(priced),
        "contribution_1d": clean_float(R.period_return(index_basket, 1), 3),
    }
    for label in ("1D", "1W", "1M", "3M"):
        index_row[label] = clean_float(R.period_return(index_basket, PERIOD_TRADING_DAYS[label]), 2)
    index_row["YTD"] = clean_float(R.ytd_return(index_basket), 2)

    # --- Sectors rebased to 100 -------------------------------------------
    rebased = {}
    sector_etf_symbols = [t for t in ctx.sector_etfs.values() if t in ctx.etf_closes.columns]
    for label, sessions in (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252), ("3Y", 756)):
        window = R.rebase_to_100(ctx.etf_closes[sector_etf_symbols], sessions)
        if window.empty or len(window) < 3:
            continue
        rebased[label] = {
            "dates": [d.strftime("%Y-%m-%d") for d in window.index],
            "series": {col: [clean_float(v, 2) for v in window[col]] for col in window.columns},
        }

    # --- Breadth and SMA slope by sector ----------------------------------
    breadth_rows, slope_rows = [], []
    for sector, group in priced.groupby("sector"):
        symbols = [s for s in group["yahoo_symbol"] if s in closes.columns]
        if not symbols:
            continue
        sub = closes[symbols]
        breadth_rows.append(
            {"sector": sector, "n": len(symbols)}
            | {f">{w}D": clean_float(R.pct_above_moving_average(sub, w), 1) for w in BREADTH_WINDOWS}
        )
        etf = ctx.sector_etfs.get(sector)
        if etf and etf in ctx.etf_closes.columns:
            series = ctx.etf_closes[etf]
            slope_rows.append(
                {"sector": sector, "etf": etf}
                | {f"{w}D": clean_float(R.sma_slope_pct(series, sma_window=200, lookback=w), 2) for w in SLOPE_WINDOWS}
            )
    breadth_rows.sort(key=lambda r: r["n"], reverse=True)
    slope_rows.sort(key=lambda r: r["sector"])

    return {
        "as_of": ctx.as_of,
        "quotes": quotes,
        "drawdowns": drawdowns,
        "advance_decline": {"SPX": spx_ad, "NDX": ndx_ad},
        "indices": indices,
        "ndx_classification": (
            ctx.ndx_holdings["classification_source"].value_counts().to_dict()
            if "classification_source" in ctx.ndx_holdings else {}
        ),
        "sector_table": {"index": index_row, "rows": sector_rows},
        "sector_rebased": rebased,
        "breadth_by_sector": {"windows": BREADTH_WINDOWS, "rows": breadth_rows},
        "sma_slope_by_sector": {"windows": SLOPE_WINDOWS, "rows": slope_rows},
    }
