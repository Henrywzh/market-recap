"""HEAT MAPS tab: S&P 500 by official weight, and US ETFs by published flow."""

from __future__ import annotations

import pandas as pd

from ..compute import returns as R
from ..config import ETF_ARTIFACT_DIR, PERIOD_TRADING_DAYS
from ..sources import ishares, ssga, yahoo
from ..util import SourceRecord, clean_float, to_iso_date, write_json

PERIODS = ("1D", "1W", "1M", "3M", "YTD", "1Y")
FLOW_MA_WINDOWS = (20, 50, 200)
FLOW_CHART_SESSIONS = 504


def _returns_for(series: pd.Series) -> dict:
    return {
        period: clean_float(
            R.ytd_return(series) if period == "YTD" else R.period_return(series, PERIOD_TRADING_DAYS[period]),
            2,
        )
        for period in PERIODS
    }


def _cumulative_flows(flows: pd.Series) -> dict:
    """Net flow summed over each window, in dollars.

    Summed, not averaged: "1M flow" is how much money moved in a month, and a
    window with too little history returns None rather than a partial total
    presented as a full month.
    """
    out: dict[str, float | None] = {}
    clean = flows.dropna()
    for period in PERIODS:
        if period == "YTD":
            start = pd.Timestamp(year=clean.index[-1].year, month=1, day=1) if not clean.empty else None
            window = clean[clean.index >= start] if start is not None else clean.iloc[0:0]
            out[period] = clean_float(window.sum()) if not window.empty else None
            continue
        sessions = PERIOD_TRADING_DAYS[period]
        out[period] = clean_float(clean.tail(sessions).sum()) if len(clean) >= sessions else None
    return out


# Two issuers publish the daily NAV and share count this panel needs, in
# different envelopes. They are tried in turn; a fund neither of them covers
# gets no flow rather than an estimate dressed up as a measurement.
FLOW_PROVIDERS = (
    ("ssga_nav_history", "State Street published NAV history", ssga.fetch_nav_history),
    ("ishares_nav_history", "iShares published NAV history", ishares.fetch_nav_history),
)


