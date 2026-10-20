"""DCF tab: SEC-derived historical line items baked per ticker.

The model itself is a teaching tool that runs in the browser. This builder
only supplies the historical column -- the assumptions are the user's, and the
artifact never contains a target price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import DCF_ARTIFACT_DIR
from ..sources import sec
from .financials import cik_for
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, company_name, describe_error, prune_stale, write_json


def _beta(stock: pd.Series, market: pd.Series, *, weeks: int, min_weeks: int) -> float | None:
    """Weekly-return beta against the market proxy.

    Computed here rather than read off a data provider so the page can say
    exactly what it is: ordinary least squares on the last two years of
    *weekly* returns, which is less noisy than daily and does not depend on a
    vendor's undocumented convention.
    """
    pair = pd.concat([stock, market], axis=1, keys=["stock", "market"]).dropna()
    if pair.empty:
        return None
    weekly = pair.resample("W-FRI").last().pct_change(fill_method=None).dropna().tail(weeks)
    if len(weekly) < min_weeks:
        return None
    variance = float(weekly["market"].var())
    if not variance:
        return None
    covariance = float(weekly["stock"].cov(weekly["market"]))
    value = covariance / variance
    return float(value) if np.isfinite(value) else None


def build(ctx, *, tickers: list[str] | None = None, use_cache: bool = True) -> dict:
    config = ctx.config
    settings = config["dcf"]
    limit = int(settings["max_tickers"])
    proxy_ticker = str(config["universe"]["market_proxy"])
    market = ctx.etf_closes[proxy_ticker] if proxy_ticker in ctx.etf_closes.columns else None

    # The risk-free default is the published par yield at the contract's own
    # tenor, so the model opens with the number the FIXED INCOME tab is showing
    # rather than a second one that happens to look similar.
    tenor = str(config["universe"]["risk_free_tenor"])
    risk_free = None
    try:
        from ..sources import treasury

        curve, _ = treasury.fetch_par_yield_curve()
        latest = curve[curve["date"] == curve["date"].max()]
        row = latest[latest["tenor"] == tenor]
        if not row.empty:
            risk_free = clean_float(row.iloc[0]["yield_pct"], 2)
    except Exception as exc:
        ctx.log.fail("dcf:risk_free", exc)

    if tickers is None:
        # Largest weights first: the names most likely to be modelled.
        ranked = ctx.holdings.sort_values("weight", ascending=False)
        tickers = ranked["yahoo_symbol"].head(limit).tolist()

    try:
        cik_map = sec.fetch_ticker_cik_map(use_cache=use_cache)
        ctx.log.add(SourceRecord("sec_tickers", "SEC ticker to CIK map", sec.TICKERS_URL, rows=len(cik_map)))
    except Exception as exc:
        ctx.log.fail("dcf:cik_map", exc)
        return {"as_of": ctx.as_of, "available": [], "error": str(exc)[:ERROR_DETAIL_CHARS]}

    if use_cache:
        sec.check_filings(cik_for(symbol, cik_map) for symbol in tickers)
    baked, skipped = [], {}
    latest_filed = None
    for symbol in tickers:
        # SEC lists class shares with a dot; the price feed uses a dash.
        cik = cik_for(symbol, cik_map)
        if cik is None:
            skipped[symbol] = "no CIK mapping"
            continue
        try:
            payload = sec.extract_fundamentals(
                symbol, cik, years=int(settings["history_years"]), use_cache=use_cache
            )
        except Exception as exc:
            skipped[symbol] = describe_error(exc)
            continue

        meta = ctx.holdings.loc[ctx.holdings["yahoo_symbol"] == symbol]
        if not meta.empty:
            payload["company_name"] = company_name(meta.iloc[0]["name"])
            payload["sector"] = meta.iloc[0]["sector"]
        if symbol in ctx.closes.columns:
            series = ctx.closes[symbol].dropna()
            payload["last_price"] = clean_float(series.iloc[-1], 2) if not series.empty else None
            if market is not None:
                payload["beta"] = clean_float(
                    _beta(
                        ctx.closes[symbol], market,
                        weeks=int(settings["beta_weeks"]),
                        min_weeks=int(settings["beta_min_weeks"]),
                    ),
                    2,
                )

        # Effective tax rate from the filer's own numbers, where both legs exist.
        latest_row = payload["rows"][-1] if payload["rows"] else {}
        taxes, pretax = latest_row.get("taxes"), latest_row.get("pretax_income")
        payload["effective_tax_rate"] = (
            clean_float(taxes / pretax * 100, 1) if taxes and pretax and pretax > 0 else None
        )
        payload["risk_free_rate"] = risk_free

        write_json(DCF_ARTIFACT_DIR / f"{symbol}.json", payload)
        baked.append(symbol)
        latest_filed = max(filter(None, [latest_filed, *(
            value for row in payload["rows"] for key, value in row.items() if key.endswith("_filed")
        )]), default=None)

    prune_stale(DCF_ARTIFACT_DIR, baked)
    ctx.log.add(
        SourceRecord(
            "sec_companyfacts",
            "SEC XBRL company facts",
            "https://data.sec.gov/api/xbrl/companyfacts/",
            observed_date=latest_filed,
            rows=len(baked),
            # The model's history is annual: its newest date is a 10-K's.
            policy="annual_filings",
            status="ok" if not skipped else "partial",
            error=None if not skipped else f"{len(skipped)} tickers unavailable",
        )
    )
    return {
        "as_of": ctx.as_of,
        "available": sorted(baked),
        "skipped": skipped,
        "risk_free_rate": risk_free,
        "risk_free_tenor": tenor,
        "market_proxy": proxy_ticker,
        "beta_weeks": int(settings["beta_weeks"]),
        "forecast_years": int(settings["forecast_years"]),
        "reverse": settings.get("reverse"),
        "note": (
            "Historical columns are extracted from the company's own 10-K XBRL facts and carry "
            "the filing date they were published with. Forecast columns, discount rate and exit "
            "multiple are yours. This is a teaching model, not a target price."
        ),
    }
