"""FIXED INCOME tab: the published par yield curve and its changes."""

from __future__ import annotations

import pandas as pd

from ..sources import fred, treasury
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, history_payload, to_iso_date

# The curve is compared against its own history, so every snapshot names a
# published date rather than "a week ago" in the abstract. Comparison windows
# come from the contract; these two bookends are structural.
LATEST = ("latest", "Latest Published", 0)
START_OF_YEAR = ("start_of_year", "Start of Year", None)
# Basis points per percentage point. The curve is published in percent and the
# change columns are in bps.
BPS_PER_PCT = 100.0


def _history(ctx, settings) -> dict:
    """Constant-maturity yields and the 10Y-2Y spread over years, from FRED.

    The par curve above comes from Treasury's yearly files; for a chart that
    reaches back a decade FRED's DGS series are the same Treasury yields in
    one file each. A series that fails is left out and says so in the log.
    """
    years = int(settings.get("history_years", 10))
    lines: dict[str, pd.Series] = {}
    for spec in settings.get("history_series", []):
        try:
            frame, url = fred.fetch_series(spec["series_id"])
        except Exception as exc:
            ctx.log.add(SourceRecord(f"fred_{spec['series_id'].lower()}", f"Treasury {spec['label']} yield history",
                                     f"https://fred.stlouisfed.org/series/{spec['series_id']}",
                                     status="error", error=str(exc)[:ERROR_DETAIL_CHARS]))
            continue
        series = frame.set_index("date")["value"].sort_index()
        lines[spec["label"]] = series
        ctx.log.add(SourceRecord(f"fred_{spec['series_id'].lower()}", f"Treasury {spec['label']} yield history", url,
                                 to_iso_date(series.index[-1]), rows=len(series)))
    out = {label: history_payload(series, years=years, digits=2) for label, series in lines.items()}
    spread = settings.get("history_spread")
    if spread and spread["long"] in lines and spread["short"] in lines:
        pair = pd.concat([lines[spread["long"]], lines[spread["short"]]], axis=1, keys=["l", "s"]).dropna()
        out[spread["label"]] = history_payload((pair["l"] - pair["s"]) * BPS_PER_PCT, years=years, digits=0)
    return {"years": years, "series": out, "spread": spread["label"] if spread else None}


def _pivot(frame: pd.DataFrame) -> pd.DataFrame:
    wide = frame.pivot(index="date", columns="tenor", values="yield_pct")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def _on_or_before(wide: pd.DataFrame, target: pd.Timestamp) -> tuple[pd.Timestamp, pd.Series] | None:
    eligible = wide[wide.index <= target]
    if eligible.empty:
        return None
    return eligible.index[-1], eligible.iloc[-1]


def build(ctx) -> dict:
    settings = ctx.config["fixed_income"]
    snapshots = (
        [LATEST]
        + [(c["key"], c["label"], int(c["days"])) for c in settings["comparisons"]]
        + [START_OF_YEAR]
    )
    spreads = [(s["label"], s["long"], s["short"]) for s in settings["spreads"]]
    change_columns = [(c["key"], c["column"]) for c in settings["comparisons"]]

    frame, url = treasury.fetch_par_yield_curve()
    if frame.empty:
        raise ValueError("Treasury returned no curve observations")
    wide = _pivot(frame)
    latest_date = wide.index[-1]
    latest = wide.iloc[-1]

    ctx.log.add(
        SourceRecord(
            "treasury_par_yield",
            "US Treasury daily par yield curve rates",
            url,
            latest_date.strftime("%Y-%m-%d"),
            rows=len(wide),
            policy="published_curve",
        )
    )

    tenor_order = [t for _, t, _ in treasury.TENORS]
    tenors = [t for t in tenor_order if t in wide.columns]

    curves = []
    for key, label, days_back in snapshots:
        if days_back is None:
            start = pd.Timestamp(year=latest_date.year, month=1, day=1)
            eligible = wide[wide.index >= start]
            if eligible.empty:
                continue
            stamp, row = eligible.index[0], eligible.iloc[0]
        else:
            found = _on_or_before(wide, latest_date - pd.Timedelta(days=days_back))
            if found is None:
                continue
            stamp, row = found
        curves.append(
            {
                "key": key,
                "label": label,
                "date": stamp.strftime("%Y-%m-%d"),
                "values": [clean_float(row.get(t), 2) for t in tenors],
            }
        )

    by_key = {c["key"]: c for c in curves}

    def _bps(tenor: str, key: str) -> float | None:
        snapshot = by_key.get(key)
        if snapshot is None or tenor not in tenors:
            return None
        prior = snapshot["values"][tenors.index(tenor)]
        current = clean_float(latest.get(tenor))
        if prior is None or current is None:
            return None
        return round((current - prior) * BPS_PER_PCT, 1)

    prior_session = _on_or_before(wide.iloc[:-1], latest_date) if len(wide) > 1 else None

    # Column headings follow the contract: a column named "1W" comes from the
    # snapshot the contract calls a week back, not from a literal repeated in
    # the builder and again in the renderer.
    column_for = dict(change_columns)

    rows = []
    for tenor in tenors:
        current = clean_float(latest.get(tenor), 2)
        one_day = None
        if prior_session is not None:
            prev = clean_float(prior_session[1].get(tenor))
            if prev is not None and current is not None:
                one_day = round((current - prev) * BPS_PER_PCT, 1)
        rows.append(
            {
                "tenor": tenor,
                "yield_pct": current,
                "1D": one_day,
                **{column_for[key]: _bps(tenor, key) for key, _ in change_columns},
                "YTD": _bps(tenor, "start_of_year"),
            }
        )

    spread_rows = []
    for label, long_leg, short_leg in spreads:
        if long_leg not in tenors or short_leg not in tenors:
            continue

        def _spread_bps(source: pd.Series) -> float | None:
            a, b = clean_float(source.get(long_leg)), clean_float(source.get(short_leg))
            return None if a is None or b is None else (a - b) * BPS_PER_PCT

        current = _spread_bps(latest)
        entry = {"label": label, "bps": clean_float(current, 1)}
        for key, column in list(column_for.items()) + [("start_of_year", "YTD")]:
            snapshot = by_key.get(key)
            if snapshot is None or current is None:
                entry[column] = None
                continue
            prior_row = wide.loc[pd.Timestamp(snapshot["date"])]
            prior = _spread_bps(prior_row)
            entry[column] = None if prior is None else round(current - prior, 1)
        if prior_session is not None and current is not None:
            prev = _spread_bps(prior_session[1])
            entry["1D"] = None if prev is None else round(current - prev, 1)
        else:
            entry["1D"] = None
        spread_rows.append(entry)

    return {
        "as_of": latest_date.strftime("%Y-%m-%d"),
        "tenors": tenors,
        "change_columns": ["1D"] + list(column_for.values()) + ["YTD"],
        "curves": curves,
        "rows": rows,
        "spreads": spread_rows,
        "history": _history(ctx, settings),
        "auctions": treasury.public_auction_summary(),
        "note": (
            '"Latest Published" is the most recent date the U.S. Treasury has posted par yield '
            "curve rates for. Treasury usually publishes same-day but sometimes not until early "
            "evening ET, so a build run shortly after the close can show the prior business day. "
            "That is the publisher's schedule, not a gap in this dashboard."
        ),
    }
