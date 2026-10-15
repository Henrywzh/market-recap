"""HEAT MAPS tab: S&P 500 by official weight, and US ETFs by published flow."""

from __future__ import annotations

import pandas as pd

from ..compute import returns as R
from ..config import ETF_ARTIFACT_DIR, period_sessions
from ..sources import invesco, ishares, snapshot_store, ssga, vanguard, yahoo
from ..util import SourceRecord, clean_float, company_name, prune_stale, to_iso_date, write_json


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
def _invesco_recorded(ticker: str, *, use_cache: bool = True) -> tuple[pd.DataFrame, str]:
    """Invesco's daily units as the evening snapshots recorded them. Invesco
    publishes no history of its own, so this starts when the record did."""
    return snapshot_store.etf_units(ticker), invesco.HOME_URL


FLOW_PROVIDERS = (
    ("ssga_nav_history", "State Street published NAV history", ssga.fetch_nav_history, ssga.HOME_URL),
    ("ishares_nav_history", "iShares published NAV history", ishares.fetch_nav_history, ishares.HOME_URL),
    ("invesco_recorded", "Invesco published units, recorded each evening", _invesco_recorded, invesco.HOME_URL),
)


def _invesco_premium(cusip: str | None, use_cache: bool) -> pd.Series | None:
    if not cusip:
        return None
    try:
        frame, _ = invesco.fetch_premium_history(cusip, use_cache=use_cache)
    except Exception:
        return None
    return frame.set_index("date")["premium_pct"] if not frame.empty else None


def _price_only(ticker: str, prices: pd.Series, *, ma_windows: list[int], chart_sessions: int,
                reason: str, premium: pd.Series | None) -> None:
    """Price and averages for a fund with no flow record, so it can still be
    picked on the page; the flow chart says why it is empty."""
    tail = prices.dropna().tail(chart_sessions)
    write_json(ETF_ARTIFACT_DIR / f"{ticker}.json", {
        "ticker": ticker,
        "as_of": to_iso_date(tail.index[-1]) if not tail.empty else None,
        "history_start": None,
        "sessions": 0,
        "source": None,
        "flow_note": reason,
        "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
        "flow": [],
        "close": [clean_float(v, 2) for v in tail.to_numpy()],
        "moving_averages": {
            str(w): [clean_float(v, 2) for v in prices.rolling(w, min_periods=w).mean().reindex(tail.index)]
            for w in ma_windows
        },
        "premium_pct": [clean_float(v, 4) for v in premium.reindex(tail.index).to_numpy()] if premium is not None else [],
        "shares_unchanged_since": None,
    })


