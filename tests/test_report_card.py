"""REPORT CARD backend: Yahoo's reported quarter, the scorecard lines, revisions and the guide against consensus."""

import json

import pytest

from market_recap import cache
from market_recap.compute import events as E
from market_recap.sources import estimates as S


def _reported_payload(quarterly, financials=None, next_date="4Q", next_year=2026):
    return {"quoteSummary": {"result": [{"earnings": {
        "earningsChart": {"quarterly": quarterly, "currentQuarterEstimateDate": next_date,
                          "currentQuarterEstimateYear": next_year},
        "financialsChart": {"quarterly": financials or []},
    }}], "error": None}}


GE_ROW = {"date": "3Q2026", "actual": 2.25, "estimate": 2.01994}
GE_REVENUE = {"date": "3Q2026", "revenue": 13285000000}


def test_parse_reported_reads_the_last_reported_quarter_with_dict_or_plain_numbers():
    wrapped = _reported_payload([{"date": "2Q2026", "actual": {"raw": 1.9, "fmt": "1.90"}, "estimate": {"raw": 1.8}},
                                 {"date": "3Q2026", "actual": {"raw": 2.25, "fmt": "2.25"},
                                  "estimate": {"raw": 2.01994, "fmt": "2.02"}}],
                                [{"date": "3Q2026", "revenue": {"raw": 13285000000, "fmt": "13.29B"}}])
    plain = _reported_payload([{"date": "3Q2026", "actual": 2.25, "estimate": 2.01994}],
                              [{"date": "3Q2026", "revenue": 13285000000}])
    expected = {"quarter": "3Q2026", "eps": 2.25, "eps_estimate": 2.01994, "revenue": 13285000000.0,
                "next_quarter": "4Q2026"}
    assert S.parse_reported(wrapped) == expected
    assert S.parse_reported(plain) == expected


def test_parse_reported_is_none_until_yahoo_rolls_over_to_the_reported_quarter():
    # Last row is the quarter still to report: Yahoo has not moved its rows on yet.
    payload = _reported_payload([{"date": "4Q2026", "actual": None, "estimate": 2.4}], next_date="4Q")
    assert S.parse_reported(payload) is None
    assert S.parse_reported(_reported_payload([])) is None
    assert S.parse_reported({"quoteSummary": {"result": None}}) is None
    assert S.parse_reported({}) is None


def test_parse_reported_keeps_the_quarter_when_its_revenue_row_is_missing():
    payload = _reported_payload([GE_ROW], [{"date": "2Q2026", "revenue": 12000000000}])
    out = S.parse_reported(payload)
    assert out["quarter"] == "3Q2026" and out["eps"] == 2.25 and out["revenue"] is None
    assert S.parse_reported(_reported_payload([GE_ROW], None))["revenue"] is None


def test_parse_reported_without_a_next_quarter_still_reports_the_row():
    out = S.parse_reported(_reported_payload([GE_ROW], [GE_REVENUE], next_date=None, next_year=None))
    assert out["quarter"] == "3Q2026" and out["next_quarter"] is None


