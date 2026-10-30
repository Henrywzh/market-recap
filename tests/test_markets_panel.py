"""INDICES: what moved an index needs its basket's weights; without them the card is left out, not the panel."""

import pandas as pd

from market_recap.panels import markets as P


def test_contributions_need_the_basket_weights():
    panel = pd.DataFrame({"AAA": [100.0, 102.0], "BBB": [50.0, 49.0]}, index=pd.bdate_range("2026-10-26", periods=2))
    members = pd.DataFrame({"yahoo_symbol": ["AAA", "BBB"], "weight": [60.0, 40.0], "sector": ["Tech", "Energy"]})
    c = P._contributions(panel, members)
    assert round(c["total_pp"], 3) == round(0.6 * 2.0 + 0.4 * -2.0, 3)
    assert [x["ticker"] for x in c["leaders"]] == ["AAA"] and [x["ticker"] for x in c["laggards"]] == ["BBB"]
    assert P._contributions(panel, members.drop(columns=["weight"])) is None
    assert P._contributions(panel, pd.DataFrame()) is None


def test_one_empty_session_does_not_blank_the_breadth_history():
    """2026-10-30: a session the feed left empty blanked the year of members above their averages."""
    import numpy as np
    from market_recap.compute import returns as R
    from market_recap.panels import overview as O
    idx = pd.bdate_range("2024-06-03", periods=600)
    rng = np.random.default_rng(3)
    closes = pd.DataFrame({f"S{i}": 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx)))) for i in range(20)}, index=idx)
    closes.iloc[-30] = np.nan                       # one whole session missing
    h = O.breadth_history(closes)
    assert len(h["dates"]) == 252 and h["dates"][-1] == idx[-1].strftime("%Y-%m-%d")
    assert idx[-30].strftime("%Y-%m-%d") not in h["dates"]   # the empty session itself has no reading
    # The last point is the day's own figure.
    assert h["above_200d"][-1] == round(R.pct_above_moving_average(closes, 200), 1)


def test_validation_flags_a_today_reading_with_no_history():
    from market_recap import validate as V
    block = {"members": 2, "advance_decline": {"advancers": 1, "decliners": 1, "unchanged": 0}, "breadth": {"above_200d": 50.0}}
    broken = V._check_latest_session({"as_of": "2026-10-29", "indices": {"SPX": {**block, "breadth_history": {"dates": []}}}})
    assert [f.check for f in broken] == ["breadth_history"]
    fine = V._check_latest_session({"as_of": "2026-10-29", "indices": {"SPX": {**block, "breadth_history": {"dates": ["2026-10-29"]}}}})
    assert fine == []
