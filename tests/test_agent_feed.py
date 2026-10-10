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
                       "crossed": [], "sentiment": {"score": 38.7, "rating": "FEAR"}})
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
    write("anchor", {"rule": "frozen v1", "held": 0.5, "next": 0.5, "components": {}, "changes": []})


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
    assert "not a position" in brief["risk_budget"]["systematic_anchor"]["what"]
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
