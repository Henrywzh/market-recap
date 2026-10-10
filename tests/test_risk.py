from datetime import date

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import priced as P
from market_recap.compute import risk as R
from market_recap.sources import cboe


def _series(values, start="2025-01-01", freq="B"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float)


def test_tile_reads_level_percentiles_and_threshold():
    s = _series(list(range(1, 301)))
    t = R.tile(s, risk_when="high", threshold=250, digits=0)
    assert t["value"] == 300
    assert t["pct_1y"] == 100 and t["pct_long"] == 100
    assert t["breach"] is True
    # A week earlier (5 sessions) it was already past 250: no crossing.
    assert t["crossed"] is None
    assert t["change_1w"] == 5


def test_crossing_into_the_threshold_within_the_week_is_flagged():
    s = _series([10.0] * 50 + [30.0])
    t = R.tile(s, risk_when="high", threshold=25)
    assert t["breach"] is True and t["crossed"] == "into"
    back = R.tile(_series([30.0] * 50 + [10.0]), risk_when="high", threshold=25)
    assert back["breach"] is False and back["crossed"] == "out"


def test_low_side_and_extreme_tails():
    assert R.breach(-3, risk_when="low", threshold=-2) is True
    assert R.breach(-1, risk_when="low", threshold=-2) is False
    assert R.breach(1, risk_when="extreme", threshold=5, percentile=3) is True
    assert R.breach(1, risk_when="extreme", threshold=5, percentile=97) is True
    assert R.breach(1, risk_when="extreme", threshold=5, percentile=50) is False
    assert R.breach(None, risk_when="high", threshold=1) is None


def test_realised_vol_of_a_constant_drift_is_zero():
    close = _series(100 * np.exp(0.001 * np.arange(60)))
    assert R.realised_vol(close).iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_correlation_is_one_for_identical_members_and_near_zero_for_independent_ones():
    rng = np.random.default_rng(1)
    common = rng.normal(0, 0.01, 200)
    same = pd.DataFrame({k: 100 * np.exp(np.cumsum(common)) for k in "ABCD"},
                        index=pd.bdate_range("2025-01-01", periods=200))
    weights = pd.Series({"A": 40.0, "B": 30.0, "C": 20.0, "D": 10.0})
    corr, disp = R.correlation_and_dispersion(same, weights)
    assert corr.iloc[-1] == pytest.approx(1.0, abs=1e-6)
    assert disp.iloc[-1] == pytest.approx(0.0, abs=1e-6)
    independent = pd.DataFrame({k: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 200))) for k in "ABCD"},
                               index=same.index)
    corr2, _ = R.correlation_and_dispersion(independent, weights)
    assert abs(corr2.iloc[-60:].mean()) < 0.3


def test_net_liquidity_subtracts_tga_and_reverse_repo_in_billions():
    wed = pd.date_range("2026-01-07", periods=3, freq="W-WED")
    assets = pd.Series([7_000_000.0, 7_100_000.0, 7_200_000.0], index=wed)   # $mn
    tga = pd.Series([800_000.0, 700_000.0, 900_000.0], index=wed)            # $mn
    rrp = pd.Series([100.0, 50.0, 25.0], index=wed)                          # $bn
    out = R.net_liquidity(assets, tga, rrp)
    assert out.tolist() == [6100.0, 6350.0, 6275.0]


def test_vix_future_expiry_is_thirty_days_before_the_next_months_third_friday():
    assert cboe.vx_expiry(2026, 10) == date(2026, 10, 21)
    assert cboe.vx_expiry(2026, 12) == date(2026, 12, 16)
    assert cboe.vx_expiries(date(2026, 10, 22), 2) == [date(2026, 11, 18), date(2026, 12, 16)]


def test_meeting_month_method_recovers_a_known_hike():
    # A 25bp hike effective after a meeting on day 15 of a 30-day month,
    # starting at 4.00%: the month averages 4.00 for 15 days and 4.25 after.
    meeting = date(2026, 11, 15)
    avg = (15 * 4.00 + 15 * 4.25) / 30
    prices = {"2026-11": 100 - avg, "2026-12": 100 - 4.25}
    path = P.policy_path(prices, [meeting], 4.00)
    assert path[0]["change_bp"] == pytest.approx(25.0)
    # Without the next month's contract it is solved from this month's.
    solo = P.policy_path({"2026-11": 100 - avg}, [meeting], 4.00)
    assert solo[0]["change_bp"] == pytest.approx(25.0)
    assert solo[0]["method"] == "this month's contract"


