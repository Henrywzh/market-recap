from datetime import date

import pandas as pd
import pytest

from market_recap.compute import evidence as V
from market_recap.compute import journal as J


def _closes(values, start="2026-07-27"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_announcement_timing_comes_from_the_acceptance_time_in_new_york():
    recent = {
        "form": ["8-K", "8-K", "10-Q", "8-K"],
        "items": ["2.02,9.01", "2.02", "", "5.02"],
        "acceptanceDateTime": ["2026-08-26T20:21:19.000Z", "2026-05-20T11:05:00.000Z", "2026-08-27T12:00:00.000Z", "2026-08-01T12:00:00.000Z"],
    }
    out = V.earnings_announcements(recent)
    assert [(a["date"], a["timing"]) for a in out] == [("2026-08-26", "amc"), ("2026-05-20", "bmo")]
    assert out[0]["time"] == "16:21"


def test_reaction_uses_the_next_session_after_the_close_and_the_same_session_before_the_open():
    closes = _closes([100, 100, 110, 99])  # Mon 07-27 .. Thu 07-30
    after_close = V.reaction(closes, date(2026, 7, 28), "amc")
    assert after_close["session"] == "2026-07-29" and after_close["move_pct"] == pytest.approx(10.0)
    before_open = V.reaction(closes, date(2026, 7, 30), "bmo")
    assert before_open["session"] == "2026-07-30" and before_open["move_pct"] == pytest.approx(-10.0)


def test_implied_move_is_the_first_expiry_on_or_after_the_reaction_session():
    summary = pd.DataFrame({
        "underlying": ["X"] * 3, "expiry": ["2026-10-09", "2026-10-16", "2026-11-20"],
        "days": [12, 19, 54], "straddle_pct": [4.1, 7.8, 11.0], "atm_iv": [0.4, 0.6, 0.45],
    })
    m = V.implied_move(summary, date(2026, 10, 15))
    assert m["expiry"] == "2026-10-16" and m["straddle_pct"] == 7.8


def test_constant_maturity_iv_interpolates_total_variance():
    rows = pd.DataFrame({"days": [20, 40], "atm_iv": [0.20, 0.30]})
    iv = V.constant_maturity_iv(rows, 30)
    expected = ((0.2 ** 2 * 20 + 0.5 * (0.3 ** 2 * 40 - 0.2 ** 2 * 20)) / 30) ** 0.5
    assert iv == pytest.approx(expected)
    assert V.constant_maturity_iv(pd.DataFrame({"days": [40], "atm_iv": [0.3]}), 30) is None


FORM4 = """<?xml version="1.0"?><ownershipDocument>
<reportingOwner><reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction>
<transactionDate><value>2026-09-02</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>1000</value></transactionShares>
<transactionPricePerShare><value>50.5</value></transactionPricePerShare></transactionAmounts>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""


def test_form4_parse_and_cluster_needs_two_different_buyers():
    tx = V.parse_form4(FORM4)
    assert tx == [{"date": "2026-09-02", "owner": "Doe Jane", "role": "director", "code": "P",
                   "shares": 1000.0, "price": 50.5, "value": 50500.0}]
    alone = V.insider_summary(tx + tx, date(2026, 9, 25))
    assert alone["cluster"] is None and alone["buy_value"] == 101000
    second = [{**tx[0], "owner": "Roe Rick", "date": "2026-09-20"}]
    together = V.insider_summary(tx + second, date(2026, 9, 25))
    assert together["cluster"]["count"] == 2
    assert V.parse_form4("not xml") == []


def test_short_and_ratings_become_evidence_lines_by_the_configured_rule():
    short = V.short_summary([
        {"date": "2026-08-15", "interest": 100.0, "days_to_cover": 2.0},
        {"date": "2026-08-31", "interest": 110.0, "days_to_cover": 2.2},
        {"date": "2026-09-15", "interest": 130.0, "days_to_cover": 2.6},
    ])
    assert short["change_1m_pct"] == pytest.approx(30.0)
    ratings = V.ratings_summary([
        {"date": "2026-09-10", "Firm": "A", "Action": "down", "currentPriceTarget": 90, "priorPriceTarget": 100},
        {"date": "2026-09-01", "Firm": "B", "Action": "down"},
        {"date": "2026-03-01", "Firm": "C", "Action": "up"},  # outside 90 days
    ], date(2026, 9, 25))
    assert (ratings["upgrades"], ratings["downgrades"], ratings["target_cuts"]) == (0, 2, 1)
    for_, against = V.evidence_lines(None, short, ratings, {"short_change_pct": 20})
    assert for_ == [] and len(against) == 2


def test_name_decisions_are_judged_against_the_index_over_the_horizon():
    idx = _closes([100] * 60)
    up = _closes([100] * 10 + [110] * 50)
    entry = {"date": "2026-07-27", "ticker": "X", "action": "enter", "reason": "r", "horizon_days": 30}
    review = J.review_name(entry, up, idx, date(2026, 9, 25), 60)
    assert review["matured"] and review["excess_pct"] == pytest.approx(10.0) and review["right"] is True
    passed = J.review_name({**entry, "action": "pass"}, up, idx, date(2026, 9, 25), 60)
    assert passed["right"] is False
    still_open = J.review_name({**entry, "horizon_days": 365}, up, idx, date(2026, 9, 25), 60)
    assert still_open["matured"] is False and still_open["right"] is None


def test_override_value_is_the_exposure_gap_times_the_index_return():
    idx = _closes([100, 110, 121])       # +10% then +10%
    anchor = _closes([0.5, 0.5, 0.5])
    entry = {"date": "2026-07-27", "action": "override", "exposure": 1.0, "reason": "r", "horizon_days": 7}
    review = J.review_override(entry, idx, anchor, date(2026, 9, 25), 60)
    # (1.0 - 0.5) x (10% + 10%) = 10% = 1000 bp
    assert review["value_bp"] == pytest.approx(1000.0) and review["right"] is True
    assert review["anchor_exposure"] == 0.5


def test_validation_and_checkpoints():
    assert J.validate({"date": "2026-09-01", "action": "buy", "reason": "x"}, 0)
    assert J.validate({"date": "2026-09-01", "action": "override", "reason": "x"}, 0)
    assert J.validate({"date": "2026-09-01", "action": "enter", "ticker": "X", "reason": "x"}, 0) == []
    points = J.checkpoints([{"date": "2026-09-01", "ticker": "X", "action": "enter", "checkpoints": [
        {"date": "2026-09-20", "text": "due"}, {"date": "2026-10-20", "text": "ahead"}, {"date": "2026-08-01", "text": "old"}]}],
        date(2026, 9, 25))
    assert [(p["text"], p["due"]) for p in points] == [("due", True), ("ahead", False)]
