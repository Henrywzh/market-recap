"""TODAY: each list cut from small fixtures, the history merge and cap, and the failure paths."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
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


def _cell(row, column, label, state, state_prev, percentile, value=None, unit=None):
    """A matrix cell with a lead; the fields TODAY reads, the rest as the panel writes them."""
    return {"row": row, "column": column, "lead": label.lower(), "label": label, "value": value, "unit": unit,
            "date": AS_OF, "risk_when": "high", "percentile": percentile, "state": state, "state_prev": state_prev,
            "change_1m": None, "worse_1m": None, "evidence": "description", "caution": None, "note": None,
            "pending": None, "members": []}


def _placeholder(row, column):
    return {"row": row, "column": column, "lead": None, "label": None, "value": None, "unit": None, "date": None,
            "risk_when": None, "percentile": None, "state": "grey", "state_prev": None, "change_1m": None,
            "worse_1m": None, "evidence": "description", "caution": None, "note": None, "pending": "—", "members": []}


def _risk():
    """A matrix with a change into elevated, a change back to calm, two stressed cells, a grey cell
    that was stressed (no reading now, so no change) and a placeholder."""
    return {"sections": [{"key": "volatility", "label": "VOLATILITY",
                          "tiles": [{"key": "vix", "value": 19.03, "change_1d": 2.35, "date": AS_OF}]}],
            "matrix": {
        "rows": [{"key": "credit", "label": "CREDIT"}, {"key": "equities", "label": "EQUITIES"},
                 {"key": "macro", "label": "MACRO"}],
        "columns": [{"key": "structure", "label": "STRUCTURE"}, {"key": "technical", "label": "TECHNICAL"},
                    {"key": "fundamental", "label": "FUNDAMENTAL / PREMIUM"}],
        "cells": [
            _cell("credit", "fundamental", "HY OAS", "elevated", "calm", 88.0, value=520, unit="bp"),
            _cell("credit", "technical", "HY OAS 20D CHANGE", "calm", "elevated", 40.0, value=-5, unit="bp"),
            _cell("equities", "structure", "VIX / VIX3M", "stressed", "stressed", 97.0, value=1.02, unit="ratio"),
            _cell("equities", "technical", "SPX FROM 1Y HIGH", "grey", "stressed", None, value=-12.0, unit="pct"),
            _cell("macro", "structure", "NET LIQUIDITY", "stressed", None, 96.0, value=-400, unit="usd_bn"),
            _placeholder("equities", "fundamental"),
        ]}}


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


def test_matrix_state_changes_are_listed_once_each_way(tmp_path):
    out = _run(events_dir=tmp_path)
    changed = {i["subject"]: i for i in out["unusual"]["states"] if i["kind"] == "risk"}
    assert changed["HY OAS"]["title"] == "Credit · fundamental: HY OAS moved to elevated (88th pct of 10y)"
    assert changed["HY OAS 20D CHANGE"]["title"] == \
        "Credit · technical: HY OAS 20D CHANGE moved back to calm (40th pct of 10y)"
    assert all(i["new"] and i["link"] == "#risk" and i["evidence"] == "description" for i in changed.values())
    assert changed["HY OAS"]["extra"]["state_prev"] == "calm"
    # A cell with no reading today is not a change, and the placeholder is nothing.
    assert "SPX FROM 1Y HIGH" not in changed and set(changed) == {"HY OAS", "HY OAS 20D CHANGE"}


def test_stressed_cells_that_did_not_change_are_ongoing(tmp_path):
    out = _run(events_dir=tmp_path)
    ongoing = {i["subject"]: i for i in out["unusual"]["ongoing"] if i["kind"] == "risk"}
    assert set(ongoing) == {"VIX / VIX3M", "NET LIQUIDITY"}  # the second has no earlier reading, so it is ongoing too
    assert ongoing["VIX / VIX3M"]["title"] == "Equities · structure: VIX / VIX3M is stressed (97th pct of 10y)"
    assert ongoing["VIX / VIX3M"]["new"] is False


def test_ordinal_writes_the_percentile_as_the_page_does(tmp_path):
    assert [today._ordinal(v) for v in (1, 2, 3, 4, 11, 12, 13, 21, 22, 102)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "102nd"]


def test_put_call_extreme_only_when_newly_past_the_tail(tmp_path):
    out = _run(events_dir=tmp_path)
    put = [i for i in out["unusual"]["states"] if i["kind"] == "put_call"]
    assert len(put) == 1
    assert put[0]["title"] == "Options traders are buying unusually many puts"
    assert put[0]["value"] == pytest.approx(1.5) and put[0]["unit"] == "x"


def test_blackout_is_ongoing(tmp_path):
    out = _run(events_dir=tmp_path)
    blackout = next(i for i in out["unusual"]["ongoing"] if i["kind"] == "blackout")
    assert blackout["title"] == "Buyback blackout covers 76% of S&P 500 weight"
    assert blackout["detail"] == "Share changes by -2.6 pp over the next 7 days"
    assert not any(i["kind"] == "anchor" for i in out["unusual"]["states"] + out["unusual"]["ongoing"])


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
    assert out["unusual"] == {"moves": [], "states": [], "events": [], "ongoing": [], "oversold": [], "watch": [], "tails": []}


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


def test_a_banded_cell_names_the_line_it_crossed():
    cell = {"row": "volatility", "column": "technical", "lead": "vix", "label": "VIX", "value": 36.2, "unit": "pts",
            "state": "stressed", "state_prev": "elevated", "percentile": 99.1, "scale": "bands",
            "bands": {"elevated": 25.0, "stressed": 35.0}, "evidence": "description"}
    matrix = {"rows": [{"key": "volatility", "label": "VOLATILITY"}], "cells": [cell]}
    (item,), ongoing = today._matrix_items(matrix, "2026-10-16")
    assert item["title"] == "Volatility · technical: VIX moved to stressed (stressed from 35)"
    assert ongoing == []
    back = {**cell, "state": "calm", "state_prev": "elevated", "value": 22.0, "unit": "bp",
            "bands": {"elevated": 25.0, "stressed": 35.0}}
    (item,), _ = today._matrix_items({**matrix, "cells": [back]}, "2026-10-16")
    assert item["title"].endswith("moved back to calm (elevated from 25bp)")


def test_a_valuation_cell_says_how_thin_its_premium_is():
    cell = {"row": "equities", "column": "valuation", "lead": "ecy", "label": "EXCESS CAPE YIELD", "value": 0.56,
            "unit": "pct", "state": "very_rich", "state_prev": "rich", "percentile": 94.5, "scale": "valuation",
            "since": "1960-01-01", "evidence": "description"}
    matrix = {"rows": [{"key": "equities", "label": "EQUITIES"}], "cells": [cell]}
    (item,), ongoing = today._matrix_items(matrix, "2026-10-16")
    assert item["title"] == ("Equities · valuation: EXCESS CAPE YIELD moved to very rich "
                             "(premium thinner than 94% of the time since 1960)")
    assert item["detail"].endswith("rich before")
    assert ongoing == [], "a rich market is not an ongoing stress"


def _closes(values):
    import pandas as pd
    return pd.Series(values, index=pd.bdate_range("2026-09-01", periods=len(values)), dtype=float)


def test_oversold_lists_watch_names_below_a_line_deepest_first(tmp_path):
    import pandas as pd
    ctx = _ctx()
    steady = [100 + (i % 2) for i in range(30)]
    falling = steady + [99, 97, 95, 93, 91, 89]             # RSI(6) 11: 3rd close below 20, 5th below 30
    crossing = steady + [101, 100, 101, 100, 99.5, 97.8]    # RSI(6) 28.5: first close below 30
    ctx.index_closes = pd.DataFrame({"^GSPC": _closes(falling)})
    ctx.etf_closes = pd.DataFrame({"XLK": _closes(crossing), "XLU": _closes(steady + [101] * 6),
                                   "AAPL": _closes(falling)})
    out = _run(ctx=ctx, events_dir=tmp_path)["unusual"]["oversold"]
    assert [i["extra"]["symbol"] for i in out] == ["^GSPC", "XLK"]   # deepest first; AAPL is not watched
    deep, fresh = out
    assert (deep["extra"]["line"], deep["days"], deep["extra"]["days_below_30"], deep["new"]) == (20, 3, 5, False)
    assert deep["title"] == "S&P 500 deeply oversold: third close in a row below 20 on RSI(6) (5 below 30)"
    assert deep["link"] == "#technicals/^GSPC"
    assert (fresh["extra"]["line"], fresh["days"], fresh["new"]) == (30, 1, True)
    assert "first close below 30" in fresh["title"]


def test_oversold_is_empty_without_closes(tmp_path):
    assert _run(events_dir=tmp_path)["unusual"]["oversold"] == []


def test_a_watch_name_in_the_outer_tail_of_its_own_history_is_listed_once():
    idx = pd.bdate_range("2016-01-01", periods=1300)
    rng = np.random.default_rng(7)
    calm = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.005, len(idx))), index=idx)
    crash = calm.copy()
    crash.iloc[-1] = crash.iloc[-2] * 0.97
    closes = pd.DataFrame({"QQQ": crash, "XLU": calm})
    items = today._tail_items(closes, {"QQQ": "Nasdaq-100 (QQQ)", "XLU": "Utilities (XLU)"}, idx[-1].strftime("%Y-%m-%d"))
    assert [i["subject"] for i in items] == ["Nasdaq-100 (QQQ)"]
    item = items[0]
    assert item["kind"] == "tail" and item["link"] == "#movecheck/QQQ" and item["extra"]["horizon"] == 1
    assert item["title"].startswith("Nasdaq-100 (QQQ) fell 3.0% today: never further since 2016")
    assert item["importance"] == "high"


# --- board, headline, move flags ---------------------------------------------

def _walk(periods, seed=3):
    """A daily close path ending on the session, with 1% daily noise."""
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, periods)),
                     index=pd.bdate_range(end=AS_OF, periods=periods))


def _board_ctx(frames):
    """A context whose watch list is the given {symbol: (label, closes)}, closes read from etf_closes."""
    ctx = _ctx()
    ctx.config["today"]["oversold_watch"] = {symbol: label for symbol, (label, _) in frames.items()}
    ctx.etf_closes = pd.DataFrame({symbol: close for symbol, (_, close) in frames.items()})
    return ctx


def test_board_row_maths_share_rsi_and_stale_names_skipped(tmp_path):
    walk = _walk(300)
    crash = walk.copy()
    crash.iloc[-1] = crash.iloc[-2] * 0.9  # -10% on the session, further than any past day in this walk
    falling = pd.Series(100 * 0.98 ** np.arange(40), index=pd.bdate_range(end=AS_OF, periods=40))
    ctx = _board_ctx({"^NDX": ("Nasdaq-100", crash), "XLE": ("Energy (XLE)", falling),
                      "XLU": ("Utilities (XLU)", _walk(300, seed=5).iloc[:-1])})  # XLU's last close is a session old
    rows = _run(ctx=ctx, events_dir=tmp_path)["board"]["rows"]
    assert [r["symbol"] for r in rows] == ["^NDX", "XLE"]  # config order; XLU skipped
    ndx, xle = rows
    assert ndx["group"] == "index" and ndx["short"] == "Nasdaq-100" and ndx["ret_pct"] == -10.0
    rets = crash.pct_change().dropna() * 100
    assert ndx["z"] == pytest.approx(round(rets.iloc[-1] / rets.iloc[-61:-1].std(), 2))
    assert ndx["share_pct"] == 0.0  # no past day fell this far
    assert 0 <= ndx["rsi6"] <= 100
    assert xle["group"] == "sector" and xle["short"] == "Energy" and xle["ret_pct"] == -2.0
    assert xle["z"] is None and xle["share_pct"] is None  # too little history for either
    assert xle["rsi6"] == 0.0  # forty closes all lower: RSI(6) at its floor


def _row(symbol, label, group, ret, share=None):
    return {"symbol": symbol, "label": label, "short": today.SHORT_LABEL.get(symbol, label), "group": group,
            "ret_pct": ret, "z": None, "share_pct": share, "rsi6": None}


def _day_board(vix=None, sectors=None, spx=-1.2, rsp=0.7):
    rows = [_row("^GSPC", "S&P 500", "index", spx), _row("^NDX", "Nasdaq-100", "index", -2.9)]
    if rsp is not None:
        rows.append(_row("RSP", "S&P 500 equal weight (RSP)", "index", rsp))
    rows += sectors if sectors is not None else [
        _row("SOXX", "Semiconductors (SOXX)", "sector", -6.79, share=0.5),
        _row("XLK", "Technology (XLK)", "sector", -3.3, share=12.0),
        _row("XLP", "Consumer staples (XLP)", "sector", 3.3),
        _row("XLU", "Utilities (XLU)", "sector", 2.1),
        _row("XLE", "Energy (XLE)", "sector", -0.2),
    ]
    return {"as_of": AS_OF, "rows": rows, "vix": {"value": 19.03, "change": 2.35} if vix is None else vix}


def test_headline_names_the_market_and_the_sectors_that_made_the_day():
    out = today.headline(_day_board())
    # 2026-10-22: the index fell, the average stock rose; semis and tech drove it; staples and utilities rose.
    assert out["title"] == ("Mega-cap selloff while the average stock rose, led by Semis −6.8% (rare) and Tech −3.3%; "
                            "Staples +3.3% and Utilities +2.1% rose")
    assert out["text"] == ("S&P 500 −1.2%, Nasdaq-100 −2.9%, Equal weight +0.7%. "
                           "Rare: Semis fell this far on 0.5% of days. VIX 19.0 (+2.4).")
    assert out["tone"] == "down"


def test_headline_title_on_a_plain_selloff_a_flat_day_and_a_narrow_rally():
    xle = _row("XLE", "Energy (XLE)", "sector", 0.4)
    assert today.headline(_day_board(spx=-1.2, rsp=-1.4, sectors=[xle]))["title"] == "Selloff"
    flat = [_row("XLE", "Energy (XLE)", "sector", 1.6), _row("XLK", "Technology (XLK)", "sector", -1.1)]
    assert today.headline(_day_board(spx=0.1, rsp=None, sectors=flat))["title"] == "Flat day; up: Energy +1.6%; down: Tech −1.1%"
    rally = [_row("XLK", "Technology (XLK)", "sector", 3.0), _row("XLU", "Utilities (XLU)", "sector", -1.2)]
    assert today.headline(_day_board(spx=1.5, rsp=0.2, sectors=rally))["title"] == (
        "Narrow rally in the largest names, led by Tech +3.0%; Utilities −1.2% fell")


def test_headline_drops_a_missing_vix_and_the_rare_part_when_nothing_is_rare():
    no_vix = today.headline(_day_board(vix={"value": None, "change": None}))
    assert no_vix["text"].endswith("Rare: Semis fell this far on 0.5% of days.")
    common = [_row("XLK", "Technology (XLK)", "sector", -3.3, share=12.0), _row("XLE", "Energy (XLE)", "sector", -0.2)]
    text = today.headline(_day_board(vix={"value": 19.03, "change": None}, sectors=common))["text"]
    assert "Rare" not in text and text.endswith("VIX 19.0.")


def test_headline_tone_is_flat_inside_three_tenths_and_none_under_three_rows():
    assert today.headline(_day_board(spx=-0.2))["tone"] == "flat"
    assert today.headline(_day_board(spx=0.5))["tone"] == "up"
    assert today.headline({"rows": _day_board()["rows"][:2]}) is None


def test_move_items_carry_earnings_flag_and_sparkline(tmp_path):
    ctx = _ctx()
    ctx.closes = pd.DataFrame({"NVDA": _walk(40)})
    inputs = _inputs()
    inputs["moves"]["unusual"] = ["NVDA", "XOM", "TRV"]
    inputs["catalysts"]["recent"]["earnings_reacted"].append(
        {"symbol": "XOM", "date": AS_OF, "eps": 1.0, "eps_forecast": 0.9, "surprise_pct": 11.1, "return_1d": 2.4,
         "index_weights": {"SPX": 0.3}})
    moves = {m["subject"]: m for m in _run(ctx=ctx, inputs=inputs, events_dir=tmp_path)["unusual"]["moves"]}
    assert moves["XOM"]["extra"]["earnings"] is True  # an earnings reaction this session
    assert moves["TRV"]["extra"]["earnings"] is True  # reported, per the moves row
    assert moves["NVDA"]["extra"]["earnings"] is False
    spark = moves["NVDA"]["extra"]["spark"]
    assert len(spark) == 20 and spark[-1] == float(f"{ctx.closes['NVDA'].iloc[-1]:.4g}")
    assert moves["XOM"]["extra"]["spark"] == []  # no frame holds XOM


def test_reaction_for_a_listed_move_is_dropped_from_events(tmp_path):
    inputs = _inputs()
    inputs["catalysts"]["recent"]["earnings_reacted"].append(
        {"symbol": "XOM", "date": AS_OF, "eps": 1.0, "eps_forecast": 0.9, "surprise_pct": 11.1, "return_1d": 2.4,
         "index_weights": {"SPX": 0.3}})
    out = _run(inputs=inputs, events_dir=tmp_path)
    reactions = [i["subject"] for i in out["unusual"]["events"] if i["kind"] == "reaction"]
    assert reactions == ["TRV"]  # XOM is already a move row, so no second row for it
    assert not any(i["subject"] == "XOM" for i in out["unusual"]["events"])


def test_payload_is_strict_json_with_board_and_headline(tmp_path):
    ctx = _board_ctx({"^GSPC": ("S&P 500", _walk(300)), "XLK": ("Technology (XLK)", _walk(300, seed=8)),
                      "XLP": ("Consumer staples (XLP)", _walk(300, seed=9))})
    out = _run(ctx=ctx, events_dir=tmp_path)
    json.dumps(out, allow_nan=False)
    assert out["board"]["vix"] == {"value": 19.03, "change": 2.35}
    assert [r["symbol"] for r in out["board"]["rows"]] == ["^GSPC", "XLK", "XLP"]
    assert out["headline"]["text"].startswith("S&P 500 ") and out["headline"]["tone"] in ("up", "down", "flat")
    empty = _run(events_dir=tmp_path)
    assert empty["board"]["rows"] == [] and empty["headline"] is None
    json.dumps(empty, allow_nan=False)


def test_sparkline_and_board_round_to_four_significant_digits():
    assert today._round(1.23456, 2) == 1.23 and today._round(float("nan"), 2) is None
    close = pd.Series([123.456789, 124.0], index=pd.bdate_range(end=AS_OF, periods=2))
    assert today._spark(SimpleNamespace(closes=pd.DataFrame({"AB": close})), "AB", AS_OF) == [123.5, 124.0]


def test_board_vix_is_left_out_when_the_tile_is_from_another_session():
    risk = {"sections": [{"tiles": [{"key": "vix", "value": 16.7, "change_1d": -0.6, "date": "2026-10-21"}]}]}
    assert today._vix(risk, "2026-10-22") == {"value": None, "change": None}
    assert today._vix(risk, "2026-10-21") == {"value": 16.7, "change": -0.6}
