"""POSITIONING: the trend-follower proxy and the FINRA helpers."""

from datetime import date

import pandas as pd

from market_recap.compute import positioning as P
from market_recap.sources import finra


def _close(values):
    return pd.Series(values, index=pd.bdate_range("2024-01-01", periods=len(values)), dtype=float)


def test_score_is_the_mean_vote_of_the_lookbacks():
    rising = _close(range(100, 400))
    assert P.trend_score(rising).iloc[-1] == 1.0
    falling = _close(range(400, 100, -1))
    assert P.trend_score(falling).iloc[-1] == -1.0
    assert P.label(1.0) == "LONG" and P.label(-0.5) == "SHORT" and P.label(0.0) == "MIXED"


def test_flip_level_is_the_close_tomorrow_is_compared_with():
    close = _close(range(100, 400))
    flips = {f["lookback"]: f for f in P.flip_levels(close)}
    # Tomorrow's 21-session return compares with the close 20 sessions before today.
    assert flips["1M"]["flip_level"] == float(close.iloc[-21])
    assert flips["1M"]["signal"] == 1
    assert round(flips["1M"]["return_pct"], 6) == round((close.iloc[-1] / close.iloc[-22] - 1) * 100, 6)
    assert flips["1M"]["distance_pct"] < 0


def test_moving_average_levels():
    close = _close([100.0] * 199 + [120.0])
    levels = {m["window"]: m for m in P.ma_levels(close)}
    assert levels[200]["above"] is True
    assert round(levels[200]["level"], 6) == 100.1


def test_finra_symbols_run_the_share_class_on():
    assert finra.finra_symbol("BRK-B") == "BRKB"
    assert finra.finra_symbol("BF.B") == "BFB"
    assert finra.finra_symbol("NVDA") == "NVDA"


def test_candidate_settlement_dates_are_mid_month_and_month_end_newest_first():
    assert finra.candidate_dates(date(2026, 9, 29), 4) == [
        date(2026, 9, 15), date(2026, 8, 31), date(2026, 8, 15), date(2026, 7, 31)]
    assert finra.candidate_dates(date(2026, 1, 10), 2) == [date(2025, 12, 31), date(2025, 12, 15)]


def test_an_unpublished_round_is_not_cached(tmp_path, monkeypatch):
    from market_recap import cache

    monkeypatch.setattr(cache, "path_for", lambda ns, name, suffix: tmp_path / f"{ns}-{name}{suffix}")
    answers = {"2026-09-30": None, "2026-09-29": None}
    monkeypatch.setattr(finra, "_query", lambda day, symbols: answers.get(day.isoformat()))
    assert finra.fetch_round(date(2026, 9, 30), ["NVDA"], max_back=1).empty
    assert not list(tmp_path.iterdir())
    answers["2026-09-30"] = [{"symbolCode": "NVDA", "settlementDate": "2026-09-30", "currentShortPositionQuantity": 5,
                              "previousShortPositionQuantity": 4, "averageDailyVolumeQuantity": 10,
                              "daysToCoverQuantity": 0.5, "changePercent": 25.0, "revisionFlag": None}]
    frame = finra.fetch_round(date(2026, 9, 30), ["NVDA"], max_back=1)
    assert frame["shares_short"].tolist() == [5] and frame["settlement_date"].iloc[0] == pd.Timestamp("2026-09-30")