def test_fetch_reported_mirrors_fetch_trends_and_caches_under_its_own_namespace(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    answers = {
        "GE": _reported_payload([GE_ROW], [GE_REVENUE]),
        "ROLL": _reported_payload([{"date": "4Q2026", "actual": None, "estimate": 2.4}]),
    }
    calls = []

    def fake(symbol):
        calls.append(symbol)
        if symbol == "BOOM":
            raise RuntimeError("refused")
        return json.dumps(answers[symbol])

    monkeypatch.setattr(S, "_fetch_reported_one", fake)
    found, failed = S.fetch_reported(["GE", "ROLL", "BOOM"])
    assert found == {"GE": S.parse_reported(answers["GE"])}
    assert failed["BOOM"] == "refused" and "Yahoo has no reported quarter" in failed["ROLL"]
    assert sorted(calls) == ["BOOM", "GE", "ROLL"]
    assert (tmp_path / S.REPORTED_NAMESPACE / "GE.json").exists()

    # A second run is served from the cache: no network call at all.
    calls.clear()
    found_again, _ = S.fetch_reported(["GE"])
    assert calls == [] and found_again == found


def test_fetch_reported_gives_up_after_a_streak_of_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(S, "WORKERS", 1)
    monkeypatch.setattr(S, "GIVE_UP_AFTER", 2)

    def refuse(symbol):
        raise RuntimeError("429")

    monkeypatch.setattr(S, "_fetch_reported_one", refuse)
    found, failed = S.fetch_reported(["A", "B", "C", "D"], use_cache=False)
    assert found == {}
    assert failed["A"] == failed["B"] == "429"
    assert failed["C"] == failed["D"] == "not asked: Yahoo refused the preceding requests"


@pytest.mark.parametrize("actual, consensus, low, high, kind, expected", [
    (2.25, 2.02, 1.91, 2.10, "eps", "above_range"),          # beyond the top of the range
    (1.80, 2.02, 1.91, 2.10, "eps", "below_range"),          # beneath the bottom
    (2.00, 2.02, 1.91, 2.10, "eps", "miss"),
    (2.05, 2.02, 1.91, 2.10, "eps", "beat"),
    (2.02, 2.02, 1.91, 2.10, "eps", "inline"),
    (2.024, 2.02, None, None, "eps", "inline"),              # equal at cents
    (2.026, 2.02, None, None, "eps", "beat"),                # 2.03 against 2.02 at cents
    (2.014, 2.02, None, None, "eps", "miss"),                # 2.01 against 2.02 at cents
    (0.13, 0.12, None, None, "eps", "beat"),
    (13_285e6, 12_900e6, None, None, "revenue", "beat"),     # 3.0% above, no range supplied
    (12_900e6 * 1.002, 12_900e6, None, None, "revenue", "inline"),
    (12_900e6 * 0.9976, 12_900e6, None, None, "revenue", "inline"),   # 0.24% under still inline
    (12_900e6 * 0.997, 12_900e6, None, None, "revenue", "miss"),
    (13_000e6, 12_900e6, 12_000e6, 12_500e6, "revenue", "above_range"),
])
def test_position_places_the_actual_against_range_and_consensus(actual, consensus, low, high, kind, expected):
    assert E.position(actual, consensus, low, high, kind=kind) == expected


def test_position_is_none_without_an_actual_or_a_consensus():
    assert E.position(None, 2.0, 1.9, 2.1, kind="eps") is None
    assert E.position(2.2, None, 1.9, 2.1, kind="eps") is None
    with pytest.raises(ValueError):
        E.position(2.2, 2.0, None, None, kind="share_count")


def test_score_line_carries_surprise_and_position_and_is_none_without_actual():
    line = E.score_line(2.25, 2.02, 1.91, 2.10, "nasdaq", kind="eps")
    assert line == {"actual": 2.25, "consensus": 2.02, "low": 1.91, "high": 2.10, "surprise_pct": 11.39,
                    "position": "above_range", "source": "nasdaq"}
    rev = E.score_line(13285e6, 12900e6, None, None, "yahoo", kind="revenue")
    assert rev["surprise_pct"] == 2.98 and rev["position"] == "beat" and rev["low"] is None
    assert E.score_line(None, 2.0, 1.9, 2.1, "nasdaq", kind="eps") is None


def test_score_line_has_no_surprise_against_a_zero_or_negative_consensus():
    assert E.score_line(0.5, 0.0, None, None, "nasdaq", kind="eps")["surprise_pct"] is None
    assert E.score_line(-0.2, -0.5, None, None, "nasdaq", kind="eps")["surprise_pct"] is None
    assert E.score_line(0.5, None, None, None, "nasdaq", kind="eps")["surprise_pct"] is None


def _trend(**rows):
    return {period: {"end": end, "eps": eps} for period, (end, eps) in rows.items()}


def test_revisions_match_the_same_period_end_across_a_roll():
    # Before the report "+1q" was the quarter ending 2026-12-31; after it that same quarter is "0q".
    before = _trend(**{"0q": ("2026-09-30", 2.02), "+1q": ("2026-12-31", 2.30), "0y": ("2026-12-31", 7.05),
                       "+1y": ("2027-12-31", 7.9)})
    now = _trend(**{"0q": ("2026-12-31", 2.41), "+1q": ("2027-03-31", 2.5), "0y": ("2027-12-31", 8.0),
                    "+1y": ("2028-12-31", 8.6)})
    out = E.revisions_since(before, now)
    assert [r["period"] for r in out] == ["+1q", "+1y"]
    assert out[0] == {"period": "+1q", "label": "Next quarter", "end": "2026-12-31", "before": 2.30, "now": 2.41,
                      "change_pct": 4.78}
    # The FY2026 "0y" row (ends 2026-12-31) has rolled out of the trend; "0y" now is FY2027 and "+1y" was FY2027.
    assert out[1] == {"period": "+1y", "label": "Next year", "end": "2027-12-31", "before": 7.9, "now": 8.0,
                      "change_pct": 1.27}


def test_revisions_never_match_a_quarter_to_a_year_with_the_same_end():
    # Q4 and FY2026 both end 2026-12-31: before, "0y" must not be compared with the quarter's 2.41.
    before = _trend(**{"0y": ("2026-12-31", 7.05)})
    now = _trend(**{"0q": ("2026-12-31", 2.41), "0y": ("2027-12-31", 8.0)})
    assert E.revisions_since(before, now) == []


def test_revisions_drop_periods_with_no_match_or_no_before_value():
    before = _trend(**{"+1q": ("2026-12-31", 2.30), "0y": ("2026-12-31", None), "+1y": ("2027-12-31", 9.0)})
    now = _trend(**{"0y": ("2026-12-31", 7.31)})
    out = E.revisions_since(before, now)
    assert out == []                                                 # "+1q" has no match, "0y" no before value
    assert E.revisions_since(None, now) == [] and E.revisions_since(before, None) == []


def test_revisions_leave_the_change_empty_when_the_before_value_is_not_positive():
    before = _trend(**{"+1q": ("2026-12-31", -0.5)})
    now = _trend(**{"0q": ("2026-12-31", -0.3)})
    out = E.revisions_since(before, now)
    assert out[0]["change_pct"] is None and out[0]["now"] == -0.3


def test_guide_vs_consensus_for_a_quarter_is_set_against_next_quarter():
    guide = {"eps_low": 2.30, "eps_high": 2.50, "eps_horizon": "quarter",
             "revenue_low": None, "revenue_high": None, "revenue_horizon": None}
    before = _trend(**{"0q": ("2026-09-30", 2.02), "+1q": ("2026-12-31", 2.40), "0y": ("2026-12-31", 9.0)})
    out = E.guide_vs_consensus(guide, before)
    assert out == {"eps": {"low": 2.30, "high": 2.50, "consensus": 2.40, "against": "+1q", "position": "inside",
                           "vs_mid_pct": round((2.40 / 2.40 - 1) * 100, 1)}}


def test_guide_vs_consensus_above_and_below_the_range():
    before = _trend(**{"0q": ("2026-09-30", 2.02), "+1q": ("2026-12-31", 2.10), "0y": ("2026-12-31", 7.05)})
    above = E.guide_vs_consensus({"eps_low": 2.30, "eps_high": 2.50, "eps_horizon": "quarter"}, before)
    assert above["eps"]["position"] == "above"                       # consensus under the guided low
    assert above["eps"]["vs_mid_pct"] == round((2.40 / 2.10 - 1) * 100, 1)
    below = E.guide_vs_consensus({"eps_low": 1.80, "eps_high": 1.90, "eps_horizon": "quarter"}, before)
    assert below["eps"]["position"] == "below" and below["eps"]["vs_mid_pct"] == round((1.85 / 2.10 - 1) * 100, 1)


def test_guide_vs_consensus_for_a_year_is_set_against_this_year():
    before = _trend(**{"0q": ("2026-09-30", 2.02), "+1q": ("2026-12-31", 2.40), "0y": ("2026-12-31", 7.05),
                       "+1y": ("2027-12-31", 7.9)})
    guide = {"period": "FY2026", "eps_low": 7.10, "eps_high": 7.40, "eps_horizon": "year"}
    out = E.guide_vs_consensus(guide, before)
    assert out["eps"]["against"] == "0y" and out["eps"]["consensus"] == 7.05 and out["eps"]["position"] == "above"
    assert out["eps"]["vs_mid_pct"] == round((7.25 / 7.05 - 1) * 100, 1)


def test_guide_vs_consensus_rolls_a_year_to_next_year_when_the_quarter_closed_the_year():
    # The reported quarter ends on the same date as "0y": that fiscal year is over.
    before = _trend(**{"0q": ("2026-12-31", 2.40), "+1q": ("2027-03-31", 2.5), "0y": ("2026-12-31", 9.6),
                       "+1y": ("2027-12-31", 10.4)})
    guide = {"eps_low": 10.8, "eps_high": 11.2, "eps_horizon": "year"}
    out = E.guide_vs_consensus(guide, before)
    assert out["eps"]["against"] == "+1y" and out["eps"]["consensus"] == 10.4 and out["eps"]["position"] == "above"


def test_guide_vs_consensus_reads_revenue_and_leaves_out_missing_inputs():
    before = {"0q": {"end": "2026-09-30", "eps": 2.0, "revenue": 12.9e9},
              "+1q": {"end": "2026-12-31", "eps": 2.4, "revenue": 13.2e9}}
    guide = {"eps_low": None, "eps_high": None, "eps_horizon": None,
             "revenue_low": 13.0e9, "revenue_high": 13.4e9, "revenue_horizon": "quarter"}
    out = E.guide_vs_consensus(guide, before)
    assert list(out) == ["revenue"] and out["revenue"]["position"] == "inside"
    assert out["revenue"]["against"] == "+1q" and out["revenue"]["consensus"] == 13.2e9
    # A guide with a range but no consensus for the period, and a guide with no horizon, give nothing.
    assert E.guide_vs_consensus(guide, {"0q": {"end": "x"}}) is None
    assert E.guide_vs_consensus({"eps_low": 1, "eps_high": 2, "eps_horizon": None}, before) is None
    assert E.guide_vs_consensus(None, before) is None and E.guide_vs_consensus(guide, None) is None


def test_guide_vs_consensus_omits_the_percentage_for_a_negative_consensus():
    before = _trend(**{"0q": ("2026-09-30", -0.2), "0y": ("2026-12-31", -0.8)})
    out = E.guide_vs_consensus({"eps_low": -0.5, "eps_high": -0.3, "eps_horizon": "year"}, before)
    assert out["eps"]["position"] == "above" and "vs_mid_pct" not in out["eps"]
