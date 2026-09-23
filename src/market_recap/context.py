"""The universe every panel shares.

Constituents, classification and price history are fetched once per build and
handed to the panels. Two panels that each fetch their own prices will
eventually disagree about what "today" is, and a dashboard whose heat map and
sector table disagree is not a dashboard.

Indices are built from :data:`config['universe']['indices']` rather than named
in code. The S&P 500 and the Nasdaq-100 used to be two hand-written branches
doing the same work, which is how the advance/decline line came to count
Nasdaq-only names in the S&P 500's breadth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import SESSION_COVERAGE_THRESHOLD, load_config
from .sources import ssga, wikipedia, yahoo
from .util import BuildLog, SourceRecord, to_iso_date

YAHOO_URL = "https://finance.yahoo.com"


def completed_sessions(closes: pd.DataFrame) -> pd.DataFrame:
    """Drop trailing rows that are not a finished session for the whole panel.

    This is not cosmetic. A frame whose last row holds fifteen of five hundred
    columns makes every cross-sectional figure on the page wrong at once:
    today's return is NaN for everything that was not refreshed, advancers and
    decliners count a handful of names, and the page dates itself to a session
    that has not closed. A post-market recap describes the last completed
    session, so that is what the context hands the panels.
    """
    if closes.empty:
        return closes
    coverage = closes.notna().sum(axis=1) / closes.shape[1]
    complete = coverage >= SESSION_COVERAGE_THRESHOLD
    if not complete.any():
        return closes
    return closes.loc[: complete[complete].index[-1]]


def _through(frame: pd.DataFrame, session: pd.Timestamp) -> pd.DataFrame:
    """Cut a frame to the page's session. ETFs and indices are fetched
    separately from the constituent panel; without this they can carry a
    session the panel has already rejected as unfinished, and the quote strip
    describes a different day from the tables beneath it."""
    return frame.loc[:session] if not frame.empty else frame


@dataclass(frozen=True)
class IndexSpec:
    """One index the page covers, as declared in the contract."""

    key: str
    label: str
    symbol: str
    holdings_etf: str
    holdings_label: str
    primary: bool = False

    @classmethod
    def from_config(cls, spec: dict) -> "IndexSpec":
        return cls(
            key=str(spec["key"]),
            label=str(spec["label"]),
            symbol=str(spec["symbol"]),
            holdings_etf=str(spec["holdings_etf"]),
            holdings_label=str(spec.get("holdings_label") or f"{spec['holdings_etf']} daily holdings"),
            primary=bool(spec.get("primary", False)),
        )


@dataclass
class MarketContext:
    config: dict
    log: BuildLog
    indices: list[IndexSpec] = field(default_factory=list)
    members: dict[str, pd.DataFrame] = field(default_factory=dict)
    holdings_dates: dict[str, str | None] = field(default_factory=dict)
    closes: pd.DataFrame = field(default_factory=pd.DataFrame)
    watchlist: pd.DataFrame = field(default_factory=pd.DataFrame)
    etf_closes: pd.DataFrame = field(default_factory=pd.DataFrame)
    index_closes: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Split ratios (date x symbol) for the constituent panel, from the same download.
    splits: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def as_of(self) -> str | None:
        """The session this whole page describes: the latest constituent close."""
        if self.closes.empty:
            return None
        return to_iso_date(self.closes.index[-1])

    @property
    def primary(self) -> IndexSpec:
        """The index the sector tables and the DCF universe are drawn from."""
        for spec in self.indices:
            if spec.primary:
                return spec
        return self.indices[0]

    @property
    def holdings(self) -> pd.DataFrame:
        """Members of the primary index."""
        return self.members.get(self.primary.key, pd.DataFrame())

    @property
    def holdings_as_of(self) -> str | None:
        return self.holdings_dates.get(self.primary.key)

    @property
    def sector_etfs(self) -> dict[str, str]:
        return dict(self.config["universe"]["sectors"])

    def priced(self, key: str) -> pd.DataFrame:
        """Members of one index that actually carry a price this build."""
        frame = self.members.get(key)
        if frame is None or frame.empty:
            return pd.DataFrame()
        return frame[frame["yahoo_symbol"].isin(self.closes.columns)].copy()

    def symbols_for(self, key: str) -> list[str]:
        frame = self.members.get(key)
        if frame is None or frame.empty:
            return []
        return [s for s in frame["yahoo_symbol"] if s in self.closes.columns]


def _classify(frame: pd.DataFrame, labelled: pd.DataFrame | None) -> pd.DataFrame:
    """Attach sector labels, marking which taxonomy each one came from.

    Names outside the S&P 500 list -- foreign issuers, recent listings -- get
    their sector from the price vendor instead, which is a different taxonomy
    and is recorded as such rather than blended in silently.
    """
    if labelled is not None and not labelled.empty:
        frame = frame.merge(labelled, on="yahoo_symbol", how="left")
    for column in ("sector", "sub_sector", "classification_source"):
        if column not in frame:
            frame[column] = None

    outside = frame.loc[frame["sector"].isna(), "yahoo_symbol"].tolist()
    if outside:
        extra = yahoo.fetch_sectors(outside)
        if not extra.empty:
            extra = extra.set_index("ticker")
            for column in ("sector", "sub_sector", "classification_source"):
                frame[column] = [
                    extra.loc[symbol, column]
                    if pd.isna(value) and symbol in extra.index
                    else value
                    for symbol, value in zip(frame["yahoo_symbol"], frame[column])
                ]
    frame["sector"] = frame["sector"].fillna("Unclassified")
    frame["sub_sector"] = frame["sub_sector"].fillna("-")
    return frame


def build_context(*, history_period: str = "3y", use_cache: bool = True) -> MarketContext:
    config = load_config()
    log = BuildLog()
    specs = [IndexSpec.from_config(s) for s in config["universe"]["indices"]]
    ctx = MarketContext(config=config, log=log, indices=specs)

    # 1. Current GICS labels for the primary basket. Descriptive metadata,
    #    refreshed weekly, and the label source every other index inherits.
    labelled = None
    try:
        classification, wiki_url = wikipedia.fetch_sp500_classification(use_cache=use_cache)
        labelled = classification[["ticker", "sector", "sub_sector"]].rename(
            columns={"ticker": "yahoo_symbol"}
        )
        labelled["classification_source"] = "wikipedia_gics"
        log.add(SourceRecord(
            "wikipedia_gics", "S&P 500 GICS sector / sub-industry", wiki_url,
            rows=len(classification), policy="fund_holdings",
        ))
    except Exception as exc:
        log.fail("classification", exc)

    # 2. Each index's official basket: weights and share counts from the issuer.
    for spec in specs:
        try:
            frame, as_of, url = ssga.fetch_holdings(spec.holdings_etf, use_cache=use_cache)
        except Exception as exc:
            log.fail(f"holdings:{spec.key}", exc)
            continue
        frame["yahoo_symbol"] = frame["ticker"].map(ssga.to_yahoo_symbol)
        ctx.members[spec.key] = _classify(frame, labelled)
        ctx.holdings_dates[spec.key] = as_of
        log.add(SourceRecord(
            f"ssga_{spec.holdings_etf.lower()}", spec.holdings_label, url, as_of,
            rows=len(frame), policy="fund_holdings",
        ))
    if not ctx.members:
        raise RuntimeError("no index basket could be fetched; the page has no universe")

    # 3. Price history, over every basket and the watchlist at once so every
    #    section of the page describes the same session. Watchlist names are
    #    carried as extra columns only; no index figure reads them, because a
    #    name the index does not hold is not part of its breadth.
    watchlist_specs = list(config.get("watchlist") or [])
    watchlist_symbols = [str(s["ticker"]).upper() for s in watchlist_specs]
    symbols = sorted(
        set(watchlist_symbols).union(
            *(set(frame["yahoo_symbol"]) for frame in ctx.members.values())
        )
    )
    ctx.closes = completed_sessions(yahoo.fetch_closes(symbols, period=history_period))
    if ctx.closes.empty:
        raise RuntimeError("no constituent prices were fetched; the page has no session to describe")
    ctx.splits = _through(yahoo.fetch_splits(history_period), ctx.closes.index[-1])
    missing = sorted(set(symbols) - set(ctx.closes.columns))
    log.add(SourceRecord(
        "yahoo_constituents",
        " / ".join(s.label for s in specs) + " constituent daily closes",
        YAHOO_URL,
        ctx.as_of,
        rows=int(ctx.closes.shape[1]),
        status="ok" if not missing else "partial",
        error=None if not missing else f"{len(missing)} symbols returned no data: {', '.join(missing[:8])}",
    ))

    # 4. Wrapper ETFs, fetched together so every tab shares one price vintage.
    etf_symbols = sorted(
        set(ctx.sector_etfs.values())
        | set(config["etf_heatmap"])
        | set(config["universe"]["quote_tickers"])
        | {config["universe"]["market_proxy"]}
        | set(_preset_symbols(config))
    )
    ctx.etf_closes = _through(yahoo.fetch_closes(etf_symbols, period=history_period), ctx.closes.index[-1])
    log.add(SourceRecord(
        "yahoo_etfs", "Sector / broad ETF daily closes", YAHOO_URL,
        to_iso_date(ctx.etf_closes.index[-1]) if not ctx.etf_closes.empty else None,
        rows=int(ctx.etf_closes.shape[1]),
    ))

    if watchlist_specs:
        ctx.watchlist = _build_watchlist(ctx, watchlist_specs, watchlist_symbols)

    # 5. Long index history for the drawdown and price charts.
    ctx.index_closes = _through(
        yahoo.fetch_closes([s.symbol for s in specs], period=f"{config['universe']['history_years']}y"),
        ctx.closes.index[-1],
    )
    log.add(SourceRecord(
        "yahoo_indices", " / ".join(s.key for s in specs) + " index history", YAHOO_URL,
        to_iso_date(ctx.index_closes.index[-1]) if not ctx.index_closes.empty else None,
        rows=int(ctx.index_closes.shape[1]),
    ))
    return ctx


def _preset_symbols(config: dict) -> set[str]:
    """Both legs of every relative-strength preset the TECHNICALS tab offers.

    A preset naming a ticker nobody else fetches renders as an empty chart, so
    the contract's own presets decide what gets priced.
    """
    out: set[str] = set()
    for preset in config["technicals"]["presets"]:
        out.update(part.strip().upper() for part in str(preset).split("/") if part.strip())
    return out


def _build_watchlist(ctx: MarketContext, specs: list[dict], symbols: list[str]) -> pd.DataFrame:
    # Sector labels for watchlist names come from the same mapped-Yahoo path
    # the out-of-index members use, and carry the same marker.
    extra = yahoo.fetch_sectors([s for s in symbols if s in ctx.closes.columns])
    rows = []
    for spec in specs:
        ticker = str(spec["ticker"]).upper()
        record = {
            "ticker": ticker,
            "label": spec.get("label") or ticker,
            "note": spec.get("note"),
            "priced": ticker in ctx.closes.columns,
        }
        if not extra.empty and ticker in set(extra["ticker"]):
            match = extra.loc[extra["ticker"] == ticker].iloc[0]
            record |= {
                "name": match["name"],
                "sector": match["sector"],
                "sub_sector": match["sub_sector"],
                "classification_source": match["classification_source"],
            }
        rows.append(record)
    missing = [r["ticker"] for r in rows if not r["priced"]]
    ctx.log.add(SourceRecord(
        "yahoo_watchlist", "Watchlist daily closes", YAHOO_URL, ctx.as_of,
        rows=int(sum(r["priced"] for r in rows)),
        status="ok" if not missing else "partial",
        error=None if not missing else "no data for: " + ", ".join(missing),
    ))
    return pd.DataFrame(rows)
