"""The universe every panel shares.

Constituents, classification and price history are fetched once per build and
handed to the panels. Two panels that each fetch their own prices will
eventually disagree about what "today" is, and a dashboard whose heat map and
sector table disagree is not a dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import load_config
from .sources import ssga, wikipedia, yahoo
from .util import BuildLog, SourceRecord, to_iso_date


# A session is "complete" when nearly the whole panel has printed a close.
# Anything less is a session in progress: the provider serves an intraday bar
# for whatever it refreshed most recently, and a few hundred cached symbols
# still end on the prior close.
SESSION_COVERAGE_THRESHOLD = 0.90


def _completed_sessions(closes: pd.DataFrame) -> pd.DataFrame:
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
    last_complete = complete[complete].index[-1]
    return closes.loc[:last_complete]


@dataclass
class MarketContext:
    config: dict
    log: BuildLog
    holdings: pd.DataFrame = field(default_factory=pd.DataFrame)
    ndx_holdings: pd.DataFrame = field(default_factory=pd.DataFrame)
    closes: pd.DataFrame = field(default_factory=pd.DataFrame)
    etf_closes: pd.DataFrame = field(default_factory=pd.DataFrame)
    index_closes: pd.DataFrame = field(default_factory=pd.DataFrame)
    holdings_as_of: str | None = None

    @property
    def as_of(self) -> str | None:
        """The session this whole page describes: the latest constituent close."""
        if self.closes.empty:
            return None
        return to_iso_date(self.closes.index[-1])

    @property
    def sector_etfs(self) -> dict[str, str]:
        return dict(self.config["universe"]["sectors"])


def build_context(*, history_period: str = "3y", use_cache: bool = True) -> MarketContext:
    config = load_config()
    log = BuildLog()
    ctx = MarketContext(config=config, log=log)

    # 1. Official S&P 500 basket: weights and share counts from the issuer.
    holdings, as_of, url = ssga.fetch_holdings("SPY", use_cache=use_cache)
    holdings["yahoo_symbol"] = holdings["ticker"].map(ssga.to_yahoo_symbol)
    ctx.holdings_as_of = as_of
    log.add(SourceRecord("ssga_spy", "SPDR S&P 500 ETF daily holdings", url, as_of, rows=len(holdings), policy="fund_holdings"))

    # 2. Current GICS labels. Descriptive metadata, refreshed weekly.
    try:
        classification, wiki_url = wikipedia.fetch_sp500_classification(use_cache=use_cache)
        holdings = holdings.merge(
            classification[["ticker", "sector", "sub_sector"]],
            left_on="yahoo_symbol",
            right_on="ticker",
            how="left",
            suffixes=("", "_wiki"),
        ).drop(columns=["ticker_wiki"], errors="ignore")
        log.add(SourceRecord("wikipedia_gics", "S&P 500 GICS sector / sub-industry", wiki_url, rows=len(classification), policy="fund_holdings"))
    except Exception as exc:
        log.fail("classification", exc)
        holdings["sector"] = None
        holdings["sub_sector"] = None
    holdings["sector"] = holdings["sector"].fillna("Unclassified")
    holdings["sub_sector"] = holdings["sub_sector"].fillna("-")
    ctx.holdings = holdings

    # 3. Nasdaq-100 basket. Most of it overlaps the S&P 500 and inherits the
    #    GICS labels above; the rest are foreign issuers and recent listings
    #    that the S&P list does not cover, so their sector comes from a
    #    different taxonomy and is marked as such.
    try:
        ndx, ndx_as_of, ndx_url = ssga.fetch_holdings("QNDX", use_cache=use_cache)
        ndx["yahoo_symbol"] = ndx["ticker"].map(ssga.to_yahoo_symbol)
        labelled = holdings[["yahoo_symbol", "sector", "sub_sector"]].copy()
        labelled["classification_source"] = "wikipedia_gics"
        ndx = ndx.merge(labelled, on="yahoo_symbol", how="left")

        outside = ndx.loc[ndx["sector"].isna(), "yahoo_symbol"].tolist()
        if outside:
            extra = yahoo.fetch_sectors(outside)
            if not extra.empty:
                extra = extra.set_index("ticker")
                for column in ("sector", "sub_sector", "classification_source"):
                    ndx[column] = ndx.apply(
                        lambda row, c=column: extra.loc[row["yahoo_symbol"], c]
                        if pd.isna(row.get(c)) and row["yahoo_symbol"] in extra.index
                        else row.get(c),
                        axis=1,
                    )
        ndx["sector"] = ndx["sector"].fillna("Unclassified")
        ndx["sub_sector"] = ndx["sub_sector"].fillna("-")
        ctx.ndx_holdings = ndx
        log.add(SourceRecord("ssga_qndx", "SPDR Portfolio Nasdaq-100 daily holdings", ndx_url, ndx_as_of, rows=len(ndx), policy="fund_holdings"))
    except Exception as exc:
        log.fail("ndx_holdings", exc)

    # 4. Constituent price history, over both baskets at once so the two index
    #    sections of the page describe the same session.
    symbols = sorted(set(holdings["yahoo_symbol"]) | set(ctx.ndx_holdings.get("yahoo_symbol", [])))
    ctx.closes = _completed_sessions(yahoo.fetch_closes(symbols, period=history_period))
    missing = sorted(set(symbols) - set(ctx.closes.columns))
    log.add(
        SourceRecord(
            "yahoo_constituents",
            "S&P 500 / Nasdaq-100 constituent daily closes",
            "https://finance.yahoo.com",
            to_iso_date(ctx.closes.index[-1]) if not ctx.closes.empty else None,
            rows=int(ctx.closes.shape[1]),
            status="ok" if not missing else "partial",
            error=None if not missing else f"{len(missing)} symbols returned no data: {', '.join(missing[:8])}",
        )
    )

    # 5. Wrapper ETFs and long index history, fetched together so every tab
    #    shares one price vintage.
    etf_symbols = sorted(set(ctx.sector_etfs.values()) | set(config["etf_heatmap"]) | set(config["universe"]["quote_tickers"]))
    ctx.etf_closes = yahoo.fetch_closes(etf_symbols, period=history_period)
    log.add(
        SourceRecord(
            "yahoo_etfs",
            "Sector / broad ETF daily closes",
            "https://finance.yahoo.com",
            to_iso_date(ctx.etf_closes.index[-1]) if not ctx.etf_closes.empty else None,
            rows=int(ctx.etf_closes.shape[1]),
        )
    )

    index_symbols = [config["universe"]["spx_index"], config["universe"]["ndx_index"]]
    ctx.index_closes = yahoo.fetch_closes(index_symbols, period=f"{config['universe']['history_years']}y")
    log.add(
        SourceRecord(
            "yahoo_indices",
            "SPX / NDX index history",
            "https://finance.yahoo.com",
            to_iso_date(ctx.index_closes.index[-1]) if not ctx.index_closes.empty else None,
            rows=int(ctx.index_closes.shape[1]),
        )
    )
    return ctx
