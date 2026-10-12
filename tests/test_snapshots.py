"""Snapshots record what the market quoted, solved honestly, and nothing else."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
import gzip
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import options as O
from market_recap.snapshots import expectations as X
from market_recap.snapshots import options as S
from market_recap.snapshots import store


# --- Black-76 ------------------------------------------------------------

@pytest.mark.parametrize("call", [True, False])
@pytest.mark.parametrize("strike", [80.0, 100.0, 125.0])
def test_implied_vol_recovers_the_vol_that_priced_it(call, strike):
    price = O.black76(100.0, strike, 0.25, 0.32, 0.99, call=call)
    assert O.implied_vol(price, 100.0, strike, 0.25, 0.99, call=call) == pytest.approx(0.32, abs=1e-5)


def test_implied_vol_refuses_a_price_below_intrinsic():
    # A call worth less than its discounted intrinsic value has no vol.
    assert O.implied_vol(4.0, 110.0, 100.0, 0.5, 1.0, call=True) is None


def test_put_call_parity_holds_in_the_pricer():
    forward, strike, years, vol, discount = 102.0, 100.0, 0.4, 0.25, 0.98
    call = O.black76(forward, strike, years, vol, discount, call=True)
    put = O.black76(forward, strike, years, vol, discount, call=False)
    assert call - put == pytest.approx(discount * (forward - strike))


@pytest.mark.parametrize("bid,ask,expected", [
    (1.0, 1.2, 1.1),
    (0.0, 0.1, None),          # one-sided
    (1.2, 1.0, None),          # crossed
    (0.1, 1.0, None),          # spread wider than half the mid
    (None, 1.0, None),
    (float("nan"), 1.0, None),
])
def test_mid_quote(bid, ask, expected):
    assert O.mid_quote(bid, ask) == (pytest.approx(expected) if expected else None)


# --- Expiry selection -----------------------------------------------------

def test_select_expiries_takes_the_nearest_and_brackets_each_target():
    today = date(2026, 9, 26)
    listed = ["2026-09-28", "2026-09-30", "2026-10-02", "2026-10-16", "2026-10-30",
              "2026-11-20", "2026-12-18", "2027-01-15"]
    chosen = O.select_expiries(listed, today, min_days=3, targets=[30, 60])
    # 09-28 is inside min_days; 10-16 (20d) and 10-30 (34d) bracket 30;
    # 11-20 (55d) and 12-18 (83d) bracket 60.
    assert chosen == ["2026-09-30", "2026-10-16", "2026-10-30", "2026-11-20", "2026-12-18"]


def test_select_expiries_with_nothing_far_enough_out():
    assert O.select_expiries(["2026-09-28"], date(2026, 9, 27), min_days=3, targets=[30]) == []


# --- Chain summary --------------------------------------------------------

def _chain(forward, years, discount, vol_of, strikes, spread=0.02):
    calls, puts = [], []
    for k in strikes:
        vol = vol_of(k)
        c = O.black76(forward, k, years, vol, discount, call=True)
        p = O.black76(forward, k, years, vol, discount, call=False)
        calls.append({"strike": k, "bid": c * (1 - spread), "ask": c * (1 + spread), "openInterest": 10, "volume": 1})
        puts.append({"strike": k, "bid": p * (1 - spread), "ask": p * (1 + spread), "openInterest": 20, "volume": 2})
    return calls, puts


def test_summary_recovers_a_flat_surface():
    today, expiry = date(2026, 9, 26), date(2026, 10, 26)
    years = 30 / O.CALENDAR_DAYS_PER_YEAR
    rate = 0.04
    discount = math.exp(-rate * years)
    calls, puts = _chain(101.0, years, discount, lambda k: 0.2, [float(k) for k in range(70, 131)])
    row = O.summarize_expiry(calls, puts, spot=100.0, expiry=expiry, today=today, rate=rate)
    assert row["forward"] == pytest.approx(101.0, abs=1e-6)
    assert row["atm_iv"] == pytest.approx(0.2, abs=1e-3)
    assert row["put_25d_iv"] == pytest.approx(0.2, abs=2e-3)
    assert row["call_25d_iv"] == pytest.approx(0.2, abs=2e-3)
    assert row["call_oi"] == 610 and row["put_volume"] == 122


def test_summary_sees_put_skew():
    today, expiry = date(2026, 9, 26), date(2026, 11, 25)
    years = 60 / O.CALENDAR_DAYS_PER_YEAR
    discount = math.exp(-0.04 * years)
    skew = lambda k: 0.2 + 0.4 * max(0.0, (100.0 - k) / 100.0)  # noqa: E731
    calls, puts = _chain(100.0, years, discount, skew, [float(k) for k in range(60, 141)])
    row = O.summarize_expiry(calls, puts, spot=100.0, expiry=expiry, today=today, rate=0.04)
    assert row["put_25d_iv"] > row["atm_iv"] + 0.01
    assert row["call_25d_iv"] == pytest.approx(0.2, abs=2e-3)


def test_summary_without_two_sided_quotes_is_empty_not_invented():
    calls = [{"strike": 100.0, "bid": 0.0, "ask": 1.0}]
    puts = [{"strike": 100.0, "bid": 0.0, "ask": 1.0}]
    row = O.summarize_expiry(calls, puts, spot=100.0, expiry=date(2026, 10, 30), today=date(2026, 9, 26), rate=0.04)
    assert row["atm_iv"] is None and row["forward"] is None
    assert row["note"] == "no strike quoted on both sides"


def test_same_day_expiry_is_recorded_without_a_vol():
    row = O.summarize_expiry([], [], spot=100.0, expiry=date(2026, 9, 26), today=date(2026, 9, 26), rate=0.04)
    assert row["atm_iv"] is None and row["note"] == "expires today"


# --- Universe ---------------------------------------------------------------

def test_universe_order_and_monitor_cap():
    settings = {"fixed": ["SPY", "AAPL"], "include_watchlist": True, "monitor_max": 2, "monitor_earnings_days": 30}
    watchlist = [{"ticker": "TSM"}, {"ticker": "aapl"}]
    rows = [
        {"ticker": "AAA", "candidate": True, "peer_excess_pct": -30.0, "earnings_date": None},
        {"ticker": "BBB", "candidate": True, "peer_excess_pct": -5.0, "earnings_date": "2026-10-10"},
        {"ticker": "CCC", "candidate": True, "peer_excess_pct": -20.0, "earnings_date": None},
        {"ticker": "DDD", "candidate": False, "peer_excess_pct": -50.0, "earnings_date": None},
        {"ticker": "SPY", "candidate": True, "peer_excess_pct": -99.0, "earnings_date": None},
    ]
    universe, left_out = S.build_universe(settings, watchlist, rows, date(2026, 9, 26))
    # Reporting soon beats a bigger lag; non-candidates and duplicates never enter.
    assert universe == ["SPY", "AAPL", "TSM", "BBB", "AAA"]
    assert left_out == {"monitor_over_limit": ["CCC"]}


def test_names_reporting_soon_come_before_monitor_candidates():
    settings = {"fixed": ["SPY"], "monitor_max": 1, "report_days": 3, "report_max": 2}
    reporters = [
        {"symbol": "MU", "date": "2026-09-30"},     # today, after the close
        {"symbol": "NKE", "date": "2026-10-01"},
        {"symbol": "SPY", "date": "2026-09-30"},    # already in
        {"symbol": "LATE", "date": "2026-10-09"},   # beyond report_days
        {"symbol": "PAST", "date": "2026-09-29"},
        {"symbol": "EXTRA", "date": "2026-10-02"},  # over report_max
    ]
    rows = [{"ticker": "AAA", "candidate": True, "peer_excess_pct": -30.0, "earnings_date": None}]
    universe, left_out = S.build_universe(settings, [], rows, date(2026, 9, 30), reporters)
    assert universe == ["SPY", "MU", "NKE", "AAA"]
    assert left_out["reporters_over_limit"] == ["EXTRA"]


def test_universe_without_a_published_monitor():
    universe, left_out = S.build_universe({"fixed": ["SPY"], "monitor_max": 5}, [], None, date(2026, 9, 26))
    assert universe == ["SPY"] and left_out == {}


# --- Window -------------------------------------------------------------------

@pytest.mark.parametrize("utc,inside", [
    (datetime(2026, 9, 28, 19, 25, tzinfo=timezone.utc), True),    # 15:25 EDT Monday
    (datetime(2026, 9, 28, 20, 25, tzinfo=timezone.utc), False),   # 16:25 EDT
    (datetime(2026, 12, 7, 20, 25, tzinfo=timezone.utc), True),    # 15:25 EST
    (datetime(2026, 12, 7, 19, 25, tzinfo=timezone.utc), False),   # 14:25 EST
    (datetime(2026, 9, 26, 19, 25, tzinfo=timezone.utc), False),   # Saturday
])
def test_window_follows_new_york_wall_clock(utc, inside):
    assert store.in_window(utc, ["15:10", "16:00"]) is inside


def test_configured_window_takes_the_late_starts_github_gives():
    """Every scheduled run in the first week started 18:56-20:27 New York."""
    window = S.load_config()["snapshots"]["options"]["window"]
    assert store.in_window(datetime(2026, 9, 29, 23, 39, tzinfo=timezone.utc), window)       # 19:39 EDT
    assert not store.in_window(datetime(2026, 9, 30, 4, 30, tzinfo=timezone.utc), window)    # 00:30 next day


def test_second_options_run_skips_a_sufficient_same_day_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "load_config", lambda: {"snapshots": {"options": {
        "window": ["15:10", "16:00"], "fixed": ["SPY", "QQQ"]}}})
    folder = tmp_path / "options" / "2026"
    folder.mkdir(parents=True)
    (folder / "2026-09-28-meta.json").write_text('{"underlyings_ok": 2, "usable_underlyings": 2}')
    result = S.run(root=tmp_path, now=datetime(2026, 9, 28, 19, 30, tzinfo=timezone.utc))
    assert result["status"] == "skipped" and "already has 2" in result["reason"]


# --- Futures symbols ----------------------------------------------------------

def test_fed_funds_symbols_start_this_month_and_roll_the_year():
    symbols = X.fed_funds_symbols(date(2026, 11, 3), 4)
    assert symbols == [("ZQX26.CBT", "2026-11"), ("ZQZ26.CBT", "2026-12"),
                       ("ZQF27.CBT", "2027-01"), ("ZQG27.CBT", "2027-02")]


@pytest.mark.parametrize("today,first", [
    (date(2026, 9, 26), ("SR3U26.CME", "2026-09")),
    (date(2026, 12, 1), ("SR3Z26.CME", "2026-12")),
    (date(2027, 2, 10), ("SR3Z26.CME", "2026-12")),
    (date(2027, 3, 1), ("SR3H27.CME", "2027-03")),
])
def test_sofr_symbols_start_at_the_quarter_in_progress(today, first):
    symbols = X.sofr_symbols(today, 3)
    assert symbols[0] == first and len(symbols) == 3


def test_sofr_symbols_step_by_quarter():
    assert [s for s, _ in X.sofr_symbols(date(2026, 9, 26), 3)] == ["SR3U26.CME", "SR3Z26.CME", "SR3H27.CME"]


# --- Row normalisation ----------------------------------------------------------

def test_kalshi_rows_keep_quotes_as_numbers():
    events = [{"event_ticker": "KXFED-26OCT", "title": "Fed rate", "markets": [{
        "ticker": "KXFED-26OCT-T4.00", "yes_sub_title": "Above 4.00%", "close_time": "2026-10-28T17:55:00Z",
        "last_price_dollars": "0.6300", "yes_bid_dollars": "0.6200", "yes_ask_dollars": "0.6400",
        "open_interest_fp": "33388.18", "volume_fp": "66017.76", "strike_type": "greater", "floor_strike": 4,
    }]}]
    [row] = X.kalshi_rows("t", "KXFED", events)
    assert row["price"] == 0.63 and row["bid"] == 0.62 and row["open_interest"] == pytest.approx(33388.18)
    assert row["label"] == "Above 4.00%" and row["detail"]["floor_strike"] == 4


def test_polymarket_rows_read_the_yes_price_and_skip_closed_markets():
    events = [{"slug": "cuts-2026", "markets": [
        {"id": "1", "groupItemTitle": "0 (0 bps)", "outcomes": '["Yes", "No"]', "outcomePrices": '["0.97", "0.03"]',
         "bestBid": 0.967, "bestAsk": 0.97, "closed": False},
        {"id": "2", "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]', "closed": True},
    ]}]
    [row] = X.polymarket_rows("t", "fed", events)
    assert row["price"] == 0.97 and row["contract"] == "1"


def test_yahoo_futures_row():
    payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 96.11, "regularMarketTime": 1790366400,
                                               "chartPreviousClose": 96.1}}]}}
    row = X.yahoo_futures_row("t", "fed_funds", "ZQV26.CBT", "2026-10", payload)
    assert row["price"] == 96.11 and row["quote_time"].startswith("2026-09-25")


# --- Writers --------------------------------------------------------------------

def test_compressed_csv_is_byte_stable(tmp_path):
    rows = [{"a": 1.5, "b": None, "c": {"x": 1}}]
    first, second = tmp_path / "1.csv.gz", tmp_path / "2.csv.gz"
    store.write_csv(first, rows, ["a", "b", "c"], compress=True)
    store.write_csv(second, rows, ["a", "b", "c"], compress=True)
    assert first.read_bytes() == second.read_bytes()
    [parsed] = list(csv.DictReader(gzip.decompress(first.read_bytes()).decode().splitlines()))
    assert parsed == {"a": "1.5", "b": "", "c": '{"x": 1}'}


def test_consensus_second_run_keeps_what_the_first_recorded(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    import csv
    import gzip
    from market_recap.snapshots import consensus
    trend = lambda eps: {"0y": {"eps": eps, "end": "2026-12-31"}}  # noqa: E731
    answers = [{"A": trend(1.0), "B": trend(2.0)}, {"B": trend(2.5), "C": trend(3.0)}]
    monkeypatch.setattr(consensus.estimates, "fetch_trends", lambda symbols, use_cache=False: (answers.pop(0), {}))
    now = datetime(2026, 10, 1, 23, 50, tzinfo=timezone.utc)                  # a Thursday evening in New York
    universe = ["A", "B", "C", "D", "E"]
    first = consensus.run(root=tmp_path, now=now, symbols=universe)
    second = consensus.run(root=tmp_path, now=now, symbols=universe)
    assert first["companies"] == 2 and second["companies"] == 3 and second["kept_from_earlier"] == 1
    path = next(tmp_path.rglob("*.csv.gz"))
    with gzip.open(path, "rt") as handle:
        eps = {r["symbol"]: r["eps"] for r in csv.DictReader(handle)}
    assert eps == {"A": "1.0", "B": "2.5", "C": "3.0"}                       # B refreshed, A kept


def test_europe_snapshot_records_multiples_and_consensus_and_keeps_an_earlier_row(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    import csv
    import gzip
    from market_recap.snapshots import europe

    multiples = [{"HSBA.L": {"forward_pe": 9.9, "trailing_pe": 11.0, "currency": "GBp", "price": 1000.0, "market_cap": 1.5e11}},
                 {"RMS.PA": {"forward_pe": 26.0, "currency": "EUR", "price": 1283.0}}]
    trends = [{"HSBA.L": {"0y": {"eps": 1.1, "end": "2026-12-31", "year_ago_eps": 1.0, "analysts": 20.0}, "+1y": {"eps": 1.2}}}, {}]
    monkeypatch.setattr(europe.source, "fetch_multiples", lambda symbols, use_cache=False: (multiples.pop(0), {}))
    monkeypatch.setattr(europe.estimates, "fetch_trends", lambda symbols, use_cache=False: (trends.pop(0), {}))
    now = datetime(2026, 10, 1, 23, 58, tzinfo=timezone.utc)                      # a Thursday evening in New York
    universe = ["HSBA.L", "RMS.PA", "X.L"]
    first = europe.run(root=tmp_path, now=now, symbols=universe)
    second = europe.run(root=tmp_path, now=now, symbols=universe)
    assert first["companies"] == 1 and second["companies"] == 2 and second["kept_from_earlier"] == 1
    path = next(tmp_path.rglob("*.csv.gz"))
    with gzip.open(path, "rt") as handle:
        rows = {r["symbol"]: r for r in csv.DictReader(handle)}
    assert rows["HSBA.L"]["forward_pe"] == "9.9" and rows["HSBA.L"]["eps_0y"] == "1.1" and rows["HSBA.L"]["eps_1y"] == "1.2"
    assert rows["RMS.PA"]["forward_pe"] == "26.0" and rows["RMS.PA"]["eps_0y"] == ""                # no consensus: blank, not zero
    assert europe.row_for("t", "Z", None, None) is None
    assert europe.run(root=tmp_path, now=datetime(2026, 10, 3, 23, 58, tzinfo=timezone.utc), symbols=universe)["status"] == "skipped"   # a Saturday
