"""TODAY: each list cut from small fixtures, the history merge and cap, and the failure paths."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_recap import validate
from market_recap.config import load_config
from market_recap.panels import today

AS_OF = "2026-10-16"


@pytest.fixture(autouse=True)
def no_published_state(monkeypatch):
    # No test reads the live site: the previous TODAY is off unless a test turns it on.
    monkeypatch.delenv("TODAY_PUBLISHED_STATE", raising=False)


def _ctx(config=None):
    return SimpleNamespace(as_of=AS_OF, config=deepcopy(config or load_config()))


def _catalysts():
    return {
        "as_of": AS_OF,
        "events": [
            {"lane": "macro", "event_type": "economic_release", "title": "CPI", "date": "2026-10-20", "time": "08:30",
             "importance": "high", "expectations": [{"kind": "survey", "source": "tradingview", "source_label": "TradingView",
                                                      "label": "CPI", "value": 0.3, "unit": "%", "decimals": 1}]},
            {"lane": "macro", "event_type": "economic_release", "title": "Minor print", "date": "2026-10-19",
             "importance": "low"},
            {"lane": "macro", "event_type": "market_structure", "rule": "vix_expiry", "title": "VIX options & futures expiry",
             "date": "2026-10-21", "time": "09:30", "importance": "low", "detail": "Settles at the open."},
            {"lane": "macro", "event_type": "central_bank", "title": "FOMC decision (statement)", "date": "2026-10-28",
             "time": "14:00", "importance": "high", "expiry_watch": None},
            {"lane": "macro", "event_type": "economic_release", "title": "Far away", "date": "2026-11-15", "importance": "high"},
            {"lane": "single_name", "event_type": "earnings", "symbol": "META", "date": "2026-10-21", "timing": "amc",
             "importance": "high", "index_weights": {"SPX": 2.434}, "eps_forecast": 2.0},
            {"lane": "single_name", "event_type": "earnings", "symbol": "SMALL", "date": "2026-10-19", "timing": "bmo",
             "importance": "low", "index_weights": {"SPX": 0.1}},
            {"lane": "single_name", "event_type": "earnings", "symbol": "WATCH", "date": "2026-10-19", "timing": "bmo",
             "importance": "low", "index_weights": {"SPX": 0.05}, "watchlist": True, "eps_forecast": 0.5},
            {"lane": "single_name", "event_type": "earnings", "symbol": "LATEX", "date": "2026-10-28", "timing": "amc",
             "importance": "high", "index_weights": {"SPX": 1.0}},
        ],
        "recent": {
            "session": AS_OF,
            "macro": [{"event_key": "bls:2026-10-16:import", "title": "Import & export prices", "date": "2026-10-16",
                       "time": "08:30", "importance": "low",
                       "prints": [{"label": "Import prices", "value": 1.2, "unit": "%", "decimals": 1, "period": "2026-09"}],
                       "expectations": []},
                      {"event_key": "rule:2026-10-16:monthly-opex", "title": "Monthly options expiry", "date": "2026-10-16",
                       "time": "09:30", "importance": "low", "rule": "monthly_opex", "event_type": "market_structure",
                       "prints": [], "expectations": []}],
            "earnings_reacted": [{"symbol": "TRV", "date": AS_OF, "eps": 9.18, "eps_forecast": 7.07,
                                  "surprise_pct": 29.84, "return_1d": 1.47, "index_weights": {"SPX": 0.12}}],
            "earnings_after_close": [{"symbol": "AFTER", "date": AS_OF, "timing": "amc", "index_weights": {"SPX": 0.5}}],
        },
    }


def _moves():
    return {
        "rows": [
            {"ticker": "NVDA", "ret_pct": -4.0, "z": -4.44, "z_own": -3.0, "own_pct": -2.7, "market_pct": -0.8,
             "sector_pct": -1.2, "sigma_pct": 0.9, "direction": "down", "reported": False,
             "tags": {"reported": False, "gap_led": True, "repeat": False, "vix_high": None,
                      "stock_above_200d": True, "market_above_200d": True}},
            {"ticker": "AEE", "ret_pct": 2.24, "z": 2.54, "z_own": 1.48, "own_pct": 0.71, "market_pct": -0.79,
             "sector_pct": 2.33, "sigma_pct": 0.88, "direction": None, "reported": False, "tags": None},
            {"ticker": "XOM", "ret_pct": 2.4, "z": 2.1, "z_own": 2.2, "own_pct": 1.9, "market_pct": 0.1,
             "sector_pct": 0.3, "sigma_pct": 1.14, "direction": "up", "reported": False,
             "tags": {"reported": False, "gap_led": False, "repeat": None, "vix_high": False,
                      "stock_above_200d": True, "market_above_200d": True}},
            {"ticker": "TRV", "ret_pct": 1.47, "z": 2.1, "z_own": 0.5, "sigma_pct": 0.7, "direction": None, "reported": True},
        ],
        "unusual": ["AEE", "NVDA", "XOM"],
        "move_states": {"rows": [
            {"key": "all", "direction": "down", "match": {}},
            {"key": "up_report", "direction": "up", "match": {"reported": True}},
        ]},
        "sector_selloff": {"active": False, "fund": "XLK", "z": -1.11, "spy_z": -1.6, "losers": []},
    }


def _state(key, label, active, days_now):
    return {"key": key, "label": label, "rule": f"{label} rule", "active_now": active, "days_now": days_now}


def _market_state():
    return {"states": [
        _state("small_caps_lag", "SMALL CAPS LAG", True, 1),
        _state("narrow", "NARROW LEADERSHIP", True, 4),
        _state("stress", "STRESS", False, 0),
    ]}


def _tile(key, label, risk_when, threshold, value, recent, breach, unit=None):
    return {"key": key, "label": label, "risk_when": risk_when, "threshold": threshold, "value": value,
            "unit": unit, "breach": breach, "recent": {"dates": [], "values": recent} if recent is not None else None}


def _risk():
    return {"sections": [{"key": "volatility", "tiles": [
        _tile("skew", "SKEW", "high", 150, 168.59, [140.0, 168.59], True),
        _tile("ccc_oas", "CCC OAS", "high", 1000, 1278.0, [1300.0, 1278.0], True),
        _tile("vx_front", "VX FRONT", "low", 0, -0.08, [0.96, -0.08], True),
        _tile("hyg", "HYG", "low", -2, -1.05, [-0.63, -1.05], False),
        _tile("drop", "DROPPING", "high", 20, 10.0, [25.0, 10.0], False),
        _tile("cftc_es", "CFTC ES", "extreme", 5, -21.2, None, True),
    ]}]}


def _anchor(exposure):
    return {"history": {"dates": ["2026-10-15", AS_OF][: len(exposure)], "exposure": exposure}, "changes": []}


def _positioning():
    base = [1.0 + 0.001 * i for i in range(100)]
    values = base + [1.05, 1.5]  # yesterday mid-range, today above every reading in its history
    return {
        "index_put_call": {"series": [{"key": "spx", "windows": {"1D": {"values": values}}}]},
        "blackout": {"now_pct": 76.4, "momentum": {"windows": [{"key": "1D", "ahead_delta_pp": -1.4},
                                                              {"key": "7D", "ahead_delta_pp": -2.6}]}},
    }


def _inputs(events_dir=None):
    return {
        "catalysts": _catalysts(),
        "moves": _moves(),
        "market_state": _market_state(),
        "risk": _risk(),
        "anchor": _anchor([0.5, 0.44]),
        "positioning": _positioning(),
        "monitor": {"changes": [
            {"ticker": "ABC", "sector": "Health Care", "kind": "entered", "text": "Entered the queue: drawdown deeper than 20%"},
            {"ticker": "DEF", "sector": "Health Care", "kind": "left", "text": "Left the queue"},
        ]},
        "catalyst_log": {"items": [
            {"key": "old_item", "date": "2026-10-02", "title": "Too old", "kind": "supply"},
            {"key": "recent_item", "date": "2026-10-14", "title": "Inside the window", "kind": "competition", "source": "TrendForce"},
            {"key": "today_item", "date": AS_OF, "title": "Today", "kind": "demand"},
        ]},
        "themes": {"groups": [{"key": "semis", "label": "Semis", "calendar": [
            {"date": "2026-10-20", "kind": "data", "title": "Quanta monthly revenue (2026-10)", "late": False},
            {"date": "2026-10-20", "kind": "data", "title": "Quanta monthly revenue (2026-10)", "late": False},
            {"date": "2026-10-19", "kind": "earnings", "symbol": "XX"},
        ]}]},
        "evidence": {"names": {"META": {"options": {"implied_move": {"straddle_pct": 6.1, "expiry": "2026-11-06"}}}}},
    }


# A directory with no event cards: the implied-move fallback then finds nothing.
NO_EVENT_CARDS = Path("/nonexistent-today-events")


def _run(inputs=None, ctx=None, events_dir=None):
    return today.build(ctx or _ctx(), inputs=inputs if inputs is not None else _inputs(),
                       events_dir=events_dir or NO_EVENT_CARDS)


def _keys(items):
    return [item["title"] for item in items]


# --- just out ----------------------------------------------------------------

def test_just_out_lists_macro_and_earnings_with_reaction_size():
    out = _run()
    assert out["just_out"]["session"] == AS_OF
    assert [m["title"] for m in out["just_out"]["macro"]] == [
        "Import & export prices: Import prices 1.2%", "Monthly options expiry settled this session"]
    assert out["just_out"]["macro"][1]["kind"] == "expiry"
    trv = out["just_out"]["earnings"][-1]
    assert trv["subject"] == "TRV" and trv["kind"] == "earnings"
    assert "beat expected EPS" in trv["title"]
    assert trv["z"] == pytest.approx(1.47 / 0.7, rel=1e-3)
    assert trv["value"] == pytest.approx(29.84)


def test_just_out_earnings_sorted_by_weight_and_after_close_named():
    out = _run()
    names = [e["subject"] for e in out["just_out"]["earnings"]]
    assert names == ["AFTER", "TRV"]  # 0.5 % weight before 0.12 %
    assert out["just_out"]["earnings"][0]["title"] == "AFTER reports after the close"


# --- coming up ---------------------------------------------------------------

def test_coming_up_has_one_block_per_session_with_the_listed_items(tmp_path):
    out = _run(events_dir=tmp_path)
    days = out["coming_up"]["days"]
    assert out["sessions"] == ["2026-10-19", "2026-10-20", "2026-10-21"]
    assert [d["date"] for d in days] == out["sessions"]
    day1, day2, day3 = (d["items"] for d in days)
    assert _keys(day1) == ["WATCH reports before the open"]  # SMALL is below the weight floor, not on the watchlist
    assert "Minor print" not in _keys(day1)
    cpi = day2[0]
    assert cpi["kind"] == "macro" and cpi["title"] == "CPI at 08:30"
    assert cpi["detail"] == "Expected: TradingView CPI 0.3%"
    assert _keys(day2).count("Quanta monthly revenue (2026-10)") == 1  # theme data, deduped by title
    theme = next(i for i in day2 if i["kind"] == "theme_data")
    assert theme["link"] == "#themes/SEMIS.DATA"
    assert {i["kind"] for i in day3} == {"expiry", "earnings"}
    expiry = next(i for i in day3 if i["kind"] == "expiry")
    assert expiry["detail"] == "Settles at the open." and expiry["importance"] == "low"
    meta = next(i for i in day3 if i["subject"] == "META")
    assert meta["value"] == pytest.approx(6.1) and meta["unit"] == "%"
    assert meta["extra"]["implied_expiry"] == "2026-11-06"


def test_coming_up_later_lists_high_importance_only_within_window(tmp_path):
    out = _run(events_dir=tmp_path)
    later = out["coming_up"]
    assert later["later_until"] == "2026-10-30"
    titles = _keys(later["later"])
    assert "FOMC decision (statement) at 14:00" in titles
    assert "LATEX reports after the close" in titles
    assert "Far away" not in titles and "Minor print" not in titles


def test_implied_move_falls_back_to_event_card(tmp_path):
    (tmp_path / "ALB.json").write_text(json.dumps({"card": {"priced": {"implied": {"straddle_pct": 11.83}}}}))
    inputs = _inputs()
    inputs["catalysts"]["events"].append({"lane": "single_name", "event_type": "earnings", "symbol": "ALB",
                                          "date": "2026-10-20", "timing": "bmo", "importance": "low",
                                          "index_weights": {"SPX": 0.01}, "watchlist": True})
    out = _run(inputs=inputs, events_dir=tmp_path)
    alb = next(i for i in out["coming_up"]["days"][1]["items"] if i["subject"] == "ALB")
    assert alb["value"] == pytest.approx(11.83)


def test_missing_implied_move_is_null(tmp_path):
    out = _run(events_dir=tmp_path)
    day1 = out["coming_up"]["days"][0]["items"]
    watch = next(i for i in day1 if i["subject"] == "WATCH")
    assert watch["value"] is None and watch["unit"] is None


# --- unusual: moves ----------------------------------------------------------

def test_unusual_moves_order_and_evidence(tmp_path):
    out = _run(events_dir=tmp_path)
    moves = out["unusual"]["moves"]
    assert [m["subject"] for m in moves] == ["NVDA", "AEE", "XOM"]  # high importance first, then the larger |z|
    nvda, aee, xom = moves
    assert nvda["importance"] == "high" and nvda["evidence"] == "tested"
    assert aee["evidence"] == "description"  # no direction, so no research row applies
    assert xom["evidence"] == "description"  # the up-shock row needs a report
    assert nvda["title"] == "NVDA fell 4.0%, 4.4 times its usual move"
    assert nvda["link"] == "#ticker/NVDA"
    assert all(m["new"] for m in moves)


def test_move_cap_applies_after_ordering(tmp_path):
    ctx = _ctx()
    ctx.config["today"]["max_moves"] = 2
    out = _run(ctx=ctx, events_dir=tmp_path)
    assert [m["subject"] for m in out["unusual"]["moves"]] == ["NVDA", "AEE"]


def test_sector_selloff_when_active_is_one_high_item(tmp_path):
    inputs = _inputs()
    inputs["moves"]["sector_selloff"] = {"active": True, "fund": "XLK", "z": -2.5, "spy_z": -0.4, "losers": ["A"]}
    out = _run(inputs=inputs, events_dir=tmp_path)
    moves = out["unusual"]["moves"]
    sector = next(m for m in moves if m["kind"] == "sector_selloff")
    assert sector["subject"] == "XLK" and sector["importance"] == "high" and sector["evidence"] == "tested"
    # Both are high importance, so the larger |z| (the name's 4.4 against the fund's 2.5) comes first.
    assert [m["subject"] for m in moves] == ["NVDA", "XLK", "AEE", "XOM"]


# --- unusual: states, risk, anchor, positioning ------------------------------

def test_started_state_and_ongoing_state(tmp_path):
    out = _run(events_dir=tmp_path)
    started = [i for i in out["unusual"]["states"] if i["kind"] == "market_state"]
    assert [i["title"] for i in started] == ["Small caps lag started this session"]
    ongoing = {i["subject"]: i for i in out["unusual"]["ongoing"] if i["kind"] == "market_state"}
    assert ongoing["NARROW LEADERSHIP"]["days"] == 4
    assert ongoing["NARROW LEADERSHIP"]["since"] == "2026-10-13"


def test_ended_state_needs_yesterdays_active_set(tmp_path, monkeypatch):
    previous = {"as_of": "2026-10-15", "history": [],
                "unusual": {"ongoing": [{"kind": "market_state", "subject": "STRESS",
                                         "extra": {"state": "stress", "active": True}}]}}
    monkeypatch.setattr(today, "_previous_payload", lambda base: (previous, None))
    out = _run(events_dir=tmp_path)
    ended = [i for i in out["unusual"]["states"] if i["kind"] == "market_state" and "ended" in i["title"]]
    assert [i["title"] for i in ended] == ["Stress ended this session"]
    assert not any(i.get("kind") == "market_state" and "ended" in i["title"] for i in out["unusual"]["ongoing"])


def test_no_previous_state_skips_ended_with_unavailable_note(tmp_path):
    out = _run(events_dir=tmp_path)
    assert any(item["part"] == "previous published TODAY" for item in out["unavailable"])
    assert not any("ended" in i["title"] for i in out["unusual"]["states"])


def test_risk_flip_into_and_out_of_and_ongoing(tmp_path):
    out = _run(events_dir=tmp_path)
    flips = {i["subject"]: i for i in out["unusual"]["states"] if i["kind"] == "risk"}
    assert flips["SKEW"]["title"] == "SKEW moved into its risk zone"
    assert flips["VX FRONT"]["title"] == "VX FRONT moved into its risk zone"
    assert flips["DROPPING"]["title"] == "DROPPING moved back out of its risk zone"
    assert all(i["evidence"] == "description" and i["new"] for i in flips.values())
    still = {i["subject"] for i in out["unusual"]["ongoing"] if i["kind"] == "risk"}
    assert still == {"CCC OAS", "CFTC ES"}  # the extreme tile cannot be flipped, so it stays ongoing


def test_put_call_extreme_only_when_newly_past_the_tail(tmp_path):
    out = _run(events_dir=tmp_path)
    put = [i for i in out["unusual"]["states"] if i["kind"] == "put_call"]
    assert len(put) == 1
    assert put[0]["title"] == "Options traders are buying unusually many puts"
    assert put[0]["value"] == pytest.approx(1.5) and put[0]["unit"] == "x"


def test_anchor_change_and_blackout_ongoing(tmp_path):
    out = _run(events_dir=tmp_path)
    anchor = [i for i in out["unusual"]["states"] if i["kind"] == "anchor"]
    assert anchor[0]["title"] == "Anchor exposure moved from 50% to 44%"
    blackout = next(i for i in out["unusual"]["ongoing"] if i["kind"] == "blackout")
    assert blackout["title"] == "Buyback blackout covers 76% of S&P 500 weight"
    assert blackout["detail"] == "Share changes by -2.6 pp over the next 7 days"


def test_anchor_below_full_without_change_is_ongoing(tmp_path):
    inputs = _inputs()
    inputs["anchor"] = _anchor([0.5, 0.5])
    out = _run(inputs=inputs, events_dir=tmp_path)
    assert not any(i["kind"] == "anchor" for i in out["unusual"]["states"])
    anchor = [i for i in out["unusual"]["ongoing"] if i["kind"] == "anchor"]
    assert anchor[0]["title"] == "Anchor exposure is 50% of a full position"


# --- unusual: events ---------------------------------------------------------

def test_events_entered_monitor_recent_catalyst_and_reaction(tmp_path):
    out = _run(events_dir=tmp_path)
    events = out["unusual"]["events"]
    kinds = {i["kind"] for i in events}
    assert kinds == {"monitor", "catalyst", "reaction"}
    monitor = [i for i in events if i["kind"] == "monitor"]
    assert len(monitor) == 1 and monitor[0]["extra"]["tickers"] == ["ABC"]
    assert monitor[0]["title"] == "MONITOR queue: 1 name entered: ABC" and monitor[0]["link"] == "#monitor"
    catalysts = [i for i in events if i["kind"] == "catalyst"]
    assert {c["title"] for c in catalysts} == {"Inside the window", "Today"}
    assert next(c for c in catalysts if c["title"] == "Today")["new"] is True
    assert next(c for c in catalysts if c["title"] == "Inside the window")["new"] is False
    reaction = next(i for i in events if i["kind"] == "reaction")
    assert reaction["subject"] == "TRV" and reaction["z"] == pytest.approx(1.47 / 0.7, rel=1e-3)


def test_reaction_below_threshold_not_listed(tmp_path):
    ctx = _ctx()
    ctx.config["today"]["reaction_sigma"] = 3.0
    out = _run(ctx=ctx, events_dir=tmp_path)
    assert not any(i["kind"] == "reaction" for i in out["unusual"]["events"])


# --- history, previous state, live -------------------------------------------

def test_history_starts_fresh_without_published_state(tmp_path):
    out = _run(events_dir=tmp_path)
    assert len(out["history"]) == 1 and out["history"][0]["as_of"] == AS_OF
    assert set(out["history"][0]["items"][0]) == {"key", "kind", "z", "new"}
    assert any("History starts fresh" in note for note in out["notes"])


def test_history_merges_newest_first_replaces_same_date_and_caps(tmp_path, monkeypatch):
    previous = {"as_of": "2026-10-15", "history": [
        {"as_of": AS_OF, "items": [{"key": "old-today", "kind": "move", "z": 1, "new": True, "extra": "drop"}]},
        {"as_of": "2026-10-15", "items": [{"key": "y", "kind": "move", "z": None, "new": False}]},
        {"as_of": "2026-10-14", "items": []},
    ], "unusual": {}}
    monkeypatch.setattr(today, "_previous_payload", lambda base: (previous, None))
    ctx = _ctx()
    ctx.config["today"]["history_days"] = 2
    out = _run(ctx=ctx, events_dir=tmp_path)
    assert [h["as_of"] for h in out["history"]] == [AS_OF, "2026-10-15"]
    assert all("old-today" != i["key"] for i in out["history"][0]["items"])
    assert all(set(i) == {"key", "kind", "z", "new"} for h in out["history"] for i in h["items"])


def test_previous_state_is_read_only_when_env_is_set(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"], seen["kwargs"] = url, kwargs
        return json.dumps({"as_of": "2026-10-15", "history": []})

    monkeypatch.setenv("TODAY_PUBLISHED_STATE", "1")
    monkeypatch.setattr(today, "get_text", fake_get)
    payload, reason = today._previous_payload("https://example.test/base")
    assert reason is None and payload["as_of"] == "2026-10-15"
    assert seen["url"] == "https://example.test/base/artifacts/today.json"
    assert seen["kwargs"]["timeout"] == today.PREVIOUS_STATE_TIMEOUT


def test_previous_state_failure_is_reported_not_raised(monkeypatch):
    def broken(url, **kwargs):
        raise OSError("network down")

    monkeypatch.setenv("TODAY_PUBLISHED_STATE", "1")
    monkeypatch.setattr(today, "get_text", broken)
    payload, reason = today._previous_payload("https://example.test")
    assert payload is None and "network down" in reason


def test_live_block_from_config(tmp_path):
    out = _run(events_dir=tmp_path)
    live = out["live"]
    assert live["threshold_sigma"] == 2.0 and live["market"] == "SPY"
    assert live["sector_funds"]["Information Technology"] == "XLK"
    assert live["max_items"] == 12


# --- failure paths -----------------------------------------------------------

def test_failed_inputs_become_unavailable_not_a_crash(tmp_path):
    inputs = _inputs()
    inputs["risk"] = None
    inputs["catalysts"] = None
    out = _run(inputs=inputs, events_dir=tmp_path)
    parts = {u["part"] for u in out["unavailable"]}
    assert {"risk", "catalysts"} <= parts
    assert out["coming_up"]["days"][0]["items"] == []
    assert out["just_out"]["earnings"] == []
    assert out["unusual"]["states"] == [i for i in out["unusual"]["states"] if i["kind"] != "risk"]


def test_empty_inputs_still_give_every_key(tmp_path):
    inputs = {name: None for name in today.INPUTS}
    out = _run(inputs=inputs, events_dir=tmp_path)
    assert set(validate.TODAY_KEYS) <= set(out)
    assert len(out["unavailable"]) >= len(today.INPUTS)
    assert out["unusual"] == {"moves": [], "states": [], "events": [], "ongoing": []}


# --- validate ----------------------------------------------------------------

def _valid_payload(tmp_path):
    return _run(events_dir=tmp_path)


def test_check_today_passes_for_a_built_payload(tmp_path):
    assert validate._check_today({"as_of": AS_OF}, _valid_payload(tmp_path)) == []


def test_check_today_flags_wrong_session_missing_keys_and_bare_items(tmp_path):
    payload = _valid_payload(tmp_path)
    payload["unusual"]["moves"][0].pop("link")
    del payload["live"]
    findings = validate._check_today({"as_of": "2026-10-15"}, payload)
    text = " | ".join(f.detail for f in findings)
    assert "is dated 2026-10-16, manifest says 2026-10-15" in text
    assert "missing live" in text
    assert "lack a key, kind, title or link" in text


def test_check_today_absent_is_not_an_error():
    assert validate._check_today({"as_of": AS_OF}, None) == []
