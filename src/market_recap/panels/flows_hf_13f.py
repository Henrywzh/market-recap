"""FLOWS · hedge-fund 13F crowding: which curated funds hold which S&P 500 names, and how that moved.

A proxy for where fundamental hedge funds are concentrated, not a census of
them. Long equity positions only; options are reported apart. The latest
quarter is the latest one whose 45-day filing deadline has passed, read against
the quarter before it for the changes.
"""

from __future__ import annotations

import tomllib

import numpy as np
import pandas as pd

from ..compute import hf_13f as H
from ..config import REPO_ROOT
from ..sources import sec13f
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, to_iso_date

CONFIG_PATH = REPO_ROOT / "config" / "hedge_funds_13f.toml"
LABEL = "SEC 13F-HR holdings of the curated hedge funds"
LAG_NOTE = (
    "13F-HR filings are due 45 days after quarter end, so the latest complete quarter is "
    "usually two to three months old when it is first read. Only long share positions "
    "count; options are reported separately."
)


def load_filers() -> list[dict]:
    with CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)["filer"]


def quarter_label(period: str) -> str:
    """'2026-06-30' reads as 'Q2 2026'."""
    day = pd.Timestamp(period)
    return f"Q{(day.month - 1) // 3 + 1} {day.year}"


def _jsonable(value):
    """Plain JSON values: numpy scalars become Python numbers, NaN and inf become None."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return clean_float(value, 4)
    return value


def _members(ctx, identifiers: pd.DataFrame) -> pd.DataFrame:
    """S&P 500 members with CUSIP, index weight, and the GICS sector of each priced name."""
    priced = ctx.priced(ctx.primary.key)[["yahoo_symbol", "sector"]].drop_duplicates("yahoo_symbol")
    return identifiers.merge(priced, on="yahoo_symbol", how="left")


def _prices(ctx, symbols) -> dict[str, float]:
    """The latest close for each member the page has a price for."""
    out: dict[str, float] = {}
    for symbol in symbols:
        if symbol not in ctx.closes.columns:
            continue
        series = ctx.closes[symbol].dropna()
        if not series.empty:
            out[symbol] = float(series.iloc[-1])
    return out


def build(ctx, inputs: dict) -> dict:
    if not ctx.as_of:
        return {"unavailable": "no index closes this build"}
    try:
        identifiers = sec13f.sp500_identifiers()
    except Exception as exc:
        ctx.log.add(SourceRecord("sec13f_identifiers", "S&P 500 CUSIPs (SSGA SPY file)", sec13f.HOME_URL,
                                 status="error", error=str(exc)[:ERROR_DETAIL_CHARS]))
        return {"unavailable": str(exc)[:ERROR_DETAIL_CHARS]}

    members = _members(ctx, identifiers)
    period = H.latest_complete_period(ctx.as_of)
    prior = H.prior_quarter(period)
    filers = load_filers()
    # Multi-strategy platforms are not fetched unless the flag asks for them.
    active = [f for f in filers if H.INCLUDE_MULTI or f["style"] != "multi"]

    longs: dict[str, dict[int, pd.DataFrame]] = {period: {}, prior: {}}
    exposures: list[dict] = []
    read_filers: dict[int, bool] = {}
    for filer in active:
        cik = int(filer["cik"])
        try:
            filings = sec13f.thirteen_f_filings(cik)
        except Exception as exc:
            ctx.log.add(SourceRecord("sec13f_filer", f"{filer['label']} 13F-HR list", sec13f.SUBMISSIONS_URL.format(cik=cik),
                                     status="error", error=str(exc)[:ERROR_DETAIL_CHARS]))
            read_filers[cik] = False
            continue
        read_filers[cik] = False
        for quarter in (period, prior):
            filing = H.pick_filing(filings, quarter)
            if filing is None:
                continue
            try:
                table = H.parse_information_table(sec13f.information_table_xml(cik, filing), quarter)
            except Exception as exc:
                ctx.log.add(SourceRecord("sec13f_filer", f"{filer['label']} 13F-HR {quarter}",
                                         sec13f.DOCUMENT_URL.format(cik=cik, folder=filing.accession.replace('-', ''), name=filing.primary),
                                         status="error", error=str(exc)[:ERROR_DETAIL_CHARS]))
                continue
            longs[quarter][cik] = H.long_positions(table)
            if quarter == period:
                exposures.append(H.option_exposure(table))
                read_filers[cik] = True

    now_ciks = [int(f["cik"]) for f in active if int(f["cik"]) in longs[period]]
    if not now_ciks:
        return {"unavailable": f"no 13F-HR for {quarter_label(period)} read from the curated list"}

    # The snapshot uses every filer that reported the quarter. The changes use
    # only the filers that reported both quarters, so a late filer is not a buyer.
    now_agg = H.aggregate({c: longs[period][c] for c in now_ciks})
    common = [c for c in now_ciks if c in longs[prior]]
    now_common = H.aggregate({c: longs[period][c] for c in common})
    prior_common = H.aggregate({c: longs[prior][c] for c in common})

    total = float(now_agg["value"].sum())
    member_frame = members.dropna(subset=["cusip"])
    prices = _prices(ctx, member_frame["yahoo_symbol"])
    splits = getattr(ctx, "splits", pd.DataFrame())
    def factors(start, end):
        if splits.empty:
            return {}
        return {symbol: float(series[(series.index > pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))]
                              .replace(0, 1).fillna(1).prod())
                for symbol, series in splits.items()}
    moves = H.changes(now_common, prior_common, member_frame, prices,
                      split_factors=factors(prior, period), post_period_split_factors=factors(period, ctx.as_of))
    crowded = H.crowded_names(now_agg, member_frame, total)
    options = H.option_totals(exposures)
    tilt = H.sector_tilt(now_agg, member_frame)
    outside = H.outside_index(now_agg, member_frame, total)

    ctx.log.add(SourceRecord("sec13f", LABEL, sec13f.HOME_URL, observed_date=period,
                             rows=len(now_ciks), policy="quarterly_filing"))

    return _jsonable({
        "period": period,
        "period_label": quarter_label(period),
        "prior_period": prior,
        "prior_label": quarter_label(prior),
        "deadline": (pd.Timestamp(period) + pd.Timedelta(days=H.FILING_LAG_DAYS)).strftime("%Y-%m-%d"),
        "as_of": to_iso_date(ctx.as_of),
        "sp_weight_as_of": ctx.holdings_as_of,
        "filers": {
            "configured": len(filers),
            "in_aggregate": len(active),
            "read": len(now_ciks),
            "read_prior": len(common),
            "list": [
                {"label": f["label"], "style": f["style"], "read": read_filers.get(int(f["cik"]), False)}
                for f in active
            ],
            "excluded_style": [f["label"] for f in filers if f not in active],
        },
        "n_funds": len(now_ciks),
        "total_value_bn": clean_float(total / 1e9, 2),
        "concentration_top10_pct": H.concentration(now_agg, total),
        "outside_sp500": {
            "names": outside["names"],
            "value_share_pct": outside["value_share_pct"],
        },
        "options": {
            "put_rows": options["put_rows"],
            "call_rows": options["call_rows"],
            "put_value_bn": clean_float(options["put_value"] / 1e9, 2),
            "call_value_bn": clean_float(options["call_value"] / 1e9, 2),
        },
        "crowded": [
            {
                "ticker": r.ticker, "sector": r.sector, "funds": int(r.funds),
                "value_bn": clean_float(r.value / 1e9, 2), "hf_pct": clean_float(r.hf_pct, 2),
                "sp_pct": clean_float(r.sp_pct, 2), "ratio": clean_float(r.ratio, 2),
            }
            for r in crowded.itertuples()
        ],
        "moves": {
            "common_funds": len(common),
            "adds": moves["adds"], "cuts": moves["cuts"],
            "adds_by_holders": moves["adds_by_holders"], "cuts_by_holders": moves["cuts_by_holders"],
        },
        "sector_tilt": tilt,
        "prices_as_of": to_iso_date(ctx.as_of),
        "lag": LAG_NOTE,
        "quality": {
            # A non-empty split matrix does not prove complete symbol coverage.
            "share_changes_split_adjusted": False,
            "amendments_applied": False,
            "status": "original_filings_only",
            "limits": "13F-HR/A restatements/additions, confidential positions and corporate-action/CUSIP changes are not fully reconciled. Share changes are estimates, not trade cash flows. Reported option values describe underlying securities, not premiums or delta exposure.",
        },
        "note": (
            "S&P 500 weights are the SPY file's current weights, not quarter-end. Adds and cuts are "
            "share changes valued at the latest close."
        ),
    })
