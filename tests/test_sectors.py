"""SECTORS: keys read off the labels, cap-weighted sector returns, and the joins behind the hub."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap import validate
from market_recap.compute import sectors as S
from market_recap.panels import sectors as panel
from market_recap.util import BuildLog

KEY = re.compile(r"^[A-Z0-9.=-]{1,15}$")


@pytest.fixture(autouse=True)
def _isolated_artifacts(tmp_path, monkeypatch):
    # The panel writes one file per page and reads VALUATION histories: keep both out of the repo's artifacts.
    monkeypatch.setattr(panel, "SECTORS_ARTIFACT_DIR", tmp_path / "sectors")
    monkeypatch.setattr(panel, "VALUATION_ARTIFACT_DIR", tmp_path / "valuation")
    monkeypatch.setattr(panel, "FINANCIALS_ARTIFACT_DIR", tmp_path / "financials")


# --- compute helpers -------------------------------------------------------

@pytest.mark.parametrize("label, expected", [
    ("Soft Drinks & Non-alcoholic Beverages", "SDNB"),   # "&" skipped; a hyphenated word counts once
    ("Hotels, Resorts & Cruise Lines", "HRCL"),          # the comma goes with its word
    ("Oil & Gas Exploration & Production", "OGEP"),
    ("Health Care Services and Supplies", "HCSS"),       # "and" skipped in any case
    ("Institute OF Things", "IT"),                       # "of" skipped in any case
    ("Software - Infrastructure", "SI"),                 # a token with no letter counts for nothing
    ("&", "SUB"),                                        # nothing left: a fixed fallback, never empty
])
def test_initials_skip_the_joining_words(label, expected):
    assert S.initials(label) == expected


def test_a_sub_industry_key_is_its_sector_fund_and_initials():
    key = S.sub_key("XLP", "Soft Drinks & Non-alcoholic Beverages", set())
    assert key == "XLP-SDNB"
    assert S.sub_key("XLY", "Hotels, Resorts & Cruise Lines", set()) == "XLY-HRCL"


def test_a_collision_gets_a_digit_in_label_order_and_keeps_the_bare_key_for_the_first():
    taken: set[str] = set()
    keys = []
    for label in ["Health Care Services", "Health Care Systems", "Health Care Solutions"]:   # all HCS
        key = S.sub_key("XLV", label, taken)
        taken.add(key)
        keys.append(key)
    assert keys == ["XLV-HCS", "XLV-HCS2", "XLV-HCS3"]


def test_keys_fit_the_hash_argument_for_the_gics_labels_in_the_contract():
    labels = ["Soft Drinks & Non-alcoholic Beverages", "Hotels, Resorts & Cruise Lines", "Semiconductors",
              "Diversified Banks", "Regional Banks", "Homebuilding", "Aerospace & Defense",
              "Construction Machinery & Heavy Transportation Equipment",
              "Paper & Plastic Packaging Products & Materials"]
    for label in labels:
        key = S.sub_key("XLI", label, set())
        assert KEY.match(key) and len(key) <= 15, key


def test_a_member_with_no_return_is_left_out_and_the_rest_renormalised():
    members = [
        {"weight": 3.0, "returns": {"1M": 10.0, "3M": 4.0}},
        {"weight": 1.0, "returns": {"1M": None, "3M": 8.0}},   # no 1M return: out of 1M only
        {"weight": 1.0, "returns": {"1M": 2.0, "3M": None}},   # no 3M return: out of 3M only
    ]
    out = S.weighted_returns(members, ["1M", "3M"])
    assert out["1M"] == pytest.approx((3 * 10.0 + 1 * 2.0) / 4)
    assert out["3M"] == pytest.approx((3 * 4.0 + 1 * 8.0) / 4)


def test_a_period_no_member_has_is_none_and_a_missing_weight_counts_for_nothing():
    members = [{"weight": None, "returns": {"1D": 5.0}}, {"weight": 2.0, "returns": {"1D": None}}]
    assert S.weighted_returns(members, ["1D", "1W"]) == {"1D": None, "1W": None}
    assert S.weighted_returns([], ["1D"]) == {"1D": None}


def test_excess_is_none_when_either_side_is_missing():
    assert S.excess(3.0, 1.5) == pytest.approx(1.5)
    assert S.excess(None, 1.5) is None and S.excess(3.0, None) is None


def test_best_and_worst_rank_on_the_named_period_and_skip_missing_returns():
    members = [{"ticker": "B", "returns": {"3M": 8.0}}, {"ticker": "A", "returns": {"3M": -10.0}},
               {"ticker": "C", "returns": {"3M": None}}, {"ticker": "D", "returns": {}}]
    best, worst = S.best_and_worst(members, "3M")
    assert best == {"ticker": "B", "return": 8.0} and worst == {"ticker": "A", "return": -10.0}
    assert S.best_and_worst([{"ticker": "X", "returns": {}}], "3M") == (None, None)


# --- the panel, from hand-made inputs shaped like the real artifacts -------

CONFIG = {
    "universe": {"sectors": {"Consumer Staples": "XLP", "Energy": "XLE"}},
    # The thin threshold comes from INDUSTRIES' settings; this one is deliberately different.
    "industries": {"thin_below": 99, "no_pe_sectors": ["Real Estate"]},
    "sectors": {
        "sector_themes": {"Energy": "energy", "Consumer Staples": "staples"},
        "sub_industry_themes": {"Tobacco": "tobacco"},
        "valuation_min_members": 5,
    },
}
PERIODS = ["1D", "1M", "3M"]


def _name(ticker, sector, sub, weight, returns, price=10.0, name=None):
    return {"ticker": ticker, "name": name or f"{ticker} Co", "sector": sector, "sub_sector": sub,
            "weight": weight, "price": price, "returns": returns}


def _heatmaps():
    return {
        "as_of": "2026-10-12", "holdings_as_of": "2026-10-09", "periods": PERIODS,
        "constituents": [
            _name("KO", "Consumer Staples", "Soft Drinks & Non-alcoholic Beverages", 4.0,
                  {"1D": 1.0, "1M": 2.0, "3M": 8.0}, price=70.0, name="Coca-Cola Co"),
            _name("PEP", "Consumer Staples", "Soft Drinks & Non-alcoholic Beverages", 2.0,
                  {"1D": -1.0, "1M": 4.0, "3M": None}, price=150.0),
            _name("PM", "Consumer Staples", "Tobacco", 1.0, {"1D": 0.5, "1M": -3.0, "3M": -6.0}),
            _name("XOM", "Energy", "Oil & Gas Exploration & Production", 6.0,
                  {"1D": 2.0, "1M": 5.0, "3M": 10.0}, price=110.0),
            _name("CVX", "Energy", "Oil & Gas Exploration & Production", 3.0,
                  {"1D": 0.0, "1M": 1.0, "3M": -2.0}, price=150.0),
        ],
        "etfs": [
            {"ticker": "SPY", "returns": {"1D": 0.5, "1M": 1.0, "3M": 3.0}},
            {"ticker": "XLP", "returns": {"1D": 0.4, "1M": -1.0, "3M": 4.0}},
        ],   # XLE is not in the fund list: its own returns are null.
    }


def _industries():
    return {
        "settings": {"thin_below": 2, "no_pe_sectors": ["Real Estate"]},
        "sectors": [{
            "sector": "Energy", "above_ma": 60.0, "down_share": 40.0, "drawdown": -5.0,
            "revision": {"30d": -1.0, "90d": 2.0, "names": 2},
            "forward_pe": {"median": 11.0, "names": 2}, "pe_percentile": {"median": 30.0, "names": 2},
            "evidence": {"sold_off": False, "estimates_cut": True, "cheap_vs_own_history": True},
        }],
        "sub_industries": [{
            "sector": "Consumer Staples", "label": "Soft Drinks & Non-alcoholic Beverages",
            "above_ma": 100.0, "down_share": 0.0, "drawdown": -2.0,
            "revision": {"30d": 3.4, "90d": 7.1, "names": 2},
            "forward_pe": {"median": 24.0, "names": 2}, "pe_percentile": {"median": 60.0, "names": 2},
            "evidence": {"sold_off": False, "estimates_cut": False, "cheap_vs_own_history": False},
        }],
    }


def _rotation():
    return {"groups": [{"key": "Energy", "cap": {"quadrant": "leading"}},
                       {"key": "Consumer Staples", "cap": {"quadrant": "lagging"}}]}


def _valuation():
    return {
        "rows": [{"ticker": "KO", "pe_forward": 22.0, "pe_percentile": 60.0, "ptbv": 9.5,
                  "ptbv_percentile": 40.0, "rotce": 30.0},
                 {"ticker": "XOM", "pe_forward": 12.0, "pe_percentile": 20.0}],
        "aggregates": {"series": [
            {"key": "Energy", "kind": "sector",
             "stats": {"current": 12.0, "median": 14.0, "p25": 11.0, "p75": 17.0},
             "stats_ptbv": {"current": 2.0, "median": 2.5}},
            {"key": "SPX", "kind": "index", "stats": {"current": 22.0, "median": 20.0}},
        ]},
    }


def _monitor():
    return {"rows": [
        {"ticker": "KO", "drawdown_pct": -2.0, "above_ma": True, "candidate": False,
         "price_state": "stabilising", "evidence_state": "steady",
         "earnings_date": "2026-10-27", "earnings_status": "before_open",
         "expectations": {"eps": 3.0, "eps_30d": 2.9, "eps_90d": 2.8,
                          "change_30d_pct": 3.4, "change_90d_pct": 7.1}},
        {"ticker": "PEP", "drawdown_pct": -10.0, "above_ma": False, "candidate": True,
         "price_state": "weak", "evidence_state": "deteriorating",
         "earnings_date": None, "earnings_status": "not_scheduled",
         "expectations": {"eps": -1.0, "eps_30d": -0.9, "eps_90d": -0.8,
                          "change_30d_pct": 5.0, "change_90d_pct": 5.0}},   # a loss: no revision
        {"ticker": "PM", "drawdown_pct": -4.0, "above_ma": True, "candidate": None},
        {"ticker": "XOM", "drawdown_pct": -1.0, "above_ma": True, "candidate": False,
         "price_state": "weak", "evidence_state": "steady",
         "expectations": {"eps": 10.0, "eps_30d": 9.0, "eps_90d": 9.5,
                          "change_30d_pct": 1.0, "change_90d_pct": -2.0}},
        # CVX is not in MONITOR's rows.
    ]}


def _themes():
    return {"groups": [
        {"key": "staples", "label": "STAPLES", "proxy": "XLP", "bellwethers": ["KO", "PEP"]},
        {"key": "energy", "label": "ENERGY", "proxy": "XLE", "bellwethers": ["XOM", "CVX"]},
        {"key": "tobacco", "label": "TOBACCO", "proxy": "PM", "bellwethers": [{"symbol": "PM"}]},
        {"key": "cloud", "label": "CLOUD & AI CAPEX", "proxy": "equal-weight MSFT, NVDA",
         "bellwethers": [{"symbol": "MSFT", "impact": {}}, {"symbol": "NVDA"}]},
        {"key": "defense", "label": "DEFENSE", "proxy": "basket", "bellwethers": ["LMT"]},
    ]}


def _inputs(**overrides):
    inputs = {"heatmaps": _heatmaps(), "industries": _industries(), "rotation": _rotation(),
              "valuation": _valuation(), "monitor": _monitor(), "themes": _themes()}
    inputs.update(overrides)
    return inputs


def _ctx(config=CONFIG, closes=None, etf_closes=None):
    # No prices unless a test gives some: the page series are then empty, and the rest of the hub is unchanged.
    return SimpleNamespace(config=config, as_of="2026-10-12", log=BuildLog(),
                           closes=pd.DataFrame() if closes is None else closes,
                           etf_closes=pd.DataFrame() if etf_closes is None else etf_closes)


def _sector(out, label):
    return next(s for s in out["sectors"] if s["label"] == label)


def test_inputs_are_the_six_named_panels():
    assert panel.INPUTS == ("heatmaps", "industries", "rotation", "valuation", "monitor", "themes")


def test_the_hub_has_the_contract_keys_and_orders_sectors_then_subs_then_names_by_weight():
    out = panel.build(_ctx(), _inputs())
    assert set(out) == {"as_of", "periods", "benchmark", "market", "sectors", "sub_industries", "members", "themes", "notes", "missing"}
    assert out["as_of"] == "2026-10-12" and out["periods"] == PERIODS and out["missing"] == []
    assert [s["label"] for s in out["sectors"]] == ["Energy", "Consumer Staples"]   # 9.0 before 7.0
    assert out["benchmark"]["symbol"] == "SPY" and out["benchmark"]["returns"]["3M"] == 3.0
    assert [s["key"] for s in out["sectors"]] == ["XLE", "XLP"]
    assert [s["key"] for s in out["sub_industries"]] == ["XLE-OGEP", "XLP-SDNB", "XLP-T"]
    assert [m["ticker"] for m in out["members"]] == ["XOM", "KO", "CVX", "PEP", "PM"]
    assert all(KEY.match(s["key"]) for s in out["sub_industries"])
    assert len(out["notes"]) == 4
    # No VALUATION caps in these inputs, so the index has no aggregate and no expectations: every figure is null.
    assert out["market"] == {"forward_pe": None, "trailing_pe": None, "pe_percentile": None,
                             "eps_growth_next": None, "eps_growth_this": None, "revenue_growth": None}


def test_sector_returns_are_cap_weighted_and_a_missing_return_is_renormalised():
    out = panel.build(_ctx(), _inputs())
    staples = _sector(out, "Consumer Staples")
    # 3M: PEP has no return, so (4 * 8 + 1 * -6) / 5 rather than over all 7.
    assert staples["returns"] == {"1D": 0.36, "1M": 1.86, "3M": 5.2}
    assert staples["vs_index"] == {"1D": -0.14, "1M": 0.86, "3M": 2.2}
    assert staples["weight"] == 7.0 and staples["members"] == 3
    energy = _sector(out, "Energy")
    assert energy["returns"]["3M"] == 6.0 and energy["returns"]["1D"] == 1.33


def test_each_sector_joins_its_fund_its_rotation_quadrant_its_multiples_and_its_theme():
    out = panel.build(_ctx(), _inputs())
    staples, energy = _sector(out, "Consumer Staples"), _sector(out, "Energy")
    assert staples["etf"] == "XLP" and staples["etf_returns"] == {"1D": 0.4, "1M": -1.0, "3M": 4.0}
    assert energy["etf"] == "XLE" and energy["etf_returns"] is None          # fund absent: null
    assert energy["quadrant"] == "leading" and staples["quadrant"] == "lagging"
    # The hub's multiples are aggregates; with no VALUATION caps here there is no aggregate, and INDUSTRIES' medians stay.
    assert energy["forward_pe"] is None and energy["pe_percentile"] is None
    assert energy["forward_pe_median"] == 11.0 and energy["pe_percentile_median"] == 30.0
    assert energy["revision"] == {"30d": -1.0, "90d": 2.0, "names": 2}
    assert energy["evidence"] == {"sold_off": False, "estimates_cut": True, "cheap_vs_own_history": True}
    assert energy["above_200d"] == 60.0 and energy["down_share_1m"] == 40.0 and energy["median_drawdown"] == -5.0
    assert energy["valuation"] == {"pe_now": 12.0, "pe_median_10y": 14.0, "pe_p25": 11.0, "pe_p75": 17.0,
                                   "ptbv_now": 2.0, "ptbv_median_10y": 2.5}
    assert energy["best"] == {"ticker": "XOM", "return": 10.0} and energy["worst"] == {"ticker": "CVX", "return": -2.0}
    assert energy["sub_industries"] == ["XLE-OGEP"]
    assert energy["theme"] == "energy" and staples["theme"] == "staples"


def test_a_sub_industry_industries_read_takes_its_evidence_and_one_it_did_not_read_leaves_it_empty():
    out = panel.build(_ctx(), _inputs())
    soft, tobacco = (next(s for s in out["sub_industries"] if s["key"] == k) for k in ("XLP-SDNB", "XLP-T"))
    assert soft["members"] == 2 and soft["weight"] == 6.0
    assert soft["returns"]["3M"] == 8.0            # PEP's 3M is missing: KO alone
    assert soft["above_200d"] == 100.0 and soft["median_drawdown"] == -2.0
    assert soft["revision"] == {"30d": 3.4, "90d": 7.1, "names": 2}
    assert soft["forward_pe_median"] == 24.0 and soft["pe_percentile_median"] == 60.0
    assert soft["forward_pe"] is None and soft["trailing_pe"] is None and soft["path"] is None
    assert soft["evidence"]["cheap_vs_own_history"] is False
    assert soft["theme"] is None and soft["sector"] == "Consumer Staples" and soft["sector_key"] == "XLP"
    # Not in INDUSTRIES: returns and weight from the names, the evidence empty.
    assert tobacco["returns"]["1M"] == -3.0 and tobacco["weight"] == 1.0
    assert tobacco["above_200d"] is None and tobacco["forward_pe"] is None
    assert tobacco["revision"] == {"30d": None, "90d": None, "names": None}
    assert tobacco["evidence"] == {"sold_off": None, "estimates_cut": None, "cheap_vs_own_history": None}
    assert tobacco["theme"] == "tobacco"


def test_thin_is_read_from_the_industries_settings_not_the_config():
    out = panel.build(_ctx(), _inputs())
    thin = {s["key"]: s["thin"] for s in out["sub_industries"]}
    assert thin == {"XLE-OGEP": False, "XLP-SDNB": False, "XLP-T": True}   # settings say 2: a name alone is thin


def test_each_name_joins_its_monitor_and_valuation_rows_and_a_missing_row_leaves_nulls():
    out = panel.build(_ctx(), _inputs())
    members = {m["ticker"]: m for m in out["members"]}
    ko = members["KO"]
    assert ko["name"] == "Coca-Cola Co" and ko["sector_key"] == "XLP" and ko["sub_key"] == "XLP-SDNB"
    assert ko["drawdown"] == -2.0 and ko["above_200d"] is True
    assert ko["revision_30d"] == 3.4 and ko["revision_90d"] == 7.1      # the monitor's own change, as INDUSTRIES reads it
    assert ko["forward_pe"] == 22.0 and ko["pe_percentile"] == 60.0 and ko["ptbv"] == 9.5 and ko["rotce"] == 30.0
    assert ko["next_report"] == {"date": "2026-10-27", "timing": "before_open"}
    assert ko["monitor"] == {"queued": False, "price_state": "stabilising", "evidence_state": "steady"}
    pep = members["PEP"]
    assert pep["revision_30d"] is None and pep["revision_90d"] is None    # a loss is not a revision
    assert pep["next_report"] is None and pep["monitor"]["queued"] is True
    assert pep["forward_pe"] is None and pep["price"] == 150.0
    cvx = members["CVX"]                                                  # in no monitor or valuation row
    assert cvx["drawdown"] is None and cvx["forward_pe"] is None and cvx["monitor"]["queued"] is None
    assert cvx["returns"]["1D"] == 0.0 and cvx["weight"] == 3.0


def test_the_theme_map_ties_groups_to_sectors_and_subs_and_lists_the_rest_across_sectors():
    out = panel.build(_ctx(), _inputs())
    assert [t["key"] for t in out["themes"]] == ["cloud", "defense"]        # staples, energy, tobacco are mapped
    cloud = out["themes"][0]
    assert cloud == {"key": "cloud", "label": "CLOUD & AI CAPEX", "proxy": "equal-weight MSFT, NVDA",
                     "members": ["MSFT", "NVDA"]}
    assert out["themes"][1]["members"] == ["LMT"]


def test_a_missing_monitor_leaves_its_fields_null_and_is_named():
    out = panel.build(_ctx(), _inputs(monitor=None))
    assert out["missing"] == ["monitor"]
    ko = next(m for m in out["members"] if m["ticker"] == "KO")
    assert ko["drawdown"] is None and ko["revision_30d"] is None and ko["next_report"] is None
    assert ko["monitor"] == {"queued": None, "price_state": None, "evidence_state": None}
    # What MONITOR does not feed is still there.
    assert ko["forward_pe"] == 22.0 and _sector(out, "Energy")["quadrant"] == "leading"


def test_a_missing_input_is_named_and_its_dependent_sector_fields_are_null():
    out = panel.build(_ctx(), _inputs(industries=None, rotation=None, valuation=None, themes=None))
    assert out["missing"] == ["industries", "rotation", "valuation", "themes"]
    energy = _sector(out, "Energy")
    assert energy["forward_pe"] is None and energy["quadrant"] is None
    assert energy["valuation"] == {k: None for k in ("pe_now", "pe_median_10y", "pe_p25", "pe_p75", "ptbv_now", "ptbv_median_10y")}
    assert energy["returns"]["3M"] == 6.0                                  # from the names alone
    assert out["themes"] == []


def test_without_heatmaps_there_are_no_names_to_show_so_the_panel_says_so():
    with pytest.raises(RuntimeError, match="heatmaps"):
        panel.build(_ctx(), _inputs(heatmaps=None))


def test_real_estate_shows_no_earnings_multiple_but_keeps_its_book_value():
    heatmaps = {"periods": ["1D"], "constituents": [
        _name("O", "Real Estate", "Retail REITs", 1.0, {"1D": 1.0}),
    ], "etfs": []}
    valuation = {"rows": [{"ticker": "O", "pe_forward": 40.0, "pe_percentile": 80.0, "ptbv": 1.5, "ptbv_percentile": 50.0}],
                 "aggregates": {"series": [{"key": "Real Estate", "kind": "sector",
                                            "stats": {"current": 40.0, "median": 30.0},
                                            "stats_ptbv": {"current": 1.5, "median": 1.6}}]}}
    out = panel.build(_ctx(), {"heatmaps": heatmaps, "valuation": valuation})
    member = out["members"][0]
    assert member["forward_pe"] is None and member["pe_percentile"] is None and member["ptbv"] == 1.5
    real_estate = out["sectors"][0]
    assert real_estate["valuation"]["pe_now"] is None and real_estate["valuation"]["ptbv_now"] == 1.5
    assert real_estate["etf"] is None and real_estate["key"] == "S-RE"   # no fund configured: a labelled fallback key


def test_the_validator_notes_a_missing_input_and_flags_an_empty_hub():
    findings = validate._check_sectors({"missing": ["monitor"], "sectors": [{}]})
    assert [(f.severity, f.check) for f in findings] == [("notice", "sectors")]
    assert "monitor" in findings[0].detail
    assert validate._check_sectors({"missing": [], "sectors": [{}]}) == []
    assert validate._check_sectors(None) == []
    assert validate._check_sectors({"missing": [], "sectors": []})[0].severity == "warning"


def test_the_build_runs_sectors_after_industries_and_before_overview_with_its_declared_inputs(tmp_path, monkeypatch):
    import pandas as pd
    from market_recap import build, config

    ctx = SimpleNamespace(config=CONFIG, as_of="2026-10-12", holdings_as_of="2026-10-09", log=BuildLog(),
                          indices=[], closes=pd.DataFrame(), filled_sessions={}, session_check=None,
                          adjustments=[], price_jumps=[], diagnostics={})
    monkeypatch.setattr(build, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(build, "ensure_dirs", lambda: None)
    # The manifest reads the brand; everything else the build reads is faked.
    monkeypatch.setattr(build, "load_config", lambda: {**CONFIG, "brand": config.load_config()["brand"]})
    monkeypatch.setattr(build, "build_context", lambda **kw: ctx)
    monkeypatch.setattr(build.sec, "filing_check", lambda: {"checked": 0})
    monkeypatch.setattr(build.site, "build", lambda: {})
    monkeypatch.delenv("MONITOR_PUBLISHED_STATE", raising=False)
    seen = {}

    def fake(name):
        def build_fake(ctx, inputs):
            seen[name] = inputs
            return {"as_of": ctx.as_of}
        return build_fake

    monkeypatch.setattr(build, "PANELS", {name: fake(name) for name in ("overview", "sectors", "industries")})
    manifest = build.run(panels=["overview", "sectors", "industries"], prune_cache=False)
    assert manifest["panels"] == ["industries", "sectors", "overview"]
    assert set(seen["sectors"]) == set(panel.INPUTS)


def test_a_sub_industry_mapped_to_a_valuation_band_carries_it_and_the_others_do_not():
    config = {**CONFIG, "sectors": {**CONFIG["sectors"], "sub_industry_valuation": {"Tobacco": "staples-tobacco"}}}
    valuation = _valuation()
    valuation["aggregates"]["series"].append({"key": "staples-tobacco", "kind": "subsector",
                                              "stats": {"current": 15.0, "median": 13.0, "p25": 12.0, "p75": 16.0},
                                              "stats_ptbv": {"current": 4.0, "median": 3.0}})
    out = panel.build(_ctx(config), _inputs(valuation=valuation))
    subs = {s["label"]: s for s in out["sub_industries"]}
    assert subs["Tobacco"]["valuation"] == {"pe_now": 15.0, "pe_median_10y": 13.0, "pe_p25": 12.0, "pe_p75": 16.0,
                                            "ptbv_now": 4.0, "ptbv_median_10y": 3.0}
    assert subs["Soft Drinks & Non-alcoholic Beverages"]["valuation"] is None
