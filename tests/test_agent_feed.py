"""Agent feed: condensed from the artifacts, states tracked, never stale."""

from __future__ import annotations

import json

from market_recap import agent_feed as A
from market_recap.sources.http import FetchError

SITE = "https://example.test"


def _artifacts(root, *, as_of="2026-10-09", breaches=("ccc_oas",), reading="rates", sector_event=True,
               risk=True):
    def write(name, payload):
        (root / f"{name}.json").write_text(json.dumps(payload))

    write("manifest", {"as_of": as_of, "edition": "evening", "generated_at": f"{as_of}T22:40:00Z",
                       "sources": [{"source_id": "nasdaq", "label": "Nasdaq", "observed_date": as_of,
                                    "policy": "daily_close", "freshness": "current", "status": "partial",
                                    "error": "results not posted yet: DAL (2026-10-09)"}]})
    write("overview", {
        "stocks": [{"key": "SPX", "label": "S&P 500", "last": 7811.54, "date": as_of, "1D": 0.59, "1M": 2.9,
                    "YTD": 14.1, "from_high_pct": -0.09}],
        "sectors": [{"sector": "Financials", "etf": "XLF", "weight_pct": 11.5, "1D": 0.9, "1M": -3.4}],
        "vol": {"date": as_of, "move": 98.47, "move_pct_1y": 94, "vix": 15.41, "vix_pct_1y": 17, "reading": reading},
        "fed": {"year_end": {"date": "2026-12-09", "cumulative_bp": 24.9}},
        "ahead": [{"kind": "macro", "date": "2026-10-14", "title": "CPI",
                   "market": {"source": "kalshi", "label": "CPI y/y", "value": 3.59, "unit": "%"}}],
        "rates": [], "cross_asset": [], "breadth": [], "prints": [],
    })
    if risk:
        write("risk", {"sections": [{"tiles": [{"key": k, "core": True, "breach": True} for k in breaches]}],
                       "breaches": [{"key": k, "label": k.upper(), "section": "credit", "horizon": "tactical",
                                     "value": 1.0, "unit": "bp", "crossed": None} for k in breaches],
                       "crossed": [], "sentiment": {"score": 38.7, "rating": "FEAR"},
                       "matrix": {"rows": [{"key": "credit", "label": "CREDIT"}], "columns": [], "cells": [
                           {"row": "credit", "column": "fundamental", "lead": "hy_oas", "label": "HY OAS",
                            "value": 520.0, "unit": "bp", "percentile": 88.0, "state": "elevated",
                            "state_prev": "calm", "evidence": "description", "caution": None,
                            "change_1m": 30.0, "worse_1m": True, "members": ["hy_oas"]},
                           {"row": "credit", "column": "technical", "lead": None, "label": None, "value": None,
                            "unit": None, "percentile": None, "state": "grey", "state_prev": None,
                            "evidence": "description", "caution": None, "pending": "—", "members": []}]}})
    write("monitor", {
        "note": "rule", "settings": {}, "previous_as_of": "2026-10-08",
        "sectors": [{"sector": "Financials", "event": sector_event, "median_excess_pct": -2.0}],
        "rows": [{"ticker": "HPQ", "name": "HP", "sector": "Tech", "candidate": True, "membership": "index",
                  "price_state": "weak", "evidence_state": "steady"},
                 {"ticker": "BE", "sector": "Industrials", "candidate": False, "membership": "index"}],
        "changes": [{"ticker": "HPQ", "sector": "Tech", "kind": "entered", "text": "Entered the queue"},
                    {"ticker": "BE", "sector": "Industrials", "kind": "left", "text": "Left the queue"}],
    })
    write("catalysts", {
        "events": [{"lane": "macro", "date": "2026-10-14", "time": "08:30", "title": "CPI", "importance": "high"},
                   {"lane": "single_name", "date": "2026-10-13", "timing": "bmo", "symbol": "JPM", "title": "JPM earnings",
                    "importance": "high", "index_weights": {"SPX": 1.3}},
                   {"lane": "single_name", "date": "2026-11-01", "symbol": "AAPL", "title": "AAPL earnings",
                    "importance": "high", "index_weights": {"SPX": 6.0}}],
        "recent": {"session": as_of, "macro": [], "earnings_after_close": [],
                   "earnings_reacted": [{"symbol": "DAL", "importance": "medium", "eps": None, "eps_forecast": 1.8,
                                         "surprise_pct": None, "return_1d": 0.04, "result_pending": True,
                                         "index_weights": {"SPX": 0.07}}]},
    })


def _build(tmp_path, previous=None, **kw):
    _artifacts(tmp_path, **kw)
    fetch = (lambda url: json.dumps(previous)) if previous is not None else _missing
    return A.build(root=tmp_path, fetch=fetch, site=SITE)


def _missing(url):
    raise FetchError("404", not_found=True)


def _states(brief):
    return {c["id"]: c["state"] for c in brief["research_candidates"]}


