from market_recap.panels import events


RECORDED = {
    "2026-10-16": {"GE": {"0q": {"end": "2026-09-30", "eps": 2.0, "low": 1.9, "high": 2.1, "revenue": 12.8e9}}},
    "2026-10-19": {"GE": {"0q": {"end": "2026-09-30", "eps": 2.02, "low": 1.91, "high": 2.10, "revenue": 12.9e9},
                          "+1q": {"end": "2026-12-31", "eps": 2.30, "low": 2.1, "high": 2.5, "revenue": 13.5e9},
                          "0y": {"end": "2026-12-31", "eps": 7.05, "low": 6.9, "high": 7.2, "revenue": 50e9}}},
    # The evening of the report: already after it, never "before".
    "2026-10-20": {"GE": {"0q": {"end": "2026-12-31", "eps": 2.41}}},
}
NOW = {"0q": {"end": "2026-12-31", "eps": 2.41}, "0y": {"end": "2026-12-31", "eps": 7.31}}
YAHOO = {"quarter": "3Q2026", "eps": 2.25, "eps_estimate": 2.01994, "revenue": 13.285e9, "next_quarter": "4Q2026"}


def test_before_is_the_last_recorded_consensus_strictly_before_the_report():
    day, trend = events._before(RECORDED, "GE", "2026-10-20")
    assert day == "2026-10-19" and trend["0q"]["eps"] == 2.02
    assert events._before(RECORDED, "RTX", "2026-10-20") == (None, None)


def test_yahoo_counts_only_when_its_estimate_is_this_reports_consensus():
    assert events._same_quarter(YAHOO, 2.02)
    # Not rolled over yet: the last row is the quarter before, with its own estimate.
    assert not events._same_quarter({**YAHOO, "eps_estimate": 1.86}, 2.02)
    assert not events._same_quarter(YAHOO, None)


def test_report_card_fills_eps_from_yahoo_when_nasdaq_has_not_posted():
    event = {"date": "2026-10-20", "eps": None, "eps_forecast": 2.02}
    history = [{"date": "2026-10-20", "drift_5d": 1.2, "drift_20d": None,
                "guide": {"eps_low": 7.1, "eps_high": 7.4, "eps_horizon": "year", "period": "FY2026"}}]
    day, before = events._before(RECORDED, "GE", "2026-10-20")
    card = events._report_card(event, history, day, before, NOW, YAHOO, 0)
    eps, revenue = card["scorecard"]["eps"], card["scorecard"]["revenue"]
    assert eps["actual"] == 2.25 and eps["source"] == "yahoo" and eps["position"] == "above_range"
    assert revenue["actual"] == 13.285e9 and revenue["consensus"] == 12.9e9 and revenue["position"] == "beat"
    assert card["scorecard"]["consensus_day"] == "2026-10-19" and card["scorecard"]["quarter"] == "3Q2026"
    assert card["guide"]["vs_consensus"]["eps"]["position"] == "above"
    assert {r["period"] for r in card["revisions"]} == {"+1q", "0y"}
    assert card["drift"] == {"5d": 1.2, "20d": None} and card["sessions_since"] == 0


def test_report_card_keeps_nasdaq_eps_and_drops_a_yahoo_row_from_another_quarter():
    event = {"date": "2026-10-20", "eps": 2.24, "eps_forecast": 2.02}
    card = events._report_card(event, [], None, None, None, {**YAHOO, "eps_estimate": 1.86}, 3)
    assert card["scorecard"]["eps"]["source"] == "nasdaq" and card["scorecard"]["eps"]["actual"] == 2.24
    assert card["scorecard"]["revenue"] is None and card["scorecard"]["quarter"] is None
    assert card["guide"] is None and card["revisions"] == [] and card["sessions_since"] == 3


def test_a_guide_is_shown_only_when_it_is_plausible_against_the_street():
    _, before = events._before(RECORDED, "GE", "2026-10-20")
    good = {"eps_low": 7.1, "eps_high": 7.4, "eps_horizon": "year", "revenue_low": 40e9, "revenue_high": 99e9,
            "revenue_horizon": "year", "period": "FY2026"}
    kept = events._plausible_guide(good, before)
    # The revenue range is too wide to be a guide: dropped, the EPS guide kept.
    assert set(kept["vs_consensus"]) == {"eps"}
    assert "revenue_low" not in kept and kept["eps_low"] == 7.1
    # Operating profit read as EPS: 9.10-9.40 against a street at 7.05.
    assert events._plausible_guide({"eps_low": 9.1, "eps_high": 9.4, "eps_horizon": "year"}, before) is None
    # A range from two unrelated numbers.
    assert events._plausible_guide({"eps_low": 0.06, "eps_high": 11.1, "eps_horizon": "year"}, before) is None
    assert events._plausible_guide(good, None) is None
    # 16.7% above the street at the mid: GE's operating profit again, against a later consensus.
    later = {**before, "0y": {**before["0y"], "eps": 7.93}}
    assert events._plausible_guide({"eps_low": 9.1, "eps_high": 9.4, "eps_horizon": "year"}, later) is None
