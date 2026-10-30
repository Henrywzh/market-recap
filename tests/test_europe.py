"""EUROPE: symbol mapping, currency arithmetic and the panel, on data whose answer is known."""

import json

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import europe as E
from market_recap.config import load_config
from market_recap.panels import europe as P
from market_recap.sources import europe as S


def test_ftse_epic_codes_become_london_yahoo_symbols():
    assert S.ftse_symbol("HSBA") == "HSBA.L"
    assert S.ftse_symbol("BT.A") == "BT-A.L"
    assert S.ftse_symbol("BP.") == "BP.L"
    assert S.ftse_symbol(" azn ") == "AZN.L"


def test_the_ftse_table_is_read_by_its_headers_with_or_without_an_isin_column():
    old = pd.DataFrame({"Company": ["3i", "BT Group"], "Ticker": ["III", "BT.A"],
                        "FTSE industry classification benchmark sector[12]": ["Investment Banking ", "Telecom"]})
    # October 2026: an ISIN column between the ticker and the sector.
    new = old.copy()
    new.insert(2, "ISIN[34]", ["GB00B1YW4409", "GB0030913577"])
    for table in (old, new):
        out = S.parse_ftse_table(table)
        assert list(out.columns) == ["symbol", "name", "sector_source"]
        assert out["symbol"].tolist() == ["III.L", "BT-A.L"]
        assert out["sector_source"].tolist() == ["Investment Banking", "Telecom"]
    with pytest.raises(ValueError, match="ticker"):
        S.parse_ftse_table(old.drop(columns=["Ticker"]))


def test_every_ftse_100_sector_label_of_october_2026_maps_to_a_broad_sector():
    # The ICB sector labels Wikipedia's FTSE 100 table carried on 2026-10-26.
    labels = ["Aerospace and Defense", "Banks", "Beverages", "Chemicals", "Closed End Investments",
              "Construction and Materials", "Consumer Services", "Electricity", "Electronic and Electrical Equipment",
              "Finance and Credit Services", "Food Producers", "Gas, Water and Multi-utilities", "General Industrials",
              "Household Goods and Home Construction", "Industrial Engineering", "Industrial Metals and Mining",
              "Industrial Support Services", "Investment Banking and Brokerage Services", "Leisure Goods", "Life Insurance",
              "Media", "Medical Equipment and Services", "Non-life Insurance", "Non-Renewable Energy", "Personal Goods",
              "Personal Care, Drug and Grocery Stores", "Pharmaceuticals, Biotechnology and Marijuana Producers",
              "Precious Metals and Mining", "Real Estate Investment Trusts", "Retailers", "Software and Computer Services",
              "Telecommunications Service Providers", "Tobacco", "Travel and Leisure"]
    mapping = load_config()["europe"]["sector_map"]
    assert [label for label in labels if E.broad_sector(label, mapping) == "Other"] == []
    assert E.broad_sector("Non-Renewable Energy", mapping) == "Energy"
    assert E.broad_sector("Pharmaceuticals, Biotechnology and Marijuana Producers", mapping) == "Health Care"


def test_a_symbol_quotes_in_the_currency_of_its_exchange_and_an_index_in_none():
    assert [E.currency_of(s) for s in ("HSBA.L", "MC.PA", "ASML.AS", "CFR.SW", "RACE.MI", "^FTSE", "SPY")] == ["GBp", "EUR", "EUR", "CHF", "EUR", None, None]
    assert E.currency_of("XYZ.L", {"XYZ.L": "USD"}) == "USD"                       # a dollar line on London
    assert E.currency_of("AAA.ZZ") is None


def test_broad_sector_maps_any_case_and_leaves_the_unknown_as_other():
    mapping = {"banks": "Financials", "pharmaceuticals & biotechnology": "Health Care"}
    assert E.broad_sector("Banks", mapping) == "Financials" and E.broad_sector("  PHARMACEUTICALS & Biotechnology ", mapping) == "Health Care"
    assert E.broad_sector("Space mining", mapping) == "Other" and E.broad_sector(None, mapping) == "Other"
    cfg = load_config()["europe"]
    assert E.broad_sector("Life insurance", cfg["sector_map"]) == "Financials" and E.broad_sector("Aerospace & defence", cfg["sector_map"]) == "Industrials"


def test_a_dollar_series_compounds_the_local_return_with_the_currency_and_pence_are_pounds():
    idx = pd.bdate_range("2026-01-05", periods=4)
    local = pd.Series([100.0, 110.0, 110.0, 121.0], index=idx)
    fx = pd.Series([1.0, 1.0, 1.1, 1.1], index=idx)                                # the currency gains 10% on day 3
    usd = E.in_dollars(local, fx)
    assert list(usd) == pytest.approx([100.0, 110.0, 121.0, 133.1])
    pence = E.in_dollars(pd.Series([10000.0], index=idx[:1]), pd.Series([1.25], index=idx[:1]), pence=True)
    assert pence.iloc[0] == pytest.approx(125.0)                                   # 10,000p = 100 pounds = 125 dollars
    # a holiday in the currency's own calendar carries the last rate over
    gap = E.in_dollars(local, fx.drop(idx[1]))
    assert gap.iloc[1] == pytest.approx(110.0)