def _build_published_flow(ticker: str, prices: pd.Series, use_cache: bool) -> dict | None:
    """Reconstruct the whole flow history from an issuer's published file."""
    nav = None
    for provider_id, provider_label, fetch in FLOW_PROVIDERS:
        try:
            candidate, url = fetch(ticker, use_cache=use_cache)
        except Exception:
            continue
        if candidate is not None and not candidate.empty and "shares_outstanding" in candidate:
            nav, source_id, source_label = candidate, provider_id, provider_label
            break
    if nav is None:
        return None

    frame = nav.set_index("date")
    shares = frame["shares_outstanding"]
    # Flow is the change in units priced at that day's NAV. Valuing it at the
    # market close instead would mix a creation with the day's premium.
    flow = shares.diff() * frame["nav"]

    # Only State Street publishes a premium/discount series here; an iShares
    # fund simply has no premium line rather than a computed stand-in.
    premium = None
    if source_id == "ssga_nav_history":
        try:
            pd_frame, _ = ssga.fetch_premium_discount(ticker, use_cache=use_cache)
            if not pd_frame.empty:
                premium = pd_frame.set_index("date")["premium_pct"]
        except Exception:
            premium = None

    tail = flow.dropna().tail(FLOW_CHART_SESSIONS)
    price_tail = prices.reindex(tail.index).ffill() if not prices.empty else pd.Series(dtype=float)
    mas = {
        str(window): [clean_float(v, 2) for v in prices.rolling(window, min_periods=window).mean().reindex(tail.index)]
        for window in FLOW_MA_WINDOWS
    } if not prices.empty else {}

    payload = {
        "ticker": ticker,
        "as_of": to_iso_date(frame.index[-1]),
        "history_start": to_iso_date(frame.index[0]),
        "sessions": int(len(frame)),
        "source": source_label,
        "source_id": source_id,
        "source_url": url,
        "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
        "flow": [clean_float(v, 0) for v in tail.to_numpy()],
        "close": [clean_float(v, 2) for v in price_tail.to_numpy()] if not price_tail.empty else [],
        "moving_averages": mas,
        "nav": [clean_float(v, 4) for v in frame["nav"].reindex(tail.index).to_numpy()],
        "premium_pct": (
            [clean_float(v, 4) for v in premium.reindex(tail.index).to_numpy()] if premium is not None else []
        ),
        "latest_premium_pct": clean_float(premium.iloc[-1], 4) if premium is not None and not premium.empty else None,
    }
    write_json(ETF_ARTIFACT_DIR / f"{ticker}.json", payload)

    return {
        "flows": _cumulative_flows(flow),
        # State Street publishes total net assets directly; BlackRock's sheet
        # does not, so it is NAV times units -- which is the same quantity, and
        # reconstructing it here keeps every published fund sizeable on the map.
        "aum": clean_float(
            frame["total_net_assets"].iloc[-1]
            if "total_net_assets" in frame and pd.notna(frame["total_net_assets"].iloc[-1])
            else frame["nav"].iloc[-1] * shares.iloc[-1]
        ),
        "nav": clean_float(frame["nav"].iloc[-1], 4),
        "shares_outstanding": clean_float(shares.iloc[-1]),
        "premium_pct": payload["latest_premium_pct"],
        "history_start": payload["history_start"],
        "sessions": payload["sessions"],
        "source_id": source_id,
        "source_label": source_label,
    }


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

    # --- ETF treemap -------------------------------------------------------
    etf_groups = dict(ctx.config["etf_heatmap"])
    published, unpublished = [], []
    etf_nodes = []

    for ticker, group in etf_groups.items():
        prices = ctx.etf_closes[ticker] if ticker in ctx.etf_closes.columns else pd.Series(dtype=float)
        result = _build_published_flow(ticker, prices.dropna(), use_cache=True)
        node = {
            "ticker": ticker,
            "group": group,
            "price": clean_float(prices.dropna().iloc[-1], 2) if not prices.dropna().empty else None,
            "returns": _returns_for(prices) if not prices.empty else {},
        }
        if result is None:
            # The issuer publishes no NAV history for this fund. Say so rather
            # than substituting a market-cap guess that would sit in the same
            # column as a measured figure and look equally solid.
            unpublished.append(ticker)
            node |= {
                "aum": None,
                "aum_source": None,
                "flows": {},
                "flow_status": "issuer_does_not_publish",
                "premium_pct": None,
                "has_detail": False,
            }
        else:
            published.append(ticker)
            node |= {
                "aum": result["aum"],
                "aum_source": result["source_id"],
                "flow_source": result["source_label"],
                "nav": result["nav"],
                "shares_outstanding": result["shares_outstanding"],
                "flows": result["flows"],
                "flow_status": "published",
                "premium_pct": result["premium_pct"],
                "history_start": result["history_start"],
                "sessions": result["sessions"],
                "has_detail": True,
            }
        etf_nodes.append(node)

    # AUM sizes the treemap. Funds without a published NAV file still need a
    # size or they vanish from the map entirely -- which contradicts the note
    # telling the reader they are shown uncoloured. Yahoo's total-assets field
    # is good enough to size a tile and is labelled as a different source.
    if unpublished:
        snapshot = yahoo.fetch_fund_snapshot(unpublished)
        sizes = snapshot.set_index("ticker")["aum"].to_dict() if not snapshot.empty else {}
        for node in etf_nodes:
            if node["flow_status"] != "published":
                node["aum"] = clean_float(sizes.get(node["ticker"]))
                node["aum_source"] = "yahoo_total_assets" if node["aum"] else None
        ctx.log.add(
            SourceRecord(
                "yahoo_etf_assets",
                "Total assets for funds without a published NAV file",
                "https://finance.yahoo.com",
                ctx.as_of,
                rows=int(sum(1 for n in etf_nodes if n.get("aum_source"))),
                status="ok" if len(sizes) == len(unpublished) else "partial",
            )
        )

    by_source: dict[str, list[str]] = {}
    for node in etf_nodes:
        if node["flow_status"] == "published":
            by_source.setdefault(node["aum_source"], []).append(node["ticker"])
    for provider_id, provider_label, _ in FLOW_PROVIDERS:
        covered = by_source.get(provider_id, [])
        if not covered:
            continue
        ctx.log.add(
            SourceRecord(
                provider_id,
                f"{provider_label} (NAV + shares outstanding)",
                "https://www.ssga.com" if provider_id.startswith("ssga") else "https://www.ishares.com",
                ctx.as_of,
                rows=len(covered),
                policy="fund_holdings",
            )
        )
    if unpublished:
        ctx.log.add(
            SourceRecord(
                "etf_flow_gap",
                "Funds with no published NAV history",
                "",
                ctx.as_of,
                rows=len(unpublished),
                policy="fund_holdings",
                status="partial",
                error="no issuer NAV file located for: " + ", ".join(sorted(unpublished)),
            )
        )

    return {
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "periods": list(PERIODS),
        "constituents": nodes,
        "etfs": etf_nodes,
        "flow_coverage": {"published": sorted(published), "unpublished": sorted(unpublished)},
        "flow_sources": {k: sorted(v) for k, v in by_source.items()},
        "note": (
            "Constituent tiles are sized by the weight State Street publishes for SPY, not by an "
            "approximate market cap. ETF net flow is the change in the fund's published shares "
            "outstanding valued at that day's NAV, taken from State Street's or BlackRock's own "
            "published history -- a measured series back to the fund's inception, not an estimate "
            "accrued since this dashboard was first run. Funds whose issuer publishes no such file "
            "are sized by reported total assets and shown without flow rather than with a "
            "market-cap guess. Premium/discount is published by State Street only."
        ),
    }
