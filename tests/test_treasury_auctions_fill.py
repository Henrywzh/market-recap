"""Fiscal Data's auction results stopped at 2026-10-08; TreasuryDirect fills what it lacks."""

import json

from market_recap.sources import treasury


def _fiscal(cusip, day, cover):
    return {"cusip": cusip, "auction_date": day, "security_type": "Note", "security_term": "3-Year",
            "original_security_term": "3-Year", "issue_date": day, "record_date": day, "reopening": "No",
            "high_yield": "4.9", "bid_to_cover_ratio": str(cover), "comp_accepted": "100", "direct_bidder_accepted": "20",
            "indirect_bidder_accepted": "70", "primary_dealer_accepted": "10", "pdf_filenm_comp_results": "R.pdf",
            "xml_filenm_comp_results": "R.xml", "inflation_index_security": "No", "floating_rate": "No"}


def _td(cusip, day, cover, *, tips="No", result="R.pdf"):
    return {"cusip": cusip, "auctionDate": "", "competitiveAuctionCloseDate": f"{day}T00:00:00", "issueDate": f"{day}T00:00:00",
            "securityType": "Note", "securityTerm": "2-Year", "originalSecurityTerm": "2-Year", "reopening": "No",
            "highYield": "4.5", "bidToCoverRatio": str(cover), "subtotalCompetitiveParAwardedInsideOfOfferingAmount": "200",
            "directBiddersCompetitiveParAwarded": "40", "indirectBiddersCompetitiveParAwarded": "130",
            "primaryDealersCompetitiveParAwarded": "30", "treasuryAuctionResultsPressReleaseFileName": result,
            "treasuryAuctionResultsXmlFileName": "R.xml", "inflationProtected": tips, "floatingRate": "No"}


def test_treasurydirect_fills_only_what_fiscal_data_lacks(monkeypatch):
    monkeypatch.setattr(treasury, "_fiscal_auction_history", lambda **k: treasury.parse_auction_results(
        {"data": [_fiscal("A", "2026-10-06", 2.62)]}, observed_at="2026-11-09", since="2008-01-01", until="2026-11-09"))
    bodies = {"note": [_td("A", "2026-10-06", 9.99), _td("B", "2026-10-26", 2.59), _td("C", "2026-10-30", 2.4, tips="Yes"),
                       _td("D", "2026-11-12", 2.5, result="")], "bond": []}
    monkeypatch.setattr(treasury.cache, "fetch_bytes", lambda ns, key, fetch, **k: json.dumps(bodies[key.rsplit("-", 1)[1]]).encode())
    rows = treasury.fetch_auction_history()
    # Fiscal Data's own row stands; the 2-year is added; TIPS and an unresulted auction are not.
    assert [(r["cusip"], r["bid_to_cover_ratio"]) for r in rows] == [("A", 2.62), ("B", 2.59)]
    assert rows[1]["primary_dealer_share_pct"] == 15 and rows[1]["source_url"] == treasury.TD_AUCTIONS_PAGE


def test_a_treasurydirect_failure_leaves_fiscal_data_standing(monkeypatch):
    monkeypatch.setattr(treasury, "_fiscal_auction_history", lambda **k: ["fiscal"])
    def fail(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(treasury, "_treasurydirect_recent", fail)
    assert treasury.fetch_auction_history() == ["fiscal"]
