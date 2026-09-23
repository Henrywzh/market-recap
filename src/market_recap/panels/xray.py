"""ETF X-RAY tab: each fund on the heat map, looked through to its holdings.

Holdings come from the issuer's own file -- State Street and iShares daily,
Vanguard monthly -- and each fund's page says which and as of when. A fund
whose issuer publishes no usable file is listed with the reason instead of
being stood in for by a look-alike fund.

Built here: concentration, sector and country weights, the day's return
attributed to holdings, and how much each pair of funds overlaps. The
valuation look-through is joined in the browser against the VALUATION tab's
rows, so the two tabs cannot disagree about a company.
"""

from __future__ import annotations

import pandas as pd

from ..compute import xray as X
from ..compute.returns import period_return
from ..config import XRAY_ARTIFACT_DIR
from ..sources import ishares, ssga, vanguard
from ..util import ERROR_DETAIL_CHARS, SourceRecord, clean_float, prune_stale, write_json

PROVIDERS = {
    "ssga": ("State Street daily holdings", ssga.fetch_holdings, "fund_holdings"),
    "ishares": ("iShares daily holdings", ishares.fetch_holdings, "fund_holdings"),
    "vanguard": ("Vanguard monthly holdings", vanguard.fetch_holdings, "monthly_holdings"),
}
BOND_GROUP = "Fixed Income"
INTERNATIONAL_GROUP = "International"
WEIGHT_DIGITS = 6


def _equity_lines(frame: pd.DataFrame, provider: str, group: str) -> pd.DataFrame:
    """The listed-equity lines, each marked with whether it is a US listing.

    SSGA's parser has already dropped cash and futures; an iShares file keeps
    them under their own asset class. A US fund's lines are US listings; an
    international fund's are not, except the ADRs it holds -- which iShares
    marks by exchange and Vanguard by a US ISIN.
    """
    frame = frame.copy()
    international = group == INTERNATIONAL_GROUP
    if provider == "ssga":
        frame["weight"] = frame["weight"] / 100.0  # SSGA publishes percent
        frame = frame.rename(columns={"ssga_sector": "sector"})
        frame["sector"] = frame["sector"].replace({"-": None})
    if "asset_class" in frame:
        frame = frame[frame["asset_class"].eq("Equity")]
    if not international:
        frame["us_listed"] = True
    elif "exchange" in frame:
        frame["us_listed"] = frame["exchange"].fillna("").str.contains(X.US_EXCHANGES)
    else:
        frame["us_listed"] = frame.get("isin", pd.Series("", index=frame.index)).fillna("").str.startswith("US")
    if "sector" in frame:
        frame["sector"] = frame["sector"].replace(X.SECTOR_ALIASES)
    # A line with no ticker (Vanguard leaves some blank) is identified by its
    # ISIN or name instead, so blanks never merge into one "holding".
    ticker = frame["ticker"].fillna("").astype(str).str.strip()
    fallback = frame["isin"] if "isin" in frame else frame["name"]
    frame["ticker"] = ticker.where(ticker.ne(""), fallback.fillna("").astype(str))
    frame["key"] = [X.holding_key(t, us) for t, us in zip(frame["ticker"], frame["us_listed"])]
    return frame[frame["weight"] > 0].reset_index(drop=True)


def _sector_map(ctx, funds: dict[str, pd.DataFrame]) -> dict[str, str]:
    """GICS sector by holding key: this build's index members first, then any
    fund file that labels the name in the same market. SSGA and Vanguard
    publish no sector, so their holdings are classified from these."""
    labels: dict[str, str] = {}
    for frame in ctx.members.values():
        for symbol, sector in zip(frame["yahoo_symbol"], frame["sector"]):
            if isinstance(sector, str) and sector:
                labels.setdefault(X.holding_key(symbol, True), sector)
    for frame in funds.values():
        if "sector" in frame:
            for key, sector in zip(frame["key"], frame["sector"]):
                if isinstance(sector, str) and sector and sector != X.UNCLASSIFIED:
                    labels.setdefault(key, sector)
    return labels


def _one_day(ctx, symbols) -> pd.Series:
    closes = ctx.closes
    return pd.Series({s: period_return(closes[s], 1) for s in symbols if s in closes.columns}, dtype=float).dropna()


