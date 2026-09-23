"""MARKETS tab: quote strip, index chart, breadth, movers, sector tables.

Every index on this tab goes through one code path. When the S&P 500 and the
Nasdaq-100 were two hand-written blocks, the advance/decline line counted
Nasdaq-only names in the S&P 500's breadth -- the kind of error that does not
look like an error on the page.
"""

from __future__ import annotations

import pandas as pd

from ..compute import returns as R
from ..config import SESSION_COVERAGE_THRESHOLD, period_sessions
from ..util import clean_float, to_iso_date

# How many names each mover table lists. A round number with no analytic
# meaning, which is exactly why it belongs in one named place.
MOVERS_PER_SIDE = 10


def _series_payload(series: pd.Series) -> dict:
    clean = series.dropna()
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in clean.index],
        "values": [clean_float(v, 4) for v in clean.to_numpy()],
    }


def _windowed(series: pd.Series, sessions: int | None) -> pd.Series:
    clean = series.dropna()
    if sessions is None:  # YTD is a calendar rule, not a fixed window.
        last = clean.index[-1]
        return clean[clean.index >= pd.Timestamp(year=last.year, month=1, day=1)]
    return clean.tail(sessions + 1)


def _chart_windows(series: pd.Series, labels: list[str]) -> dict:
    out = {}
    for label in labels:
        window = _windowed(series, period_sessions(label))
        if len(window) > 2:
            out[label] = _series_payload(window)
    return out


def _period_returns(series: pd.Series, labels: list[str]) -> dict:
    return {k: clean_float(v, 2) for k, v in R.period_returns(series, labels).items()}


def _basket_returns(closes: pd.DataFrame, weights: pd.Series, labels: list[str]) -> dict:
    returns = R.basket_returns(closes, weights, labels, min_weight_share=SESSION_COVERAGE_THRESHOLD)
    return {k: clean_float(v, 2) for k, v in returns.items()}


