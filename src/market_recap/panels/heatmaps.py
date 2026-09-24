"""HEAT MAPS tab: S&P 500 by official weight, and US ETFs by published flow."""

from __future__ import annotations

import pandas as pd

from ..compute import returns as R
from ..config import ETF_ARTIFACT_DIR, period_sessions
from ..sources import ishares, ssga, vanguard, yahoo
from ..util import SourceRecord, clean_float, prune_stale, to_iso_date, write_json


def _returns_for(series: pd.Series, periods: list[str]) -> dict:
    return {k: clean_float(v, 2) for k, v in R.period_returns(series, periods).items()}


# Every issuer series here changes its share count within 19 sessions at most,
# except iShares' EFA and EEM, whose published count has sat unchanged for up
# to 127 sessions. Past this many unchanged sessions a window lying wholly in
# the unchanged stretch is unknown, not a measured zero.
STALE_SHARE_SESSIONS = 20


def _unchanged_run(shares: pd.Series) -> tuple[pd.Timestamp | None, int]:
    """Date of the last published change in units, and sessions since it."""
    clean = shares.dropna()
    if clean.empty:
        return None, 0
    changed = clean.diff().ne(0)
    changed.iloc[0] = True
    last = clean.index[changed.to_numpy()][-1]
    return last, int((clean.index > last).sum())


def _mask_unchanged(flows: dict, periods: list[str], last_change: pd.Timestamp | None,
                    unchanged: int, latest: pd.Timestamp) -> dict:
    if last_change is None or unchanged < STALE_SHARE_SESSIONS:
        return flows
    out = dict(flows)
    for period in periods:
        sessions = period_sessions(period)
        inside = (pd.Timestamp(year=latest.year, month=1, day=1) > last_change) if sessions is None \
            else sessions <= unchanged
        if inside:
            out[period] = None
    return out


def _cumulative_flows(flows: pd.Series, periods: list[str]) -> dict:
    """Net flow summed over each window, in dollars.

    Summed, not averaged: "1M flow" is how much money moved in a month, and a
    window with too little history returns None rather than a partial total
    presented as a full month.
    """
    out: dict[str, float | None] = {}
    clean = flows.dropna()
    for period in periods:
        sessions = period_sessions(period)
        if sessions is None:  # YTD
            start = pd.Timestamp(year=clean.index[-1].year, month=1, day=1) if not clean.empty else None
            window = clean[clean.index >= start] if start is not None else clean.iloc[0:0]
            out[period] = clean_float(window.sum()) if not window.empty else None
            continue
        out[period] = clean_float(clean.tail(sessions).sum()) if len(clean) >= sessions else None
    return out


# Two issuers publish the daily NAV and share count this panel needs, in
# different envelopes. They are tried in turn; a fund neither of them covers
# gets no flow rather than an estimate dressed up as a measurement.
# Each entry carries its own home URL. Deriving it from the provider id with a
# string test -- which is what this did -- silently attributes a third
# provider's funds to the second one.
FLOW_PROVIDERS = (
    ("ssga_nav_history", "State Street published NAV history", ssga.fetch_nav_history, ssga.HOME_URL),
    ("ishares_nav_history", "iShares published NAV history", ishares.fetch_nav_history, ishares.HOME_URL),
)