def _equity_payload(ctx, ticker: str, frame: pd.DataFrame, sectors: dict[str, str], top: int) -> dict:
    frame = frame.copy()
    # Only a US listing can be priced from this build's closes; any other line
    # keeps its own ticker, so it can never be mistaken for a US namesake.
    resolved = X.resolve_symbols(frame["ticker"], list(ctx.closes.columns))
    frame["symbol"] = resolved.where(frame["us_listed"], frame["ticker"].astype(str).str.upper())
    own = frame["sector"] if "sector" in frame else pd.Series(None, index=frame.index)
    frame["sector"] = own.where(own.notna() & own.ne(""), frame["key"].map(sectors))
    weights = frame[frame["us_listed"]].groupby("symbol")["weight"].sum()
    returns = _one_day(ctx, weights.index)
    attributed = X.attribution(weights, returns)
    contribution = attributed["contribution"]
    fund_closes = ctx.etf_closes[ticker] if ticker in ctx.etf_closes.columns else None
    frame = frame.sort_values("weight", ascending=False)
    return {
        "lines": int(len(frame)),
        "equity_weight": clean_float(frame["weight"].sum(), 4),
        "top10_weight": clean_float(X.top_weight(frame["weight"]), 4),
        "effective_n": clean_float(X.effective_n(frame["weight"]), 1),
        "sectors": [{**row, "weight": clean_float(row["weight"], 4)} for row in X.breakdown(frame, "sector")],
        "countries": (
            [{**row, "weight": clean_float(row["weight"], 4)} for row in X.breakdown(frame, "country")]
            if "country" in frame else None
        ),
        # Every line, compactly: the browser joins these to the VALUATION rows.
        "holdings": {
            "symbol": frame["symbol"].tolist(),
            "weight": [clean_float(w, WEIGHT_DIGITS) for w in frame["weight"]],
            "sector": frame["sector"].where(frame["sector"].notna(), None).tolist(),
        },
        "top": [
            {
                "symbol": row.symbol,
                "name": row.name,
                "weight": clean_float(row.weight, 5),
                "sector": row.sector if isinstance(row.sector, str) else None,
                "country": getattr(row, "country", None),
                "return_1d": clean_float(returns.get(row.symbol), 2),
                "contribution_1d": clean_float(contribution.get(row.symbol), 3),
            }
            for row in frame.head(top).itertuples()
        ],
        "attribution_1d": {
            "fund_return": clean_float(period_return(fund_closes, 1) if fund_closes is not None else None, 2),
            "covered_weight": clean_float(attributed["covered"], 4),
            "priced": attributed["priced"],
            "sum": clean_float(attributed["sum"], 3),
            "leaders": [{"symbol": s, "contribution": clean_float(c, 3)} for s, c in contribution[::-1].head(5).items() if c > 0],
            "laggards": [{"symbol": s, "contribution": clean_float(c, 3)} for s, c in contribution.head(5).items() if c < 0],
        },
    }


def _bond_payload(frame: pd.DataFrame, as_of: str | None, top: int) -> dict:
    profile = X.bond_profile(frame, as_of)
    issues = frame.sort_values("weight", ascending=False).head(top)
    return {
        "lines": int(len(frame)),
        **{k: clean_float(v, 3) if isinstance(v, float) else v for k, v in profile.items() if k != "maturity_buckets"},
        "maturity_buckets": [{**b, "weight": clean_float(b["weight"], 4)} for b in profile["maturity_buckets"]],
        "sectors": [{**row, "weight": clean_float(row["weight"], 4)} for row in X.breakdown(frame, "sector")],
        "countries": [{**row, "weight": clean_float(row["weight"], 4)} for row in X.breakdown(frame, "country")],
        "top": [
            {
                "name": row.name,
                "sector": row.sector,
                "weight": clean_float(row.weight, 5),
                "coupon": clean_float(getattr(row, "coupon", None), 3),
                "maturity": row.maturity.strftime("%Y-%m-%d") if pd.notna(getattr(row, "maturity", None)) else None,
                "duration": clean_float(getattr(row, "duration", None), 2),
                "ytm": clean_float(getattr(row, "ytm", None), 2),
            }
            for row in issues.itertuples()
        ],
    }


