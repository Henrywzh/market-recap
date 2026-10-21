from datetime import date
import json

import numpy as np
import pandas as pd

from market_recap.config import load_config
from market_recap.panels import today, watch


AS_OF = date(2026, 10, 21)


def _cfg(**over) -> dict:
    cfg = {
        "event_days": 14, "history_sessions": 30, "history_years": 10,
        "kalshi_keys": {"cpi": "cpi_mom", "claims": "claims"},
        "series": {"oil": {"label": "Brent", "source": "yahoo", "symbol": "BZ=F", "unit": "$"},
                   "spx": {"label": "S&P 500", "source": "yahoo", "symbol": "^GSPC"}},
        "scenarios": [
            {"key": "oil", "name": "Oil shock", "thesis": "Crude jumps.", "added": "2026-10-01", "horizon": "2027-03-31",
             "match": "any", "triggers": [{"series": "oil", "measure": "level", "op": "above", "threshold": 120, "near": 112}]},
            {"key": "drop", "name": "Stocks drop", "added": "2026-10-01", "horizon": "2027-03-31", "match": "all",
             "triggers": [{"series": "spx", "measure": "change_pct", "sessions": 5, "op": "below", "threshold": -4, "near": -2}]},
        ],
    }
    return cfg | over


def _series(last_oil: float) -> dict[str, pd.Series]:
    idx = pd.bdate_range("2026-06-01", "2026-10-21")
    oil = pd.Series(100.0, index=idx)
    oil.iloc[-1] = last_oil
    spx = pd.Series(np.linspace(7000, 7100, len(idx)), index=idx)
    return {"oil": oil, "spx": spx}


def _scenarios_panel() -> dict:
    cls = {"n": 30, "dY2": {"mean": 6.0, "se": 1.5}, "SPY": {"mean": -0.2, "se": 0.2}}
    return {
        "drivers": [
            {"key": "cpi", "label": "CPI m/m", "unit": "pp", "status": "ok", "scale": 0.1, "miss_threshold": 0.05,
             "next": {"date": "2026-10-28", "time": "08:30", "forecast": 0.3, "previous": 0.4, "unit": "pp"},
             "classes": {"above": cls, "inline": {"n": 40, "dY2": None, "SPY": None}, "below": cls},
             "latest": {"date": "2026-09-30", "actual": 0.4, "forecast": 0.3, "surprise": 0.1, "cls": "above",
                        "dY2": 5.0, "SPY": -0.3}},
            {"key": "claims", "label": "Claims", "unit": "k", "status": "ok", "scale": 10.0, "miss_threshold": None,
             "next": {"date": "2026-10-23", "time": "08:30", "forecast": 200.0, "previous": 199.0, "unit": "k"},
             "classes": {}},
            # Outside the window: left out.
            {"key": "payrolls", "label": "Payrolls", "unit": "k", "status": "ok", "scale": 50.0,
             "next": {"date": "2026-11-20", "time": "08:30", "forecast": 100.0}, "classes": {}},
        ],
        "fomc": {"buckets": {"bp": 5, "hawkish": {"n": 20, "spy": -0.6}, "dovish": {"n": 22, "spy": 0.7}}},
    }


def _priced_panel() -> dict:
    return {
        "releases": [
            {"key": "cpi_mom", "release": "2026-10-28", "value": 0.28, "low": 0.1, "high": 0.4, "open_interest": 1000,
             "ladder": [[0.1, 0.95], [0.2, 0.8], [0.3, 0.3], [0.4, 0.1]]},
            {"key": "claims", "release": "2026-10-23", "value": 201.0, "low": 190.0, "high": 212.0, "open_interest": 50,
             "ladder": [[190.0, 0.9], [200.0, 0.55], [210.0, 0.2], [220.0, 0.05]]},
        ],
        "meetings": [{"date": "2026-10-28", "kalshi": {"outcomes": [{"label": "Hold", "change_bp": 0.0, "probability": 0.86}]}},
                     {"date": "2026-12-09", "kalshi": {"outcomes": []}}],
    }


def _assemble(last_oil: float = 100.0, **over) -> dict:
    return watch.assemble(as_of=AS_OF, series=_series(last_oil), scenarios=_scenarios_panel(),
                          priced=_priced_panel(), cfg=_cfg(**over), threshold_sd=0.5)


