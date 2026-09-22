"""MACRO tab: commodity proxies and the last twelve inflation releases."""

from __future__ import annotations

import pandas as pd

from ..compute import returns as R
from ..config import PERIOD_TRADING_DAYS
from ..sources import fred, yahoo
from ..util import SourceRecord, clean_float, to_iso_date

RELEASES = 12


def build(ctx) -> dict:
    config = ctx.config

    # --- Commodities: Yahoo front-month futures and ETF proxies ------------
    symbols = dict(config["macro"]["commodities"])
    closes = yahoo.fetch_closes(symbols.values(), period="2y")
    ctx.log.add(
        SourceRecord(
            "yahoo_commodities",
            "Commodity futures / ETF proxies",
            "https://finance.yahoo.com",
            to_iso_date(closes.index[-1]) if not closes.empty else None,
            rows=int(closes.shape[1]),
            status="ok" if closes.shape[1] == len(symbols) else "partial",
        )
    )

    commodity_rows = []
    for label, symbol in symbols.items():
        if symbol not in closes.columns:
            commodity_rows.append({"label": label, "symbol": symbol, "price": None, "status": "unavailable"})
            continue
        series = closes[symbol].dropna()
        row = {
            "label": label,
            "symbol": symbol,
            "price": clean_float(series.iloc[-1], 2),
            "status": "ok",
        }
        for period in ("1D", "1W", "1M", "3M"):
            row[period] = clean_float(R.period_return(series, PERIOD_TRADING_DAYS[period]), 2)
        row["YTD"] = clean_float(R.ytd_return(series), 2)
        commodity_rows.append(row)

    # --- Inflation: the last twelve monthly prints -------------------------
    # Displayed as the publisher's own transform (YoY, MoM or a level), never
    # silently converted between them.
    inflation_rows, months = [], []
    for spec in config["macro"]["inflation"]:
        try:
            frame, url = fred.fetch_series(spec["series_id"])
        except Exception as exc:
            ctx.log.add(
                SourceRecord(
                    f"fred_{spec['series_id'].lower()}", spec["label"],
                    f"https://fred.stlouisfed.org/series/{spec['series_id']}",
                    status="error", error=str(exc)[:200], policy="monthly_release",
                )
            )
            inflation_rows.append({"label": spec["label"], "unit": spec["unit"], "values": [], "status": "unavailable"})
            continue

        series = frame.set_index("date")["value"].sort_index()
        display = spec["display"]
        if display == "yoy":
            transformed = (series / series.shift(12) - 1.0) * 100.0
        elif display == "mom":
            transformed = (series / series.shift(1) - 1.0) * 100.0
        else:
            transformed = series
        transformed = transformed.dropna().tail(RELEASES)

        ctx.log.add(
            SourceRecord(
                f"fred_{spec['series_id'].lower()}", spec["label"], url,
                to_iso_date(series.index[-1]), rows=len(series), policy="monthly_release",
            )
        )
        if not months:
            months = [d.strftime("%Y-%m") for d in transformed.index]
        inflation_rows.append(
            {
                "label": spec["label"],
                "unit": spec["unit"],
                "series_id": spec["series_id"],
                "values": [clean_float(v, 2) for v in transformed.to_numpy()],
                "status": "ok",
            }
        )

    return {
        "as_of": to_iso_date(closes.index[-1]) if not closes.empty else None,
        "commodities": commodity_rows,
        "inflation": {"months": months, "rows": inflation_rows},
        "note": (
            "Commodity prices are Yahoo front-month futures or ETF proxies, not LBMA/EIA spot "
            "prints. Inflation figures are the current FRED vintage: they reflect revisions "
            "published since the original release, so they are a release table, not a "
            "point-in-time record of what was known on the day."
        ),
    }
