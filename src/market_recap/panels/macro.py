"""MACRO tab: commodity proxies and the last twelve inflation releases."""

from __future__ import annotations

import pandas as pd

from ..compute import periods as P
from ..compute import returns as R
from ..sources import fred, yahoo
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, history_payload, to_iso_date


def build(ctx) -> dict:
    config = ctx.config
    releases = int(config["macro"]["releases"])
    history_years = int(config["macro"].get("history_years", 10))
    periods = list(config["periods"]["commodities"])
    history = config["periods"]["commodity_history"]

    # --- Commodities: Yahoo front-month futures and ETF proxies ------------
    symbols = dict(config["macro"]["commodities"])
    closes = yahoo.fetch_closes(symbols.values(), period=history)
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
        # Each instrument on its own trading days: futures, FX and ETFs keep
        # different holidays, and a shared union calendar would blank them.
        series = closes[symbol].dropna()
        row = {
            "label": label,
            "symbol": symbol,
            "price": clean_float(series.iloc[-1], 2),
            "status": "ok",
        }
        row |= {k: clean_float(v, 2) for k, v in R.period_returns(series, periods).items()}
        row["history"] = history_payload(series, years=history_years, digits=2)
        commodity_rows.append(row)

    # --- Inflation: the last twelve monthly prints -------------------------
    # Displayed as the publisher's own transform (YoY, MoM or a level), never
    # silently converted between them.
    collected: dict[str, pd.Series] = {}
    inflation_rows = []
    for spec in config["macro"]["inflation"]:
        try:
            frame, url = fred.fetch_series(spec["series_id"])
        except Exception as exc:
            ctx.log.add(
                SourceRecord(
                    f"fred_{spec['series_id'].lower()}", spec["label"],
                    f"https://fred.stlouisfed.org/series/{spec['series_id']}",
                    status="error", error=str(exc)[:ERROR_DETAIL_CHARS], policy="monthly_release",
                )
            )
            inflation_rows.append(
                {"label": spec["label"], "unit": spec["unit"],
                 "series_id": spec["series_id"], "values": [], "status": "unavailable"}
            )
            continue

        series = frame.set_index("date")["value"].sort_index()
        display = spec["display"]
        # By date: a month the agency never published leaves the changes that
        # span it blank instead of comparing across two periods.
        transformed = P.transform(series, display if display in ("yoy", "mom") else "level")
        collected[spec["series_id"]] = transformed.dropna()

        ctx.log.add(
            SourceRecord(
                f"fred_{spec['series_id'].lower()}", spec["label"], url,
                to_iso_date(series.index[-1]), rows=len(series), policy="monthly_release",
            )
        )
        inflation_rows.append(
            {"label": spec["label"], "unit": spec["unit"],
             "series_id": spec["series_id"], "status": "ok"}
        )

    # Lay every series on one month axis rather than taking each one's own last
    # twelve values and labelling them with the first series' months. These
    # publishers do not share a release lag -- the Dallas Fed's trimmed-mean
    # series can run a month behind BEA's -- and a row shifted one column
    # against its own header is wrong in a way nothing on the page would show.
    months: list[str] = []
    if collected:
        axis = sorted({stamp for series in collected.values() for stamp in series.index})
        axis = axis[-releases:]
        months = [stamp.strftime("%Y-%m") for stamp in axis]
        for row in inflation_rows:
            series = collected.get(row["series_id"])
            if series is None:
                row["values"] = []
                continue
            aligned = series.reindex(axis)
            row["values"] = [clean_float(v, 2) for v in aligned.to_numpy()]
            # Monthly already: nothing to thin, so the daily window covers it all.
            row["history"] = history_payload(series, years=history_years, digits=2, daily_days=366 * history_years)
            # A series that has not printed the latest month says so, instead
            # of borrowing the month above it.
            row["latest_month"] = series.index[-1].strftime("%Y-%m") if len(series) else None

    return {
        "as_of": to_iso_date(closes.index[-1]) if not closes.empty else None,
        "commodities": {"periods": periods, "rows": commodity_rows},
        "inflation": {"months": months, "releases": releases, "rows": inflation_rows},
        "note": (
            "Commodity prices are Yahoo front-month futures or ETF proxies, not LBMA/EIA spot "
            "prints. Inflation figures are the current FRED vintage: they reflect revisions "
            "published since the original release, so they are a release table, not a "
            "point-in-time record of what was known on the day. Every row is laid on one shared "
            "month axis, so a series its publisher has not updated yet shows a blank in the last "
            "column rather than being shifted a month to fill it."
        ),
    }