def test_path_chains_meetings_and_stops_where_prices_end():
    meetings = [date(2026, 10, 28), date(2026, 12, 9), date(2027, 1, 27)]
    prices = {"2026-10": 100 - 3.88, "2026-11": 100 - 4.13, "2026-12": 100 - (9 * 4.13 + 22 * 4.38) / 31}
    path = P.policy_path(prices, meetings, 3.88)
    assert [m["date"] for m in path] == ["2026-10-28", "2026-12-09"]
    assert path[0]["change_bp"] == pytest.approx(25.0, abs=0.01)
    assert path[1]["cumulative_bp"] == pytest.approx(50.0, abs=0.05)


def test_step_probabilities_and_two_nearest_ranges():
    s = P.step_probabilities(15.5)
    assert s["direction"] == "hike" and s["whole_steps"] == 0 and s["p_next_step"] == pytest.approx(0.62)
    ranges = P.two_nearest(35.9, 3.75, 4.00)
    assert [r["range"] for r in ranges] == ["4.00–4.25", "4.25–4.50"]
    assert sum(r["probability"] for r in ranges) == pytest.approx(1.0)


def test_kalshi_meeting_expectation_uses_mids_and_counts_more_than_25_as_50():
    event = {"event_ticker": "KXFEDDECISION-26OCT", "title": "Fed decision in Oct 2026?", "markets": [
        {"yes_sub_title": "Cut >25bps", "yes_bid_dollars": "0.00", "yes_ask_dollars": "0.01", "last_price_dollars": "0.01", "close_time": "2026-10-28T18:00:00Z"},
        {"yes_sub_title": "Fed maintains rate", "yes_bid_dollars": "0.35", "yes_ask_dollars": "0.36", "last_price_dollars": "0.36", "close_time": "2026-10-28T18:00:00Z"},
        {"yes_sub_title": "Hike 25bps", "yes_bid_dollars": "0.63", "yes_ask_dollars": "0.64", "last_price_dollars": "0.64", "close_time": "2026-10-28T18:00:00Z"},
    ]}
    k = P.kalshi_meeting(event)
    assert k["date"] == "2026-10-28"
    assert k["p_hike"] == pytest.approx(0.635 / (0.005 + 0.355 + 0.635), abs=1e-3)
    assert k["expected_bp"] == pytest.approx((-50 * 0.005 + 25 * 0.635) / (0.005 + 0.355 + 0.635), abs=0.1)


def test_a_daily_tile_has_a_one_session_change_and_a_daily_last_year():
    s = _series([float(v) for v in range(1, 301)])
    t = R.tile(s, risk_when="high", threshold=250, digits=0)
    assert t["change_1d"] == 1 and t["previous_date"] == s.index[-2].strftime("%Y-%m-%d")
    assert t["recent"]["dates"][-1] == t["date"]
    # The last year day by day; the long history stays weekly.
    assert len(t["recent"]["dates"]) > len([d for d in t["history"]["dates"] if d >= t["recent"]["dates"][0]])
    weekly = R.tile(_series([1.0, 2.0, 3.0], freq="W-FRI"), risk_when="high", threshold=5, daily=False)
    assert weekly["change_1d"] is None and weekly["recent"] is None


def test_a_cboe_file_behind_the_session_is_asked_for_again_once_per_build(monkeypatch, tmp_path):
    from market_recap import cache
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cboe, "_asked", set())
    files = iter(["DATE,CLOSE\n10/08/2026,15.41\n", "DATE,CLOSE\n10/08/2026,15.41\n10/09/2026,14.84\n"])
    calls = []
    monkeypatch.setattr(cboe, "get_text", lambda url, **kw: calls.append(url) or next(files))

    first = cboe.fetch_index("VIX", session=date(2026, 10, 9))
    assert first.index[-1] == pd.Timestamp("2026-10-08") and len(calls) == 1   # fetched, not re-asked
    monkeypatch.setattr(cboe, "_asked", set())  # the next build reads the cached copy, a session behind
    later = cboe.fetch_index("VIX", session=date(2026, 10, 9))
    assert later.iloc[-1] == 14.84 and len(calls) == 2
    # Up to date, or already asked this build: no further request.
    cboe.fetch_index("VIX", session=date(2026, 10, 9))
    monkeypatch.setattr(cboe, "_asked", set())
    cboe.fetch_index("VIX", session=date(2026, 10, 9))
    assert len(calls) == 2
