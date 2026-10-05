from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from market_recap.sources import treasury as T


def row(**changes):
    return {**{key: "null" for key in T.AUCTION_FIELDS}, "cusip": "91282TEST", "auction_date": "2026-09-24",
            "security_type": "Note", "security_term": "7-Year", "original_security_term": "7-Year",
            "issue_date": "2026-09-30", "record_date": "2026-09-30", "reopening": "No",
            "high_yield": "5.0", "bid_to_cover_ratio": "2.4", "comp_accepted": "1000",
            "direct_bidder_accepted": "300", "indirect_bidder_accepted": "600", "primary_dealer_accepted": "100",
            "pdf_filenm_comp_results": "R_20260924_test.pdf", **changes}


def parse(rows):
    return T.parse_auction_results({"data": rows}, observed_at="2026-10-01T12:00:00Z", since="2026-09-01", until="2026-10-01")


def test_completed_auction_units_composition_and_timestamp():
    r = parse([row()])[0]
    assert r["indirect_bidder_share_pct"] == 60
    assert r["high_yield"] == 5.0
    assert r["release_time"] is None
    assert r["record_date"] != r["auction_date"]
    assert r["tail_bps"] is None


def test_future_announcements_and_unreleased_results_are_not_zero_demand():
    assert parse([row(auction_date="2026-10-07"), row(pdf_filenm_comp_results="null", bid_to_cover_ratio="null")]) == []


def test_frn_null_yield_is_valid_and_original_tenor_groups_reopenings():
    r = parse([row(security_type="FRN", high_yield="null", security_term="1-Year 10-Month", original_security_term="2-Year", reopening="Yes")])[0]
    assert r["high_yield"] is None
    assert r["comparison_group"] == "FRN|2-Year|reopening=Yes"


@pytest.mark.parametrize("rows", [[row(), row()], [row(comp_accepted="900")], [row(indirect_bidder_accepted="-1")], [row(high_yield="inf")]])
def test_invalid_auction_grain_and_allocations_fail(rows):
    with pytest.raises(ValueError):
        parse(rows)


def test_collector_keeps_last_good_on_failed_refresh(tmp_path, monkeypatch):
    recent = row(auction_date=(date.today() - timedelta(days=3)).isoformat())
    monkeypatch.setattr(T, "get_bytes", lambda *a, **kw: json.dumps({"data": [recent], "meta": {"total-pages": 1}}).encode())
    result = T.collect_auction_results(days=365, root=tmp_path)
    assert result["status"] == "ok"
    before = (tmp_path / "latest.json").read_bytes()
    monkeypatch.setattr(T, "get_bytes", lambda *a, **kw: b'{"data": []}')
    with pytest.raises(ValueError):
        T.collect_auction_results(days=365, root=tmp_path)
    assert (tmp_path / "latest.json").read_bytes() == before
    assert json.loads((tmp_path / "last_attempt.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("cover", ["-1", "0"])
def test_invalid_bid_to_cover_is_not_completed_demand(cover):
    with pytest.raises(ValueError, match="bid-to-cover"):
        parse([row(bid_to_cover_ratio=cover)])


def test_narrow_refresh_keeps_history_and_missing_overlap_fails(tmp_path, monkeypatch):
    old = row(auction_date=(date.today() - timedelta(days=20)).isoformat(), cusip="old")
    new = row(auction_date=(date.today() - timedelta(days=3)).isoformat(), cusip="new")
    def response(items):
        return json.dumps({"data": items, "meta": {"total-pages": 1}}).encode()
    monkeypatch.setattr(T, "get_bytes", lambda *a, **kw: response([old, new]))
    T.collect_auction_results(days=90, root=tmp_path)
    monkeypatch.setattr(T, "get_bytes", lambda *a, **kw: response([new]))
    result = T.collect_auction_results(days=7, root=tmp_path)
    assert len(result["rows"]) == 2 and result["captured_row_count"] == 1
    before = (tmp_path / "latest.json").read_bytes()
    with pytest.raises(ValueError, match="coverage"):
        T.collect_auction_results(days=90, root=tmp_path)
    assert (tmp_path / "latest.json").read_bytes() == before


def test_missing_pagination_metadata_cannot_claim_complete(tmp_path, monkeypatch):
    recent = row(auction_date=(date.today() - timedelta(days=3)).isoformat())
    monkeypatch.setattr(T, "get_bytes", lambda *a, **kw: json.dumps({"data": [recent]}).encode())
    with pytest.raises(ValueError, match="pagination"):
        T.collect_auction_results(root=tmp_path)


def test_public_summary_compares_only_same_group_and_keeps_tail_unknown(tmp_path, monkeypatch):
    old = row(auction_date=(date.today() - timedelta(days=20)).isoformat(), cusip="old", high_yield="4.8", bid_to_cover_ratio="2.2")
    new = row(auction_date=(date.today() - timedelta(days=3)).isoformat(), cusip="new")
    other = row(auction_date=(date.today() - timedelta(days=2)).isoformat(), cusip="other", original_security_term="10-Year", security_term="10-Year")
    monkeypatch.setattr(T, "get_bytes", lambda *a, **kw: json.dumps({"data": [old, new, other], "meta": {"total-pages": 1}}).encode())
    T.collect_auction_results(days=90, root=tmp_path)
    summary = T.public_auction_summary(tmp_path / "latest.json")
    seven = next(g for g in summary["groups"] if g["original_term"] == "7-Year")
    assert seven["high_yield_change_bps"] == pytest.approx(20)
    assert seven["bid_to_cover_change"] == pytest.approx(0.2)
    assert seven["tail_bps"] is None
    assert all(g["events"] == 1 or g["original_term"] == "7-Year" for g in summary["groups"])
