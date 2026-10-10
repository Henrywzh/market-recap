from datetime import date

import pandas as pd
import pytest

from market_recap.compute import evidence as V


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


def test_strict_form4_cluster_excludes_indirect_and_planned_buys():
    def filing(owner, day, direct="D", plan="0", deemed=None):
        return f"""<ownershipDocument><documentType>4</documentType>
        <issuer><issuerCik>123</issuerCik></issuer><aff10b5One>{plan}</aff10b5One>
        <reportingOwner><reportingOwnerId><rptOwnerCik>{owner}</rptOwnerCik><rptOwnerName>Owner {owner}</rptOwnerName></reportingOwnerId></reportingOwner>
        <nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>{day}</value></transactionDate>
        {"" if deemed is None else f"<deemedExecutionDate>{deemed}</deemedExecutionDate>"}
        <transactionCoding><transactionCode>P</transactionCode><equitySwapInvolved>0</equitySwapInvolved></transactionCoding>
        <transactionAmounts><transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>150</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
        <ownershipNature><directOrIndirectOwnership><value>{direct}</value></directOrIndirectOwnership></ownershipNature>
        </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""

    one = V.strict_form4_buys(filing(1, "2026-09-21"), issuer_cik=123, filed="2026-09-22")
    two = V.strict_form4_buys(filing(2, "2026-09-24"), issuer_cik=123, filed="2026-09-25")
    assert V.strict_form4_buys(filing(3, "2026-09-24", direct="I"), issuer_cik=123, filed="2026-09-25") == []
    assert V.strict_form4_buys(filing(3, "2026-09-24", plan="1"), issuer_cik=123, filed="2026-09-25") == []
    assert V.strict_form4_buys(filing(3, "2026-09-24"), issuer_cik=124, filed="2026-09-25") == []
    # An empty deemed-execution element is common boilerplate; only a dated one excludes.
    assert len(V.strict_form4_buys(filing(3, "2026-09-24", deemed=""), issuer_cik=123, filed="2026-09-25")) == 1
    assert V.strict_form4_buys(filing(3, "2026-09-24", deemed="<value>2026-09-20</value>"),
                               issuer_cik=123, filed="2026-09-25") == []
    cluster = V.strict_buy_cluster(one + two, pd.bdate_range("2026-09-21", periods=10))
    assert cluster["count"] == 2 and cluster["value"] == 300_000
    assert cluster["available"] == "2026-09-25"


def test_strict_form4_cluster_window_has_five_sessions_including_the_first():
    sessions = pd.bdate_range("2026-09-21", periods=10)
    first = {"date": "2026-09-21", "filed": "2026-09-22", "owner_id": "1",
             "owner": "First", "value": 150_000}
    fifth = {"date": "2026-09-25", "filed": "2026-09-28", "owner_id": "2",
             "owner": "Second", "value": 150_000}
    sixth = {**fifth, "date": "2026-09-28", "filed": "2026-09-29"}
    assert V.strict_buy_cluster([first, fifth], sessions) is not None
    assert V.strict_buy_cluster([first, sixth], sessions) is None


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


def test_a_same_day_sec_stamp_is_eastern_wall_clock():
    """Micron's 16:02 release on 2026-09-30 was served as 16:02:22Z that evening."""
    recent = {"form": ["8-K", "8-K"], "items": ["2.02,9.01", "2.02,9.01"],
              "acceptanceDateTime": ["2026-09-30T16:02:22.000Z", "2026-06-24T20:02:01.000Z"]}
    fresh, old = V.earnings_announcements(recent, today=date(2026, 9, 30))
    assert (fresh["date"], fresh["time"], fresh["timing"]) == ("2026-09-30", "16:02", "amc")
    assert (old["time"], old["timing"]) == ("16:02", "amc")        # corrected stamps are UTC
    # Once SEC has corrected it, reading it as Eastern still says after the close.
    recent["acceptanceDateTime"][0] = "2026-09-30T20:02:22.000Z"
    assert V.earnings_announcements(recent, today=date(2026, 10, 1))[0]["timing"] == "amc"


def test_release_time_comes_from_the_index_page_then_the_filing_date():
    """By 2026-10-03 SEC's stamps ran twice the Eastern offset late."""
    recent = {"form": ["8-K", "8-K"], "items": ["2.02", "2.02"],
              "acceptanceDateTime": ["2026-10-01T00:02:22.000Z", "2026-07-14T14:30:38.000Z"],
              "filingDate": ["2026-09-30", "2026-07-14"], "accessionNumber": ["a1", "a2"]}
    index = {"a1": "2026-09-30 16:02:22", "a2": "2026-07-14 06:30:38"}
    mu, jpm = V.earnings_announcements(recent, today=date(2026, 10, 3), exact=index.get)
    assert (mu["date"], mu["time"], mu["timing"]) == ("2026-09-30", "16:02", "amc")
    assert (jpm["time"], jpm["timing"]) == ("06:30", "bmo")
    # No index page: the reading whose date is the filing date (UTC here).
    mu = V.earnings_announcements(recent, today=date(2026, 10, 3))[0]
    assert (mu["date"], mu["timing"]) == ("2026-09-30", "amc")


# --- Short interest is asked for together, and a failure is still reported where it is used --
def test_prefetch_returns_each_answer_or_the_exception_it_raised():
    from market_recap.panels import evidence as panel

    def fetch(symbol):
        if symbol == "BAD":
            raise RuntimeError("HTTP 429")
        return [symbol.lower()]
    answers = panel.prefetch(fetch, ["AAA", "BAD", "CCC"])
    assert answers["AAA"] == (["aaa"], None) and answers["CCC"] == (["ccc"], None)
    assert answers["BAD"][0] is None and str(answers["BAD"][1]) == "HTTP 429"
    assert list(answers) == ["AAA", "BAD", "CCC"]                     # the order asked, whatever finished first


def test_prefetch_asks_several_at_a_time():
    import threading
    import time
    from market_recap.panels import evidence as panel
    lock, live, peak = threading.Lock(), [0], [0]

    def slow(symbol):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return symbol
    assert len(panel.prefetch(slow, [f"S{i}" for i in range(12)], workers=4)) == 12
    assert 1 < peak[0] <= 4                                           # together, but never past the pool