def _build_published_flow(
    ticker: str, prices: pd.Series, *, periods: list[str], ma_windows: list[int],
    chart_sessions: int, use_cache: bool, cusip: str | None = None,
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
    if source_id == "invesco_recorded":
        premium = _invesco_premium(cusip, use_cache)
    elif source_id == "ssga_nav_history":
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


def _constituents(priced: pd.DataFrame, closes: pd.DataFrame, periods: list[str]) -> list[dict]:
    """One tile per priced member, heaviest first."""
    nodes = []
    for row in priced.itertuples():
        series = closes[row.yahoo_symbol].dropna()
        nodes.append(
            {
                "ticker": row.yahoo_symbol,
                "name": company_name(row.name),
                "sector": row.sector,
                "sub_sector": row.sub_sector,
                "weight": clean_float(row.weight, 4),
                "price": clean_float(series.iloc[-1], 2) if not series.empty else None,
                "returns": _returns_for(closes[row.yahoo_symbol], periods),
            }
        )
    nodes.sort(key=lambda n: n["weight"] or 0, reverse=True)
    return nodes


def _fund_map(ctx, spec: dict, closes: pd.DataFrame, periods: list[str]) -> dict:
    """A map for an index the dashboard does not otherwise cover (the Dow),
    sized by its SPDR fund's published weights. Its members must already be
    priced members of a covered index, which also gives their GICS labels; a
    name that is not is left off and listed, never priced on the side."""
    fund = spec["holdings_etf"]
    out = {"key": spec["key"], "label": spec["label"], "weight_source": fund, "note": spec.get("note"),
           "constituents": [], "missing": []}
    try:
        holdings, as_of, url = ssga.fetch_holdings(fund)
    except Exception as exc:  # an optional map: its failure is a note, not the page's
        ctx.log.add(SourceRecord(f"ssga_{fund.lower()}_map", f"{fund} daily holdings", "", None,
                                 status="partial", error=str(exc)[:300]))
        return out
    known = pd.concat([ctx.priced(s.key) for s in ctx.indices]).drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")
    rows = []
    for row in holdings.itertuples():
        symbol = ssga.to_yahoo_symbol(row.ticker)
        if symbol in known.index:
            member = known.loc[symbol]
            rows.append({"yahoo_symbol": symbol, "name": member["name"], "sector": member["sector"],
                         "sub_sector": member["sub_sector"], "weight": row.weight})
        else:
            out["missing"].append(row.ticker)
    out["constituents"] = _constituents(pd.DataFrame(rows), closes, periods) if rows else []
    out["holdings_as_of"] = as_of
    ctx.log.add(SourceRecord(f"ssga_{fund.lower()}_map", f"{fund} daily holdings", url, as_of,
                             rows=len(rows), status="partial" if out["missing"] else "ok",
                             error=f"not priced here: {', '.join(out['missing'])}" if out["missing"] else None))
    return out


def build(ctx) -> dict:
    closes = ctx.closes
    periods = list(ctx.config["periods"]["heatmap"])
    ma_windows = list(ctx.config["technicals"]["ma_periods"])
    chart_sessions = period_sessions(ctx.config["periods"]["chart_window"])
    priced = ctx.priced(ctx.primary.key)

    # --- Constituent treemaps: area = issuer-published weight --------------
    nodes = _constituents(priced, closes, periods)
    # The other indices (the Nasdaq 100) get the same map, sized by their own
    # tracking fund's weights; the page switches between them.
    index_maps = [
        {"key": spec.key, "label": spec.label, "weight_source": spec.holdings_etf,
         "constituents": _constituents(ctx.priced(spec.key), closes, periods)}
        for spec in ctx.indices if not spec.primary
    ]
    index_maps += [_fund_map(ctx, spec, closes, periods) for spec in ctx.config.get("heatmap_maps", [])]
    index_maps = [m for m in index_maps if m["constituents"]]

    # --- ETF treemap -------------------------------------------------------
    etf_groups = dict(ctx.config["etf_heatmap"])
    holdings_sources = dict(ctx.config.get("etf_xray", {}).get("holdings", {}))
    published, unpublished, price_only = [], [], []
    etf_nodes = []

    for ticker, group in etf_groups.items():
        prices = ctx.etf_closes[ticker] if ticker in ctx.etf_closes.columns else pd.Series(dtype=float)
        cusip = invesco.cusip_for(holdings_sources.get(ticker))
        result = _build_published_flow(
            ticker, prices.dropna(), periods=periods, ma_windows=ma_windows,
            chart_sessions=chart_sessions, use_cache=True, cusip=cusip,
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
            if not prices.dropna().empty:
                reason = ("Invesco publishes only today's shares outstanding; they are recorded each "
                          "evening and a flow appears once two days are on record."
                          if cusip and ticker in ctx.config.get("snapshots", {}).get("risk", {}).get("invesco", [])
                          else "The issuer publishes no daily shares-outstanding history for this fund, "
                               "so there is no measured flow.")
                _price_only(ticker, prices.dropna(), ma_windows=ma_windows, chart_sessions=chart_sessions,
                            reason=reason, premium=_invesco_premium(cusip, True))
                price_only.append(ticker)
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

    prune_stale(ETF_ARTIFACT_DIR, published + price_only)
    # The single-fund picker: the funds named first in the contract, then the
    # rest in heat-map order; every fund with a price, flow record or not.
    first = [t for t in ctx.config.get("etf_detail", {}).get("first", []) if t in published + price_only]
    detail = first + [t for t in etf_groups if t in published + price_only and t not in first]
    return {
        "as_of": ctx.as_of,
        "holdings_as_of": ctx.holdings_as_of,
        "periods": periods,
        "constituents": nodes,
        "primary": {"key": ctx.primary.key, "label": ctx.primary.label, "weight_source": ctx.primary.holdings_etf},
        "index_maps": index_maps,
        "etfs": etf_nodes,
        "flow_coverage": {"published": sorted(published), "unpublished": sorted(unpublished), "detail": detail},
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
