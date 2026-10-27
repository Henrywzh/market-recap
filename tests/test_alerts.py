"""ALERTS: tiers with hysteresis, announced on change against the previous session, and the e-mail digest."""

from __future__ import annotations

import json

from market_recap import alerts as A
from market_recap import alerts_email as M
from market_recap.config import load_config

VIX = {"id": "vix", "group": "VOLATILITY", "source": "tile", "key": "vix", "op": "above",
       "lines": [20.0, 25.0, 30.0], "reset": 1.5, "unit": "pts", "high_from_tier": 3}


def _arts(vix=None, strip_state="calm", rsi=None):
    tiles = [{"key": "vix", "label": "VIX", "value": vix}] if vix is not None else []
    rows = [{"symbol": "SOXX", "label": "Semiconductors (SOXX)", "group": "sector", "rsi6": rsi}] if rsi is not None else []
    return {
        "risk": {"sections": [{"tiles": tiles}],
                 "strip": [{"row": "strip", "column": "stock_bond", "channel": "CROSS-ASSET", "lead": "stock_bond_corr",
                            "label": "STOCK–BOND CORR 3M", "state": strip_state, "value": 0.27}],
                 "matrix": {"rows": [{"key": "credit", "label": "CREDIT"}],
                            "cells": [{"row": "credit", "column": "structure", "lead": "hyg_ief", "label": "HYG/IEF",
                                       "scale": "bands", "state": "calm"},
                                      {"row": "cross_asset", "column": "technical", "lead": "stock_bond_corr",
                                       "label": "STOCK–BOND CORR 3M", "scale": "bands", "state": strip_state}]}},
        "today": {"board": {"rows": rows}},
    }


def _run(rules, arts, base):
    events, ledger = A.evaluate(rules, arts, base)
    return events, {"as_of": "x", "entries": ledger}


def test_tiers_count_the_lines_passed_and_keep_a_tier_until_the_reset_margin():
    assert A.tier_of(19.9, [20, 25], "above") == 0
    assert A.tier_of(20.0, [20, 25], "above") == 1
    assert A.tier_of(26.0, [20, 25], "above") == 2
    # Back to 24 from tier 2: still within 1.5 of 25, so tier 2 holds; at 23.4 it eases to 1.
    assert A.tier_of(24.0, [20, 25], "above", previous=2, reset=1.5) == 2
    assert A.tier_of(23.4, [20, 25], "above", previous=2, reset=1.5) == 1
    # Below: an RSI under 30 and 20.
    assert A.tier_of(19.0, [30, 25, 20], "below") == 3
    assert A.tier_of(33.0, [30, 25, 20], "below", previous=1, reset=5.0) == 1
    assert A.tier_of(35.1, [30, 25, 20], "below", previous=1, reset=5.0) == 0
    assert A.tier_of(None, [20], "above", previous=1) == 1   # no reading: the tier stands


def test_a_crossing_is_new_once_then_quiet_and_cleared_when_it_falls_back():
    _, day0 = _run([VIX], _arts(vix=18.0), {"as_of": "d0", "entries": {}})
    events, day1 = _run([VIX], _arts(vix=21.0), day0)
    assert [(e["state"], e["line"], e["value"]) for e in events] == [("NEW", "≥ 20.0", "21.0")]
    # Still above 20 the next session: nothing to announce.
    events, day2 = _run([VIX], _arts(vix=22.5), day1)
    assert events == []
    # Up a tier: NEW again, at the deeper line; past the third line it is HIGH.
    events, day3 = _run([VIX], _arts(vix=31.0), day2)
    assert events[0]["state"] == "NEW" and events[0]["tier"] == 3 and events[0]["severity"] == "high"
    events, day4 = _run([VIX], _arts(vix=26.0), day3)
    assert events[0]["state"] == "EASED" and events[0]["severity"] == "normal"
    events, _ = _run([VIX], _arts(vix=17.0), day4)
    assert events[0]["state"] == "CLEARED" and events[0]["line"] == "≥ 25.0"


def test_the_first_build_lists_what_is_past_a_line_as_active_not_new():
    events, _ = _run([VIX], _arts(vix=26.0), None)
    assert [e["state"] for e in events] == ["ACTIVE"]
    assert _run([VIX], _arts(vix=12.0), None)[0] == []


def test_risk_states_and_rsi_per_symbol_and_the_matrix_skips_leads_on_the_strip():
    rules = [{"id": "risk_now", "group": "RISK NOW", "source": "risk_state", "from": "strip"},
             {"id": "risk_matrix", "group": "RISK MATRIX", "source": "risk_state", "from": "matrix"},
             {"id": "rsi6", "group": "TECHNICAL", "source": "rsi6", "op": "below", "lines": [30, 25, 20], "reset": 5, "unit": "pts"}]
    _, base = _run(rules, _arts(strip_state="calm", rsi=40), {"as_of": "d0", "entries": {}})
    events, _ = _run(rules, _arts(strip_state="elevated", rsi=19.5), base)
    labels = [(e["rule"], e["label"], e["value"], e["line"]) for e in events]
    assert ("risk_now", "CROSS-ASSET · STOCK–BOND CORR 3M", "elevated", "") in labels
    assert ("rsi6", "Semiconductors (SOXX)", "19.5", "≤ 20.0") in labels
    # The same lead in the matrix is not announced twice.
    assert not any(e["rule"] == "risk_matrix" for e in events)