def _build_published_flow(
    ticker: str, prices: pd.Series, *, periods: list[str], ma_windows: list[int],
    chart_sessions: int, use_cache: bool,
) -> dict | None:
    """Reconstruct the whole flow history from an issuer's published file."""
    nav = None
    for provider_id, provider_label, fetch, _home in FLOW_PROVIDERS:
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

    last_change, unchanged = _unchanged_run(shares)
    stale_since = to_iso_date(last_change) if unchanged >= STALE_SHARE_SESSIONS else None

    tail = flow.dropna().tail(chart_sessions)
    price_tail = prices.reindex(tail.index).ffill() if not prices.empty else pd.Series(dtype=float)
    mas = {
        str(window): [clean_float(v, 2) for v in prices.rolling(window, min_periods=window).mean().reindex(tail.index)]
        for window in ma_windows
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
        "shares_unchanged_since": stale_since,
        "shares_unchanged_sessions": unchanged if stale_since else None,
    }
    write_json(ETF_ARTIFACT_DIR / f"{ticker}.json", payload)

    return {
        "flows": _mask_unchanged(_cumulative_flows(flow, periods), periods, last_change, unchanged, frame.index[-1]),
        "shares_unchanged_since": stale_since,
        "shares_unchanged_sessions": payload["shares_unchanged_sessions"],
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
    closes = ctx.closes
    periods = list(ctx.config["periods"]["heatmap"])
    ma_windows = list(ctx.config["technicals"]["ma_periods"])
    chart_sessions = period_sessions(ctx.config["periods"]["chart_window"])
    priced = ctx.priced(ctx.primary.key)

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
                "returns": _returns_for(series, periods),
            }
        )
    nodes.sort(key=lambda n: n["weight"] or 0, reverse=True)

    # --- ETF treemap -------------------------------------------------------
    etf_groups = dict(ctx.config["etf_heatmap"])
    published, unpublished = [], []
    etf_nodes = []

    for ticker, group in etf_groups.items():
        prices = ctx.etf_closes[ticker] if ticker in ctx.etf_closes.columns else pd.Series(dtype=float)
        result = _build_published_flow(
            ticker, prices.dropna(), periods=periods, ma_windows=ma_windows,
            chart_sessions=chart_sessions, use_cache=True,
        )
        node = {
            "ticker": ticker,
            "group": group,
            "price": clean_float(prices.dropna().iloc[-1], 2) if not prices.dropna().empty else None,
            "returns": _returns_for(prices, periods) if not prices.empty else {},
        }
        if result is None:
            # The issuer publishes no NAV history for this fund. Say so rather
            # than substituting a market-cap guess that would sit in the same
            # column as a measured figure and look equally solid.
            unpublished.append(ticker)
            node |= {
                "aum": None,
                "aum_source": None,
                "aum_basis": None,
                "flows": {},
                "flow_status": "issuer_does_not_publish",
                "premium_pct": None,
                "has_detail": False,
            }
            # Vanguard publishes no share history, but it does publish a
            # premium and -- crucially -- whether this ETF is one share class
            # of a larger fund, which is what makes a vendor's "total assets"
            # figure for it unusable as a tile size.
            try:
                facts = vanguard.fetch_fund_facts(ticker)
            except Exception:
                facts = None
            if facts:
                node |= {
                    "premium_pct": facts["premium_pct"],
                    "premium_source": "vanguard_published",
                    "nav": facts["nav"],
                    "multi_share_class": facts["multi_share_class"],
                    "share_classes": len(facts["associated_fund_ids"]),
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
                "shares_unchanged_since": result["shares_unchanged_since"],
                "shares_unchanged_sessions": result["shares_unchanged_sessions"],
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
                if node.get("multi_share_class"):
                    # Vanguard's own figure for the ETF share class alone,
                    # month-end and rounded, beats a whole-fund total.
                    try:
                        own, own_date = vanguard.fetch_share_class_assets(node["ticker"])
                    except Exception:
                        own, own_date = None, None
                    if own:
                        node |= {"aum": clean_float(own), "aum_source": "vanguard_share_class",
                                 "aum_basis": "share_class_month_end", "aum_as_of": own_date}
                        continue
                # An ETF that is one share class of a multi-class fund reports
                # assets for the whole fund. VTI comes back at $2.3tn that way,
                # which would make it the largest tile on the map. The tile is
                # kept -- dropping it hides a real fund -- but it is marked
                # oversized so the size is not read as the ETF's own.
                node["aum_basis"] = (
                    "all_share_classes" if node.get("multi_share_class") else "reported_total_assets"
                )
        share_class = [n for n in etf_nodes if n.get("aum_source") == "vanguard_share_class"]
        if share_class:
            ctx.log.add(SourceRecord(
                "vanguard_share_class_assets", "Vanguard ETF share-class net assets (month end)",
                vanguard.HOME_URL, min((n["aum_as_of"] for n in share_class if n.get("aum_as_of")), default=None),
                rows=len(share_class), policy="monthly_holdings",
            ))
        ctx.log.add(
            SourceRecord(
                "yahoo_etf_assets",
                "Total assets for funds without a published NAV file",
                "https://finance.yahoo.com",
                ctx.as_of,
                rows=int(sum(1 for n in etf_nodes if n.get("aum_source") == "yahoo_total_assets")),
                status="ok" if len(sizes) == len(unpublished) else "partial",
            )
        )

    by_source: dict[str, list[str]] = {}
    for node in etf_nodes:
        if node["flow_status"] == "published":
            by_source.setdefault(node["aum_source"], []).append(node["ticker"])
    for provider_id, provider_label, _fetch, home_url in FLOW_PROVIDERS:
        covered = by_source.get(provider_id, [])
        if not covered:
            continue
        ctx.log.add(
            SourceRecord(
                provider_id,
                f"{provider_label} (NAV + shares outstanding)",
                home_url,
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

    prune_stale(ETF_ARTIFACT_DIR, published)
    return {
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "periods": periods,
        "constituents": nodes,
        "etfs": etf_nodes,
        "flow_coverage": {"published": sorted(published), "unpublished": sorted(unpublished)},
        "flow_sources": {k: sorted(v) for k, v in by_source.items()},
        "oversized_aum": sorted(n["ticker"] for n in etf_nodes if n.get("aum_basis") == "all_share_classes"),
        "shares_unchanged": {n["ticker"]: n["shares_unchanged_since"] for n in etf_nodes
                             if n.get("shares_unchanged_since")},
        "note": (
            f"Constituent tiles are sized by the weight State Street publishes for "
            f"{ctx.primary.holdings_etf}, not by an "
            "approximate market cap. ETF net flow is the change in the fund's published shares "
            "outstanding valued at that day's NAV, taken from State Street's or BlackRock's own "
            "published history -- a measured series back to the fund's inception, not an estimate "
            "accrued since this dashboard was first run. Funds whose issuer publishes no such file "
            "are sized by reported total assets (Vanguard ETFs by the issuer's month-end figure for the ETF share class) and shown without flow rather than with a "
            "market-cap guess -- a vendor's shares-outstanding field for those funds disagrees "
            "with its own assets-over-price by more than half, so a sampled flow built on it "
            "would be fiction. Premium/discount comes from State Street and Vanguard, each for "
            "its own funds."
        ),
    }