def test_the_feed_condenses_without_recomputing_and_labels_the_overlay(tmp_path):
    index, brief = _build(tmp_path)
    assert index["market_state"]["indices"][0]["last"] == 7811.54
    # The systematic anchor has left RISK and the feed; its artifact is still built, but nothing reads it.
    assert "systematic_anchor" not in brief["risk_budget"] and "systematic_anchor" not in index["market_state"]
    # The matrix is listed cell by cell; a placeholder keeps its place with no lead.
    cells = brief["risk_budget"]["risk_matrix"]
    assert [(c["row"], c["column"], c["label"], c["state"]) for c in cells] == [
        ("credit", "fundamental", "HY OAS", "elevated"), ("credit", "technical", None, "grey")]
    assert cells[0]["percentile"] == 88.0 and cells[0]["evidence"] == "description"
    assert index["next_7_days"][0]["what"] == "JPM earnings"
    # CPI carries what the market prices for it.
    assert [e for e in index["next_7_days"] if e["what"] == "CPI"][0]["market_implied"]["value"] == 3.59
    # 30-day calendar: one line each, past the detailed week.
    assert brief["timing"]["calendar_high_importance"] == [
        {"date": "2026-11-01", "lane": "single_name", "title": "AAPL", "spx_weight_pct": 6.0}]
    # An exit is kept, in one line; the entry gets a full card.
    assert [n["ticker"] for n in brief["names"]["changed_this_session"]] == ["HPQ"]
    assert [n["ticker"] for n in brief["names"]["left_the_queue"]] == ["BE"]
    # A result not posted yet is a candidate that says so, and a data-quality alert.
    review = [c for c in brief["research_candidates"] if c["rule_id"] == "review.earnings"][0]
    assert review["trigger"].startswith("result not posted yet")
    assert any("results not posted yet: DAL" in a for a in index["data_quality_alerts"])
    for c in brief["research_candidates"]:
        assert c["question"] == A.RULES[c["rule_id"]]["question"]
    assert {c["id"] for c in index["candidates"]["top"]} <= {c["id"] for c in brief["research_candidates"]}


def test_conditions_are_new_then_continuing_then_resolved_on_valid_data(tmp_path):
    _, first = _build(tmp_path)
    assert _states(first)["risk.breach:ccc_oas"] == "new"
    assert _states(first)["monitor.entered:HPQ:2026-10-09"] == "new"
    assert _states(first)["catalyst.earnings:JPM:2026-10-13"] == "scheduled"

    _, second = _build(tmp_path, previous=first, as_of="2026-10-12")
    assert _states(second)["risk.breach:ccc_oas"] == "continuing"
    ccc = [c for c in second["research_candidates"] if c["id"] == "risk.breach:ccc_oas"][0]
    assert ccc["first_seen"] == "2026-10-09" and ccc["last_confirmed"] == "2026-10-12"

    _, third = _build(tmp_path, previous=second, as_of="2026-10-13", breaches=(), reading="in_line",
                      sector_event=False)
    states = _states(third)
    assert states["risk.breach:ccc_oas"] == "resolved"
    assert states["vol.divergence:rates"] == "resolved"
    assert states["sector.event:XLF"] == "resolved"
    # Events and passed catalysts are not carried forward.
    assert "monitor.entered:HPQ:2026-10-09" not in states


def test_a_condition_without_a_valid_reading_is_unknown_not_resolved(tmp_path):
    _, first = _build(tmp_path)
    (tmp_path / "risk.json").unlink()
    _, second = _build(tmp_path, previous=first, as_of="2026-10-12", risk=False)
    assert _states(second)["risk.breach:ccc_oas"] == "unknown"
    assert "risk" not in second["data_quality"]["sections_unavailable"]  # the section is just thinner
    _, third = _build(tmp_path, previous=second, as_of="2026-10-13")
    # Back with data and still in breach: it never ended.
    assert _states(third)["risk.breach:ccc_oas"] == "continuing"


def test_a_rerun_of_a_session_compares_with_the_session_before(tmp_path):
    _, first = _build(tmp_path)
    _, second = _build(tmp_path, previous=first, as_of="2026-10-12")
    _, rerun = _build(tmp_path, previous=second, as_of="2026-10-12")
    assert rerun["compared_with"] == "2026-10-09"
    assert _states(rerun)["risk.breach:ccc_oas"] == "continuing"


def test_an_unreadable_previous_feed_makes_states_unknown(tmp_path):
    _artifacts(tmp_path)

    def broken(url):
        raise FetchError("timed out")
    index, brief = A.build(root=tmp_path, fetch=broken, site=SITE)
    assert _states(brief)["risk.breach:ccc_oas"] == "unknown"
    assert any("candidate states unknown" in a for a in index["data_quality_alerts"])
    # The site's page where no feed exists yet is "no previous feed", not an error.
    _, fresh = A.build(root=tmp_path, fetch=lambda url: "<!doctype html>", site=SITE)
    assert _states(fresh)["risk.breach:ccc_oas"] == "new"