def test_openrouter_month_so_far_against_last_month():
    dates = [f"2026-09-{d:02d}" for d in range(1, 31)] + [f"2026-10-{d:02d}" for d in range(1, 23)]
    values = [100.0] * 30 + [175.0] * 22
    assert round(A.openrouter_change(dates, values), 1) == 75.0
    assert A.openrouter_change(dates[:33], values[:33]) is None   # three days of October: too few
    assert A.openrouter_change(dates, [0.0] * 30 + [1.0] * 22) is None


def test_a_rerun_of_the_session_does_not_send_the_same_digest_twice(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"as_of": "2026-10-27", "edition": "evening"}))
    (tmp_path / "risk.json").write_text(json.dumps(_arts(vix=26.0)["risk"]))
    previous_session = {"schema": A.SCHEMA, "as_of": "2026-10-26",
                        "ledger": {"as_of": "2026-10-26", "entries": {"vix:vix": {"tier": 0, "value": 18.0}}}}
    first = A.build(root=tmp_path, fetch=lambda url: json.dumps(previous_session))
    assert first["email"]["due"] and first["compared_with"] == "2026-10-26"
    assert [e["key"] for e in first["events"] if e["rule"] == "vix"] == ["vix:vix"]
    # The published file is now this session's: a rerun finds the same changes and is not due.
    rerun = A.build(root=tmp_path, fetch=lambda url: json.dumps(first))
    assert rerun["compared_with"] == "2026-10-26" and rerun["email"]["due"] is False


def test_a_first_session_rerun_with_fewer_active_alerts_sends_nothing_but_a_new_one_does(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"as_of": "2026-10-27"}))
    (tmp_path / "agent-index.json").write_text("{}")
    (tmp_path / "risk.json").write_text(json.dumps(_arts(vix=26.0, strip_state="elevated")["risk"]))
    first = A.build(root=tmp_path, fetch=lambda url: "<html>")   # nothing published yet
    assert first["compared_with"] is None and first["email"]["due"] and len(first["events"]) == 2
    # Rerun: VIX back under 20, so one fewer ACTIVE: nothing new, nothing sent.
    (tmp_path / "risk.json").write_text(json.dumps(_arts(vix=15.0, strip_state="elevated")["risk"]))
    fewer = A.build(root=tmp_path, fetch=lambda url: json.dumps(first))
    assert len(fewer["events"]) == 1 and fewer["email"]["due"] is False
    # Rerun with a reading past a line the published build did not have: that one is sent.
    (tmp_path / "risk.json").write_text(json.dumps(_arts(vix=31.0, strip_state="elevated")["risk"]))
    more = A.build(root=tmp_path, fetch=lambda url: json.dumps(first))
    assert more["email"]["due"] and more["email"]["fresh"] == ["vix:vix"]
    subject, text, _ = M.compose(more)
    assert "VIX" in text and "STOCK–BOND" not in text and "1 active" in subject


def test_the_digest_puts_high_first_and_sends_nothing_without_smtp_settings(tmp_path, monkeypatch):
    payload = {"as_of": "2026-10-27", "site": "https://example.test", "compared_with": "2026-10-26",
               "email": {"due": True, "subject": "Market Recap alerts · 2026-10-27 · 2 new"},
               "events": [{"key": "a", "group": "VOLATILITY", "state": "NEW", "severity": "normal", "label": "VIX",
                           "value": "21.0", "line": "≥ 20.0", "link": "#risk"},
                          {"key": "b", "group": "WATCH", "state": "NEW", "severity": "high", "label": "Oil shock",
                           "value": "1", "line": "", "link": "#watch"}]}
    subject, text, html = M.compose(payload)
    assert subject == "Market Recap alerts · 2026-10-27 · 2 new"
    assert text.index("HIGH") < text.index("NEW") and "Oil shock" in text.split("NEW")[0]
    assert "VIX: 21.0 (≥ 20.0)  https://example.test/#risk" in text and "<table" in html
    (tmp_path / "alerts.json").write_text(json.dumps(payload))
    for key in ("ALERT_SMTP_USER", "ALERT_SMTP_PASSWORD", "ALERT_EMAIL_TO"):
        monkeypatch.delenv(key, raising=False)
    assert M.send(root=tmp_path)["sent"] is False
    assert M.send(root=tmp_path, dry_run=True)["subject"] == subject
    payload["email"]["due"] = False
    (tmp_path / "alerts.json").write_text(json.dumps(payload))
    assert "nothing new" in M.send(root=tmp_path)["why"]


def test_every_configured_rule_names_a_known_source_with_lines_in_order():
    rules = load_config()["alerts"]["rules"]
    assert len({r["id"] for r in rules}) == len(rules)
    known = {"tile", "strip", "risk_state", "rsi6", "cross_asset", "rate", "blackout", "openrouter_mom", "watch", "health"}
    for rule in rules:
        assert rule["source"] in known, rule["id"]
        lines = rule.get("lines")
        if lines:
            # Lines run in the rule's direction, so tier n is the n-th line passed.
            assert lines == (sorted(lines, reverse=True) if rule.get("op") == "below" else sorted(lines)), rule["id"]