def test_scheduled_lists_releases_and_the_fomc_inside_the_window_soonest_first():
    events = _assemble()["events"]
    assert [(e["kind"], e["key"]) for e in events] == [("release", "claims"), ("release", "cpi"), ("fomc", "fomc")]
    cpi = events[1]
    # One-decimal series: above = prints above 0.3 (ladder at 0.3), below = 1 - ladder at 0.2.
    assert cpi["market"]["p_above"] == 0.3 and cpi["market"]["p_below"] == 0.2
    assert cpi["market"]["p_inline"] == 0.5
    assert cpi["band_basis"] == "any miss of the published tick"
    assert cpi["branches"]["above"] == {"n": 30, "dY2": 6.0, "dY2_se": 1.5, "SPY": -0.2, "SPY_se": 0.2}
    assert cpi["branches"]["inline"]["dY2"] is None
    assert cpi["latest"]["cls"] == "above"
    claims = events[0]
    # Continuous: the band is 0.5 robust SD of 10k = 5k either side of 200k.
    assert claims["band"] == 5.0
    assert claims["market"]["p_above"] is not None and claims["market"]["p_below"] is not None
    assert events[2]["market"]["outcomes"][0]["probability"] == 0.86
    assert events[2]["branches"]["hawkish"] == {"n": 20, "SPY": -0.6}


def test_a_release_without_a_kalshi_market_has_no_market_block():
    priced = _priced_panel()
    priced["releases"] = []
    events = watch.assemble(as_of=AS_OF, series=_series(100.0), scenarios=_scenarios_panel(), priced=priced,
                            cfg=_cfg(), threshold_sd=0.5)["events"]
    assert all(e["market"] is None for e in events if e["kind"] == "release")


def test_missing_inputs_leave_the_scheduled_list_empty():
    out = watch.assemble(as_of=AS_OF, series=_series(100.0), scenarios=None, priced=None, cfg=_cfg(), threshold_sd=0.5)
    assert out["events"] == []
    assert len(out["scenarios"]) == 2


def test_condition_states_follow_the_trigger_and_the_near_line():
    by = {s["key"]: s for s in _assemble(last_oil=121.0)["scenarios"]}
    oil = by["oil"]
    assert oil["state"] == "triggered" and oil["previous_state"] == "quiet" and oil["changed"]
    assert oil["first_triggered"] == "2026-10-21"
    assert oil["triggers"][0]["value"] == 121.0 and oil["triggers"][0]["met"]
    assert oil["triggers"][0]["label"] == "Brent" and oil["triggers"][0]["unit"] == "$"
    assert len(oil["triggers"][0]["history"]) == 30
    assert oil["episodes"]["count"] == 1
    near = {s["key"]: s for s in _assemble(last_oil=113.0)["scenarios"]}["oil"]
    assert near["state"] == "near" and not near["triggers"][0]["met"] and near["triggers"][0]["is_near"]
    drop = by["drop"]
    assert drop["state"] == "quiet"
    assert drop["triggers"][0]["label"] == "S&P 500 5-session change" and drop["triggers"][0]["unit"] == "%"


def test_a_missing_series_is_no_data_not_a_quiet_reading():
    series = _series(100.0)
    del series["spx"]
    out = watch.assemble(as_of=AS_OF, series=series, scenarios=None, priced=None, cfg=_cfg(), threshold_sd=0.5)
    drop = {s["key"]: s for s in out["scenarios"]}["drop"]
    assert drop["triggers"][0]["value"] is None
    assert drop["state"] in ("missing", None)


def test_payload_is_plain_json():
    json.dumps(_assemble(last_oil=121.0), allow_nan=False)


def test_today_lists_triggered_scenarios_and_state_changes_only():
    payload = _assemble(last_oil=121.0)
    items = today._watch_items(payload, "2026-10-21")
    assert [i["subject"] for i in items] == ["Oil shock"]
    item = items[0]
    assert item["kind"] == "watch" and item["link"] == "#watch" and item["new"] and item["importance"] == "high"
    assert item["title"].startswith("Oil shock triggered: Brent $121 (triggers at ≥ $120)")
    # Near but unchanged stays off TODAY; a change into near is listed.
    payload["scenarios"][0].update(state="near", previous_state="near", changed=False)
    assert today._watch_items(payload, "2026-10-21") == []
    payload["scenarios"][0].update(previous_state="quiet", changed=True)
    assert "near its trigger" in today._watch_items(payload, "2026-10-21")[0]["title"]


def test_config_scenarios_reference_known_series_and_valid_rules():
    cfg = load_config()["watch"]
    keys = set()
    for s in cfg["scenarios"]:
        assert s["key"] not in keys
        keys.add(s["key"])
        assert s.get("match", "all") in ("all", "any")
        assert date.fromisoformat(s["added"]) < date.fromisoformat(s["horizon"])
        for t in s["triggers"] + s.get("kill", []):
            assert t["series"] in cfg["series"]
            assert t["measure"] in ("level", "change_pct", "change_bp")
            assert t["op"] in ("above", "below")
            if t.get("near") is not None:
                # The near line sits before the threshold on the way to it.
                assert t["near"] < t["threshold"] if t["op"] == "above" else t["near"] > t["threshold"]
    for spec in cfg["series"].values():
        if spec["source"] == "ratio":
            assert all(k in cfg["series"] for k in spec["of"])
