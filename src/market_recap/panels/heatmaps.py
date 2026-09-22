"""HEAT MAPS tab: S&P 500 by official weight, and US ETFs by estimated flow."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..compute import returns as R
from ..config import CACHE_DIR, PERIOD_TRADING_DAYS
from ..sources import yahoo
from ..util import SourceRecord, clean_float, to_iso_date, write_json

PERIODS = ("1D", "1W", "1M", "3M", "YTD", "1Y")
FLOW_HISTORY = CACHE_DIR / "etf_flow_history.json"


def _returns_for(series: pd.Series) -> dict:
    out = {}
    for period in PERIODS:
        out[period] = clean_float(
            R.ytd_return(series) if period == "YTD" else R.period_return(series, PERIOD_TRADING_DAYS[period]), 2
        )
    return out


def _load_flow_history() -> dict:
    if not FLOW_HISTORY.exists():
        return {}
    try:
        return json.loads(FLOW_HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_flow_history(history: dict) -> None:
    FLOW_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    FLOW_HISTORY.write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")


def build(ctx) -> dict:
    holdings, closes = ctx.holdings, ctx.closes
    priced = holdings[holdings["yahoo_symbol"].isin(closes.columns)].copy()

    # --- Constituent treemap: area = issuer-published weight ---------------
    nodes = []
    for row in priced.itertuples():
        series = closes[row.yahoo_symbol]
        nodes.append(
            {
                "ticker": row.yahoo_symbol,
                "name": str(row.name).title(),
                "sector": row.sector,
                "sub_sector": row.sub_sector,
                "weight": clean_float(row.weight, 4),
                "price": clean_float(series.dropna().iloc[-1], 2) if not series.dropna().empty else None,
                "returns": _returns_for(series),
            }
        )
    nodes.sort(key=lambda n: n["weight"] or 0, reverse=True)

    # --- ETF treemap: area = AUM, colour = estimated net flow --------------
    # Flow is the change in *shares outstanding* priced at today's close. A
    # fund whose price fell has not had an outflow, so market-value change is
    # not usable here. The series can only start when sampling started, and
    # the artifact says so rather than implying a full history.
    etf_groups = dict(ctx.config["etf_heatmap"])
    snapshot = yahoo.fetch_fund_snapshot(etf_groups.keys())
    ctx.log.add(
        SourceRecord(
            "yahoo_etf_snapshot",
            "US ETF price / AUM / shares outstanding",
            "https://finance.yahoo.com",
            ctx.as_of,
            rows=len(snapshot),
            status="ok" if len(snapshot) == len(etf_groups) else "partial",
        )
    )

    history = _load_flow_history()
    today = ctx.as_of or to_iso_date(pd.Timestamp.today())
    etf_nodes = []
    for row in snapshot.itertuples():
        prior = history.get(row.ticker)
        flow, flow_status = None, "insufficient_history"
        if prior and prior.get("date") != today and prior.get("shares_outstanding") and row.shares_outstanding:
            delta = float(row.shares_outstanding) - float(prior["shares_outstanding"])
            flow = delta * float(row.price)
            flow_status = "estimated"
        history[row.ticker] = {
            "date": today,
            "shares_outstanding": clean_float(row.shares_outstanding),
            "price": clean_float(row.price, 4),
        }
        series = ctx.etf_closes[row.ticker] if row.ticker in ctx.etf_closes.columns else pd.Series(dtype=float)
        etf_nodes.append(
            {
                "ticker": row.ticker,
                "name": row.name,
                "group": etf_groups.get(row.ticker, "Other"),
                "aum": clean_float(row.aum),
                "price": clean_float(row.price, 2),
                "shares_basis": row.shares_basis,
                "estimated_flow": clean_float(flow),
                "flow_status": flow_status,
                "returns": _returns_for(series) if not series.empty else {},
            }
        )
    _save_flow_history(history)

    sampling_started = min((v.get("date") for v in history.values() if v.get("date")), default=today)

    return {
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "periods": list(PERIODS),
        "constituents": nodes,
        "etfs": etf_nodes,
        "flow_sampling_started": sampling_started,
        "note": (
            "Constituent tiles are sized by the weight State Street publishes for SPY, not by an "
            "approximate market cap. Estimated net flow is the daily change in shares outstanding "
            "priced at the latest close, sampled once per build -- it accrues from the first run "
            f"({sampling_started}) and is not a backfilled history."
        ),
    }