def build(ctx, *, use_cache: bool = True) -> dict:
    settings = ctx.config["etf_xray"]
    groups = ctx.config["etf_heatmap"]
    top = int(settings["top_holdings"])

    raw: dict[str, tuple[str, pd.DataFrame, str | None, str]] = {}
    funds: list[dict] = []
    records: dict[str, list] = {key: [] for key in PROVIDERS}
    for ticker, group in groups.items():
        spec = settings["holdings"].get(ticker, "none: no holdings source configured")
        entry = {"ticker": ticker, "group": group, "provider": None, "status": "unavailable"}
        if spec not in PROVIDERS:
            funds.append({**entry, "reason": spec.split(":", 1)[-1].strip()})
            continue
        label, fetch, _ = PROVIDERS[spec]
        try:
            frame, as_of, url = fetch(ticker, use_cache=use_cache)
        except Exception as exc:
            funds.append({**entry, "provider": spec, "reason": str(exc)[:ERROR_DETAIL_CHARS]})
            records[spec].append((ticker, None, False))
            continue
        raw[ticker] = (spec, frame, as_of, url)
        records[spec].append((ticker, as_of, True))
        funds.append({**entry, "provider": spec, "provider_label": label, "status": "ok",
                      "holdings_as_of": as_of, "source_url": url})

    equity = {t: _equity_lines(frame, spec, groups[t]) for t, (spec, frame, _, _) in raw.items() if groups[t] != BOND_GROUP}
    sectors = _sector_map(ctx, equity)

    written = []
    for fund in funds:
        ticker = fund["ticker"]
        if ticker not in raw:
            continue
        spec, frame, as_of, url = raw[ticker]
        if groups[ticker] == BOND_GROUP:
            body = {"kind": "bond", **_bond_payload(frame, as_of, top)}
            fund.update({k: body.get(k) for k in ("lines", "duration", "ytm")})
        else:
            body = {"kind": "equity", **_equity_payload(ctx, ticker, equity[ticker], sectors, top)}
            fund.update({k: body.get(k) for k in ("lines", "top10_weight", "effective_n", "equity_weight")})
        fund["kind"] = body["kind"]
        write_json(XRAY_ARTIFACT_DIR / f"{ticker}.json", {**fund, **body})
        written.append(ticker)
    prune_stale(XRAY_ARTIFACT_DIR, written)

    # Overlap between every pair of equity funds, by holding.
    keyed = {t: frame.groupby("key")["weight"].sum() for t, frame in equity.items()}
    order = [t for t in groups if t in keyed]
    matrix = [[clean_float(X.overlap(keyed[a], keyed[b]), 3) for b in order] for a in order]

    for spec, rows in records.items():
        if not rows:
            continue
        label, _, policy = PROVIDERS[spec]
        dates = [as_of for _, as_of, ok in rows if ok and as_of]
        failed = [t for t, _, ok in rows if not ok]
        urls = [f["source_url"] for f in funds if f.get("provider") == spec and f.get("source_url")]
        ctx.log.add(SourceRecord(
            f"{spec}_xray_holdings", label, urls[0] if urls else "",
            # The oldest file among the issuer's funds: the one that decides freshness.
            observed_date=min(dates) if dates else None, rows=len(rows) - len(failed), policy=policy,
            status="ok" if not failed else ("error" if not dates else "partial"),
            error=f"not fetched: {', '.join(failed)}" if failed else None,
        ))

    return {
        "as_of": ctx.as_of,
        "top_holdings": top,
        "funds": funds,
        "overlap": {"tickers": order, "matrix": matrix},
        "note": (
            "Holdings are each issuer's own published file: State Street and iShares daily (as of the "
            "prior session), Vanguard monthly, weeks after month end, and each fund shows its date. "
            "Vanguard weights are shares of the fund's stock holdings; the others are shares of the "
            "whole fund, cash and derivatives included. Sectors are GICS: the issuer's own label where "
            "it publishes one, otherwise the name's label from this build's index members or another "
            "fund's file in the same market. Overlap sums the smaller weight of each common holding, "
            "matching tickers within a market and without separators (BRK.B = BRKB = BRK-B). The 1D "
            "attribution covers only the US listings this build prices -- S&P 500 and Nasdaq-100 "
            "members -- and says how much of the fund that is. "
            "Look-through valuation is computed in the browser from the VALUATION tab's rows."
        ),
    }