def test_a_missing_artifact_is_named_and_a_failed_build_leaves_no_feed(tmp_path):
    _artifacts(tmp_path)
    (tmp_path / "catalysts.json").unlink()
    result = A.write(root=tmp_path, fetch=_missing)
    assert result["written"] and "timing" in result["sections_unavailable"]
    assert (tmp_path / A.INDEX_FILE).exists() and (tmp_path / A.BRIEF_FILE).exists()
    assert json.loads((tmp_path / A.INDEX_FILE).read_text())["as_of"] == "2026-10-09"
    # A build that fails removes the previous files rather than leaving them
    # to be published as this build's.
    (tmp_path / "manifest.json").unlink()
    failed = A.write(root=tmp_path, fetch=_missing)
    assert not failed["written"]
    assert not (tmp_path / A.INDEX_FILE).exists() and not (tmp_path / A.BRIEF_FILE).exists()


def _busy_brief(candidates=1):
    cards = [{"ticker": f"N{i:02d}", "sector": "Tech", "watchlist": i == 39, "in_queue": i % 2 == 0,
              "changes": [{"kind": "entered", "text": "Entered the queue"}], "pe": None, "gaps": [],
              "evidence_for": ["x" * 400]} for i in range(40)]
    earnings = [{"date": "2026-10-27", "timing": "amc", "symbol": f"E{i:02d}", "name": "Co", "importance": "high" if i == 29 else "medium",
                 "watchlist": False, "spx_weight_pct": i / 10, "expectations": {"history": "y" * 400, "setup": None}}
                for i in range(30)]
    research = [{"id": f"c{i}", "kind": "condition", "state": "new", "trigger": "t", "values": {"v": "z" * 300}}
                for i in range(candidates)]
    return cards, {"names": {"changed_this_session": cards, "source": "monitor.json"},
                   "timing": {"earnings": earnings, "sources": ["events.json"]},
                   "research_candidates": research, "data_quality": {}}


def test_a_brief_over_its_cap_is_fitted_not_dropped_and_says_what_it_condensed():
    cards, brief = _busy_brief()
    A._fit(brief, 30_000)
    assert len(json.dumps(brief).encode()) <= 30_000
    kept = brief["names"]["changed_this_session"]
    assert [c["ticker"] for c in kept] == [c["ticker"] for c in cards]          # no name dropped
    full = [c for c in kept if not c.get("condensed")]
    # The first step was enough: both lists at its counts, the candidates whole.
    assert len(full) == A.NAME_CARD_STEPS[0] and full[0]["ticker"] == "N00" and any(c["ticker"] == "N39" for c in full)
    assert "pe" not in full[0] and "gaps" not in full[0]                         # empty fields left out
    assert sum(not r.get("condensed") for r in brief["timing"]["earnings"]) == A.EARNINGS_STEPS[0]
    assert len(brief["data_quality"]["condensed"]) == 2 and "monitor.json" in brief["data_quality"]["condensed"][0]
    assert brief["research_candidates"] == [{"id": "c0", "kind": "condition", "state": "new", "trigger": "t",
                                              "values": {"v": "z" * 300}}]


def test_a_busier_brief_takes_more_steps_and_finally_the_candidates_values():
    _, brief = _busy_brief()
    A._fit(brief, 20_000)
    assert len(json.dumps(brief).encode()) <= 20_000
    cards = brief["names"]["changed_this_session"]
    rows = brief["timing"]["earnings"]
    assert len(cards) == 40 and len(rows) == 30                                  # nothing dropped
    assert sum(not c.get("condensed") for c in cards) in A.NAME_CARD_STEPS[1:]
    assert sum(not r.get("condensed") for r in rows) in A.EARNINGS_STEPS
    assert not next(r for r in rows if r["symbol"] == "E29").get("condensed")   # high importance kept first
    assert all("importance" in r for r in rows)                                 # the index's next week reads it
    # One note per list, giving its final count, not one per step.
    notes = brief["data_quality"]["condensed"]
    assert len(notes) == 2 and "of 40" in notes[0] and "of 30" in notes[1]
    # Past every step, the candidates outside the index's top give up their values; none is dropped.
    _, crowded = _busy_brief(candidates=60)
    A._fit(crowded, 20_000)
    research = crowded["research_candidates"]
    assert len(research) == 60 and len(json.dumps(crowded).encode()) <= 20_000
    assert all("values" in c for c in research[:A.TOP_CANDIDATES])
    assert not any("values" in c for c in research[A.TOP_CANDIDATES:])
    assert crowded["data_quality"]["condensed"][-1].startswith("research_candidates:")


def test_a_brief_under_its_cap_only_loses_its_empty_fields():
    brief = {"names": {"changed_this_session": [{"ticker": "A", "pe": None, "gaps": []}]},
             "timing": {"earnings": []}, "data_quality": {}}
    A._fit(brief, 150_000)
    assert brief["names"]["changed_this_session"] == [{"ticker": "A"}] and brief["data_quality"]["condensed"] == []