def test_relative_to_is_the_ratio_rebased_on_the_common_days():
    idx = pd.bdate_range("2026-01-05", periods=3)
    s = pd.Series([10.0, 12.0, 15.0], index=idx)
    b = pd.Series([100.0, 100.0, 125.0], index=idx[:3])
    r = E.relative_to(s, b)
    assert list(r) == pytest.approx([100.0, 120.0, 120.0]) and E.relative_to(s, pd.Series(dtype=float)).empty


def test_yahoo_multiples_parse_and_a_reply_with_nothing_is_none():
    payload = {"quoteSummary": {"result": [{"summaryDetail": {"forwardPE": {"raw": 15.6}, "trailingPE": {"raw": 17.4}},
                                            "defaultKeyStatistics": {"forwardEps": {"raw": 22.0}, "trailingEps": {"raw": 19.0}},
                                            "price": {"marketCap": {"raw": 1.9e11}, "regularMarketPrice": {"raw": 380.0}, "currency": "EUR"}}]}}
    got = S.parse_multiples(payload)
    assert got == {"forward_pe": 15.6, "trailing_pe": 17.4, "forward_eps": 22.0, "trailing_eps": 19.0, "market_cap": 1.9e11, "price": 380.0, "currency": "EUR"}
    assert S.parse_multiples({"quoteSummary": {"result": [{"price": {"currency": "EUR"}}]}}) is None
    assert S.parse_multiples({}) is None and S.parse_multiples(None) is None


# --- the panel ---------------------------------------------------------------------

class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def fail(self, *a):
        raise AssertionError(a)


def _cfg():
    cfg = dict(load_config()["europe"])
    cfg.update(indices=[{"key": "ftse100", "label": "FTSE 100", "symbol": "^FTSE", "currency": "GBP"},
                        {"key": "dax", "label": "DAX", "symbol": "^GDAXI", "currency": "EUR"}],
               sectors=[{"key": "banks", "label": "Banks", "symbol": "EXV1.DE"}],
               universes=[{"key": "ftse100", "label": "FTSE 100", "source": "ftse100"}],
               groups=[{"key": "lux", "label": "LUX", "members": [{"symbol": "RMS.PA", "name": "Hermes", "sector": "Consumer Discretionary"}]},
                       {"key": "fin", "label": "FIN", "from_universe": "ftse100", "sector": "Financials"}],
               rotation_benchmark="EXSA.DE", chart_years=1)
    return cfg


def _world(monkeypatch, *, drop=()):
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2025-01-02", periods=420)
    syms = ["^FTSE", "^GDAXI", "EXV1.DE", "EXSA.DE", "GBPUSD=X", "EURUSD=X", "CHFUSD=X", "SPY", "^GSPC", "HSBA.L", "AZN.L", "RMS.PA"]
    closes = pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))) for s in syms}, index=idx)
    closes["HSBA.L"] = closes["HSBA.L"].where(closes.index != idx[200])                   # a London holiday that Paris traded
    closes = closes.drop(columns=list(drop))
    members = pd.DataFrame({"symbol": ["HSBA.L", "AZN.L"], "name": ["HSBC", "AstraZeneca"], "sector_source": ["Banks", "Pharmaceuticals & biotechnology"]})
    monkeypatch.setattr(P.yahoo, "fetch_closes", lambda syms, **kw: closes)
    monkeypatch.setattr(P.src, "fetch_ftse100", lambda **kw: (members, "https://example.test/ftse"))
    monkeypatch.setattr(P.src, "fetch_multiples", lambda syms, **kw: ({"HSBA.L": {"forward_pe": 9.9, "trailing_pe": 11.0, "market_cap": 1.5e11}, "RMS.PA": {"forward_pe": 26.0}}, {"AZN.L": "none"}))
    monkeypatch.setattr(P.estimates, "fetch_trends", lambda syms, **kw: ({"HSBA.L": {"0y": {"eps": 1.1, "year_ago_eps": 1.0}}, "AZN.L": {"0y": {"eps": 100.0, "year_ago_eps": 1.0}}}, {}))
    cfg = load_config()
    cfg["europe"] = _cfg()
    return type("C", (), {"config": cfg, "as_of": idx[-1].date().isoformat(), "log": _Log()})()


