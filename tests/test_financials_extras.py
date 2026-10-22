"""The [financials] extras: names outside the S&P 500 and Nasdaq-100 that get filings and prices."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import context as C
from market_recap.compute import valuation as V
from market_recap.config import load_config
from market_recap.panels import financials as fin
from market_recap.panels import valuation as panel
from market_recap.sources import sec, wikipedia, yahoo, ssga
from market_recap.util import BuildLog

EXTRAS = ["VIK", "TOL", "CZR", "ALLY"]


def test_the_shipped_config_names_the_four_extras():
    assert load_config()["financials"]["extra"] == EXTRAS


def test_universe_adds_the_extras_and_leaves_index_membership_alone():
    members = {"SPX": pd.DataFrame({"yahoo_symbol": ["AAPL", "BRK-B"]})}
    ctx = types.SimpleNamespace(config={"financials": {"indices": ["SPX", "NDX"], "extra": ["vik", "TOL"]}},
                                members=members)
    assert fin.universe(ctx) == ["AAPL", "BRK-B", "TOL", "VIK"]
    assert set(members["SPX"]["yahoo_symbol"]) == {"AAPL", "BRK-B"}      # not added to the index


def test_universe_without_extras_is_the_index_members_alone():
    members = {"SPX": pd.DataFrame({"yahoo_symbol": ["AAPL"]})}
    ctx = types.SimpleNamespace(config={"financials": {"indices": ["SPX"]}}, members=members)
    assert fin.universe(ctx) == ["AAPL"]


# --- Prices: the extras ride the constituent download ----------------------------------

def _days(end: str = "2026-10-09", periods: int = 320) -> pd.DatetimeIndex:
    return pd.bdate_range(end=end, periods=periods)


class _FakeYahoo:
    """Every symbol asked for gets a flat close. Splits and split-adjusted
    prices come from the first download, as the cache serves them."""

    def __init__(self) -> None:
        self.requested: list[list[str]] = []
        self.first: pd.DataFrame | None = None

    def fetch_closes(self, symbols, **_kwargs) -> pd.DataFrame:
        wanted = sorted(set(symbols))
        self.requested.append(wanted)
        frame = pd.DataFrame({s: 100.0 for s in wanted}, index=_days())
        if self.first is None:
            self.first = frame
        return frame

    def fetch_prices(self, period: str) -> pd.DataFrame:
        return self.first.copy()

    def fetch_splits(self, period: str) -> pd.DataFrame:
        return pd.DataFrame(index=self.first.index, columns=self.first.columns, dtype=float)


def _offline(**_kwargs):
    raise RuntimeError("offline")


def _patch_sources(monkeypatch) -> _FakeYahoo:
    feed = _FakeYahoo()
    # No GICS labels: the build records the failure and carries on.
    monkeypatch.setattr(wikipedia, "fetch_sp500_classification", _offline)
    monkeypatch.setattr(ssga, "fetch_holdings", lambda ticker, **_: (
        pd.DataFrame({"ticker": ["AAPL", "MSFT"], "weight": [60.0, 40.0]}), "2026-10-09", "https://example.test/holdings"))
    monkeypatch.setattr(yahoo, "fetch_sectors", lambda symbols: pd.DataFrame())
    monkeypatch.setattr(yahoo, "fetch_closes", feed.fetch_closes)
    monkeypatch.setattr(yahoo, "fetch_prices", feed.fetch_prices)
    monkeypatch.setattr(yahoo, "fetch_splits", feed.fetch_splits)
    # Gap checks read IVV and Nasdaq over the network; with flat closes there is nothing to check.
    monkeypatch.setattr(C.gapfill, "verify", lambda frame, raw, **_: None)
    monkeypatch.setattr(C.gapfill, "verify_latest", lambda frame, raw, sample, **_: {"suspect": False})
    monkeypatch.setattr(C.gapfill, "fill", lambda frame, raw, **_: (frame, raw, {}))
    return feed


def test_the_extras_are_priced_with_the_constituents_and_never_members(monkeypatch):
    feed = _patch_sources(monkeypatch)
    ctx = C.build_context(use_cache=False)
    assert set(EXTRAS) <= set(feed.requested[0])                          # asked of Yahoo in the constituent download
    assert set(EXTRAS) <= set(ctx.closes.columns)
    assert set(EXTRAS) <= set(ctx.prices.columns)
    assert ctx.closes[EXTRAS].notna().all().all()
    for key in ("SPX", "NDX"):
        assert not set(EXTRAS) & set(ctx.members[key]["yahoo_symbol"])
        assert not set(EXTRAS) & set(ctx.symbols_for(key))
        assert not set(EXTRAS) & set(ctx.priced(key)["yahoo_symbol"])


# --- Filings: a foreign filer with no statements is skipped and named ------------------

def _extracted(ticker: str, cik: int) -> dict:
    row = {"fiscal_year": 2025, "period_end": "2025-12-31", "nwc_basis": None}
    for item in sec.LINE_ITEMS:
        row[item.key] = 100.0
        row[f"{item.key}_filed"] = "2026-02-20"
    return {"entity_name": f"{ticker} Inc", "cik": cik, "source_ciks": [cik],
            "source_url": "https://example.test/facts", "rows": [row], "quarterly_rows": []}


def test_a_filer_with_no_statements_is_skipped_and_reported_not_faked(tmp_path, monkeypatch):
    monkeypatch.setattr(fin, "FINANCIALS_ARTIFACT_DIR", tmp_path)
    ciks = {"AAPL": 320193, "VIK": 1, "TOL": 2, "CZR": 3, "ALLY": 4}
    monkeypatch.setattr(sec, "fetch_ticker_cik_map", lambda *, use_cache=True: ciks)
    reason = sec.unextracted_reason(("dei", "ifrs-full"))

    def extract(ticker, cik, *, years, quarters=24, use_cache=True):
        if ticker == "VIK":
            raise ValueError(f"{ticker}: {reason}")
        return _extracted(ticker, cik)

    monkeypatch.setattr(sec, "extract_fundamentals", extract)
    members = {"SPX": pd.DataFrame({"yahoo_symbol": ["AAPL"], "name": ["Apple Inc."],
                                    "sector": ["Information Technology"]})}
    ctx = types.SimpleNamespace(config={"financials": {"indices": ["SPX"], "history_years": 2, "extra": EXTRAS}},
                                members=members, as_of="2026-10-09", log=BuildLog())
    out = fin.build(ctx, use_cache=False)
    assert set(out["skipped"]) == {"VIK"} and "reports under IFRS" in out["skipped"]["VIK"]
    assert {a["ticker"] for a in out["available"]} == {"AAPL", "TOL", "CZR", "ALLY"}
    assert not (tmp_path / "VIK.json").exists()
    assert (tmp_path / "TOL.json").exists()
    record = next(s for s in ctx.log.sources if s.source_id == "sec_financials")
    assert record.status == "partial" and record.error == "1 of 5 not extracted"


# --- Index aggregates: a name with no index membership or sector moves nothing ----------

def _company(ticker: str, sector: str | None, indices: list[str]) -> dict:
    return {"ticker": ticker, "sector": sector, "sub_sector": None, "indices": indices,
            "market_cap": 100.0, "price": 10.0, "eps_ntm": 1.1, "eps_fy0": 1.0, "eps_fy1": 1.2, "eps_fy_prev": 0.8}


def test_an_extra_with_no_index_or_sector_moves_no_index_or_sector_series():
    days = pd.bdate_range("2026-01-01", periods=V.MIN_HISTORY_SESSIONS + 60)
    rows = [_company(t, "Industrials", ["SPX"]) for t in ("AAA", "BBB", "CCC")]
    caps = {r["ticker"]: pd.Series(100.0, index=days) for r in rows}
    earn = {basis: {r["ticker"]: pd.Series(10.0, index=days) for r in rows} for basis in (V.OPERATING, V.REPORTED)}
    ctx = types.SimpleNamespace(indices=[types.SimpleNamespace(key="SPX", label="S&P 500")],
                                primary=types.SimpleNamespace(key="SPX"), config=load_config())
    base = panel._aggregates(ctx, rows, caps, earn, {})

    # VIK has filings, a price and a cap, but no index membership and no sector.
    with_extra = panel._aggregates(
        ctx, [*rows, _company("VIK", None, [])],
        {**caps, "VIK": pd.Series(9999.0, index=days)},
        {basis: {**series, "VIK": pd.Series(1.0, index=days)} for basis, series in earn.items()}, {})
    assert with_extra == base