def build(ctx) -> dict:
    config = ctx.config
    windows = config["periods"]
    closes = ctx.closes

    # --- Quote strip -------------------------------------------------------
    quotes = []
    for ticker in config["universe"]["quote_tickers"]:
        if ticker not in ctx.etf_closes.columns:
            continue
        # The last two rows of the shared calendar, not the last two prints:
        # a missing session must blank the change, not double it.
        series = ctx.etf_closes[ticker]
        if len(series) < 2 or series.iloc[-2:].isna().any():
            continue
        last, prior = float(series.iloc[-1]), float(series.iloc[-2])
        quotes.append({
            "ticker": ticker,
            "price": clean_float(last, 2),
            "change": clean_float(last - prior, 2),
            "change_pct": clean_float((last / prior - 1) * 100, 2),
            "as_of": to_iso_date(series.index[-1]),
        })

    # --- One block per index, built the same way so the sections are
    #     genuinely comparable rather than two different calculations.
    def index_block(spec) -> dict | None:
        symbols = ctx.symbols_for(spec.key)
        if spec.symbol not in ctx.index_closes.columns or not symbols:
            return None
        members = ctx.members[spec.key]
        panel = closes[symbols]

        movers = []
        if panel.shape[0] >= 2:
            change = (panel.iloc[-1] / panel.iloc[-2] - 1.0) * 100.0
            meta = members.drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")
            for symbol, value in change.dropna().items():
                if symbol not in meta.index:
                    continue
                row = meta.loc[symbol]
                movers.append({
                    "ticker": symbol,
                    "name": str(row["name"]).title(),
                    "sector": row["sector"],
                    "sub_sector": row["sub_sector"],
                    "price": clean_float(panel[symbol].iloc[-1], 2),
                    "change_pct": clean_float(value, 2),
                })
            movers.sort(key=lambda r: r["change_pct"], reverse=True)

        stats = R.drawdown_from_high(ctx.index_closes[spec.symbol])
        return {
            "key": spec.key,
            "label": spec.label,
            "symbol": spec.symbol,
            "members": len(symbols),
            "price_chart": _chart_windows(ctx.index_closes[spec.symbol], windows["index_price_chart"]),
            "breadth_chart": _chart_windows(R.net_breadth_series(panel), windows["breadth_chart"]),
            # Breadth on each index's own members. Counting every priced column
            # would credit the S&P 500 with Nasdaq-only names.
            "advance_decline": R.advance_decline(panel),
            "drawdown": {
                "drawdown_pct": clean_float(stats["drawdown_pct"], 2),
                "trading_days_since_high": stats["trading_days_since_high"],
                "high_date": stats["high_date"],
            },
            "gainers": movers[:MOVERS_PER_SIDE],
            "losers": movers[-MOVERS_PER_SIDE:][::-1],
            "classification": (
                members["classification_source"].value_counts().to_dict()
                if "classification_source" in members else {}
            ),
        }

    indices = {}
    for spec in ctx.indices:
        block = index_block(spec)
        if block:
            indices[spec.key] = block

    # --- Sector performance / weight / contribution ------------------------
    # Contribution is weight x return, using the issuer's published weight.
    # It is the only figure here that explains *why* the index moved, so it
    # must not be approximated from a sector ETF's own return.
    primary = ctx.priced(ctx.primary.key)
    sector_periods = windows["sector_table"]
    sector_rows = []
    for sector, group in primary.groupby("sector"):
        symbols = [s for s in group["yahoo_symbol"] if s in closes.columns]
        if not symbols:
            continue
        weights = group.set_index("yahoo_symbol").loc[symbols, "weight"]
        row = {
            "sector": sector,
            "etf": ctx.sector_etfs.get(sector),
            "weight_pct": clean_float(group["weight"].sum(), 2),
            "members": len(symbols),
        } | _basket_returns(closes, weights, sector_periods)
        one_day = row.get("1D")
        row["contribution_1d"] = (
            clean_float(group["weight"].sum() / 100.0 * one_day, 3) if one_day is not None else None
        )
        sector_rows.append(row)
    sector_rows.sort(key=lambda r: r["weight_pct"] or 0, reverse=True)

    index_weights = primary.drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")["weight"]
    index_returns = _basket_returns(closes, index_weights, sector_periods)
    index_row = {
        "sector": ctx.primary.label,
        "etf": None,
        "weight_pct": 100.0,
        "members": len(primary),
        # The column's total is the sum of its rows, so the table adds up.
        "contribution_1d": (
            clean_float(sum(r["contribution_1d"] for r in sector_rows), 3)
            if sector_rows and all(r["contribution_1d"] is not None for r in sector_rows) else None
        ),
    } | index_returns

    # --- Sectors rebased to 100 -------------------------------------------
    rebased = {}
    sector_etf_symbols = [t for t in ctx.sector_etfs.values() if t in ctx.etf_closes.columns]
    for label in windows["sector_rebased"]:
        window = R.rebase_to_100(ctx.etf_closes[sector_etf_symbols], period_sessions(label))
        if window.empty or len(window) < 3:
            continue
        rebased[label] = {
            "dates": [d.strftime("%Y-%m-%d") for d in window.index],
            "series": {col: [clean_float(v, 2) for v in window[col]] for col in window.columns},
        }

    # --- Breadth and SMA slope by sector ----------------------------------
    above_windows = config["breadth"]["above_ma_windows"]
    slope_lookbacks = config["breadth"]["slope_lookbacks"]
    trend_window = int(config["technicals"]["zscore_window"])
    breadth_rows, slope_rows = [], []
    for sector, group in primary.groupby("sector"):
        symbols = [s for s in group["yahoo_symbol"] if s in closes.columns]
        if not symbols:
            continue
        sub = closes[symbols]
        breadth_rows.append(
            {"sector": sector, "n": len(symbols)}
            | {f">{w}D": clean_float(R.pct_above_moving_average(sub, w), 1) for w in above_windows}
        )
        etf = ctx.sector_etfs.get(sector)
        if etf and etf in ctx.etf_closes.columns:
            series = ctx.etf_closes[etf]
            slope_rows.append(
                {"sector": sector, "etf": etf}
                | {
                    f"{w}D": clean_float(
                        R.sma_slope_pct(series, sma_window=trend_window, lookback=w), 2
                    )
                    for w in slope_lookbacks
                }
            )
    breadth_rows.sort(key=lambda r: r["n"], reverse=True)
    slope_rows.sort(key=lambda r: r["sector"])

    # --- Watchlist ---------------------------------------------------------
    # Names no tracked index holds. They get the same period definitions as
    # everything else, and a window their history cannot cover stays empty
    # rather than being measured from the first bar available.
    watchlist_periods = windows["watchlist"]
    watchlist_rows = []
    for row in ctx.watchlist.itertuples() if not ctx.watchlist.empty else []:
        entry = {
            "ticker": row.ticker,
            "label": row.label,
            "note": getattr(row, "note", None),
            "name": getattr(row, "name", None),
            "sector": getattr(row, "sector", None),
            "sub_sector": getattr(row, "sub_sector", None),
            "classification_source": getattr(row, "classification_source", None),
        }
        if not row.priced or row.ticker not in closes.columns:
            watchlist_rows.append(entry | {"price": None, "sessions": 0, "status": "unavailable"})
            continue
        series = closes[row.ticker].dropna()
        entry |= {
            "price": clean_float(series.iloc[-1], 2),
            "sessions": int(len(series)),
            "first_session": to_iso_date(series.index[0]),
            "status": "ok",
        } | _period_returns(closes[row.ticker], watchlist_periods)
        watchlist_rows.append(entry)

    index_labels = " or the ".join(s.label for s in ctx.indices)
    return {
        "as_of": ctx.as_of,
        "quotes": quotes,
        "indices": indices,
        "index_order": [s.key for s in ctx.indices],
        "sector_table": {
            "index": index_row,
            "rows": sector_rows,
            "periods": sector_periods,
            "source": f"{ctx.primary.holdings_etf} published weights",
        },
        "sector_rebased": rebased,
        "breadth_by_sector": {"windows": above_windows, "rows": breadth_rows},
        "sma_slope_by_sector": {"windows": slope_lookbacks, "trend_window": trend_window, "rows": slope_rows},
        "watchlist": {
            "rows": watchlist_rows,
            "periods": watchlist_periods,
            "note": (
                f"Watchlist names are not held by the {index_labels}, so they never enter "
                "either index's breadth, weight or advance/decline figures. A blank return means "
                "the history is shorter than that window, not that the return was zero."
            ),
        },
    }