def test_panel_builds_indices_sectors_names_and_groups_without_inventing(monkeypatch):
    ctx = _world(monkeypatch)
    p = P.build(ctx)
    json.dumps(p, allow_nan=False)
    ix = {r["key"]: r for r in p["indices"]}
    assert ix["ftse100"]["returns"]["1M"] is not None and ix["ftse100"]["returns_usd"]["1M"] is not None
    assert ix["ftse100"]["returns_usd"]["1M"] != ix["ftse100"]["returns"]["1M"]                  # the currency's move is in the dollar return
    assert p["sectors"][0]["relative"]["3M"] is not None and p["sectors"][0]["currency"] == "EUR"
    uni = p["universes"]["ftse100"]
    names = {n["symbol"]: n for n in uni["names"]}
    assert names["HSBA.L"]["sector"] == "Financials" and names["HSBA.L"]["forward_pe"] == 9.9 and names["HSBA.L"]["eps_growth"] == pytest.approx(10.0)
    assert names["AZN.L"]["forward_pe"] is None and names["AZN.L"]["eps_growth"] is None and names["AZN.L"]["eps_growth_out_of_range"] is True   # +9,900%: not a growth rate
    assert names["HSBA.L"]["currency"] == "GBp"
    groups = {g["key"]: g for g in p["groups"]}
    assert [n["symbol"] for n in groups["fin"]["names"]] == ["HSBA.L"] and groups["lux"]["names"][0]["sector"] == "Consumer Discretionary"
    assert p["chart"]["series"]["FTSE 100"][0] == pytest.approx(100.0) and "SPY" in p["chart"]["series"]
    assert p["inputs"]["no_prices"] == [] and {r.source_id for r in ctx.log.records} == {"europe_prices", "europe_multiples"}


def test_returns_use_each_series_own_trading_days_so_a_holiday_is_not_a_one_day_move(monkeypatch):
    ctx = _world(monkeypatch)
    p = P.build(ctx)
    hs = next(n for n in p["universes"]["ftse100"]["names"] if n["symbol"] == "HSBA.L")
    assert hs["returns"]["1D"] is not None and abs(hs["returns"]["1D"]) < 10             # the missing session is not stepped over as a gap


def test_a_symbol_without_prices_is_named_and_the_rest_stands(monkeypatch):
    ctx = _world(monkeypatch, drop=["AZN.L", "CHFUSD=X"])
    p = P.build(ctx)
    assert "AZN.L" in p["inputs"]["no_prices"]
    az = next(n for n in p["universes"]["ftse100"]["names"] if n["symbol"] == "AZN.L")
    assert az["last"] is None and az["returns"]["1M"] is None and az["drawdown_pct"] is None
    rec = {r.source_id: r for r in ctx.log.records}["europe_prices"]
    assert rec.status == "partial" and "AZN.L" in rec.error
    json.dumps(p, allow_nan=False)


def test_an_unavailable_universe_is_a_named_gap_not_a_failure(monkeypatch):
    ctx = _world(monkeypatch)
    monkeypatch.setattr(P.src, "fetch_ftse100", lambda **kw: (_ for _ in ()).throw(RuntimeError("wikipedia down")))
    p = P.build(ctx)
    assert "unavailable" in p["universes"]["ftse100"] and "wikipedia down" in p["inputs"]["universes_unavailable"]["ftse100"]
    assert [g["key"] for g in p["groups"]] == ["lux", "fin"] and p["groups"][1]["names"] == []      # the derived group is empty, not invented


def test_each_universe_carries_the_us_session_cards_on_its_index_own_days(monkeypatch):
    ctx = _world(monkeypatch)
    p = P.build(ctx)
    json.dumps(p, allow_nan=False)
    s = p["universes"]["ftse100"]["session"]
    assert s["members"] == 2 and s["1D"]["up"] + s["1D"]["down"] <= 2 and s["above_200d"] is not None
    assert s["history"]["dates"][-1] == ctx.as_of and len(s["gainers"]) == 2 and s["gainers"][0]["change_pct"] >= s["losers"][0]["change_pct"]
    # Only HSBC has a market cap, so it carries the whole weight: its contribution is its return.
    c = s["contributions"]
    assert c["weighted"] == 1 and c["total_pp"] == pytest.approx(next(g for g in s["gainers"] if g["ticker"] == "HSBA.L")["change_pct"], abs=1e-2)
    assert c["index_pct"] == pytest.approx(next(r for r in p["indices"] if r["key"] == "ftse100")["returns"]["1D"], abs=1e-2)
    # 420 sessions of history: no 3Y / 5Y / 10Y window drawn short under its label.
    assert "1Y" in s["price_chart"] and "3Y" not in s["price_chart"]
    assert list(p["performance"]["series"]) == ["FTSE 100", "S&P 500"]


def test_a_member_listed_twice_is_counted_once(monkeypatch):
    ctx = _world(monkeypatch)
    twice = pd.DataFrame({"symbol": ["HSBA.L", "AZN.L", "HSBA.L"], "name": ["HSBC", "AstraZeneca", "HSBC"],
                          "sector_source": ["Banks", "Pharmaceuticals & biotechnology", "Banks"]})
    monkeypatch.setattr(P.src, "fetch_ftse100", lambda **kw: (twice, "https://example.test/ftse"))
    assert P.build(ctx)["universes"]["ftse100"]["session"]["members"] == 2
