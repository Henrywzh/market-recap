"""EVENTS: read-through, index impact and the consensus quarter check."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from market_recap.compute import events as E


def test_co_move_is_the_regression_slope_on_report_sessions_only():
    leader = [10.0, -5.0, 8.0, -4.0, None]
    follower = [5.0, -2.5, 4.0, 1.0, 3.0]          # the last pair is dropped: no leader move
    stats = E.co_move(leader, follower, min_reports=4)
    assert stats["n"] == 4
    assert stats["beta"] == round((50 + 12.5 + 32 - 4) / (100 + 25 + 64 + 16), 2)
    assert stats["hit"] == 0.75
    assert E.co_move(leader[:3], follower[:3], min_reports=4) is None


def test_candidates_drop_the_name_itself_and_its_other_share_class():
    rng = np.random.default_rng(0)
    base = rng.normal(size=300)
    frame = pd.DataFrame({
        "GOOGL": base, "GOOG": base + rng.normal(scale=0.01, size=300),
        "META": base + rng.normal(scale=0.5, size=300), "XOM": rng.normal(size=300),
    })
    picks = E.candidates(frame.corr(), "GOOGL", count=5, same_issuer={"GOOG"})
    assert [p[0] for p in picks] == ["META"]                                   # XOM: no tie and no correlation
    assert picks[0][2].startswith("trades with it")


def test_candidates_need_a_link_or_a_strong_correlation():
    corr = pd.DataFrame({"AAPL": [1.0, 0.28, 0.20, 0.50], "GDDY": [0.28, 1, 0, 0], "DELL": [0.20, 0, 1, 0],
                         "MSFT": [0.50, 0, 0, 1]}, index=["AAPL", "GDDY", "DELL", "MSFT"])
    picks = E.candidates(corr, "AAPL", count=5, same_issuer=set(), linked={"DELL": "same industry (Hardware)"})
    assert [(p[0], p[2]) for p in picks] == [("MSFT", "trades with it (corr 0.50)"), ("DELL", "same industry (Hardware)")]


def test_co_move_reports_the_betas_t_statistic():
    lead = [2.0, -3.0, 1.5, -1.0, 4.0, -2.5, 1.0, -2.0]
    tight = E.co_move(lead, [x * 0.5 + 0.05 for x in lead], min_reports=4)
    noisy = E.co_move(lead, [0.5, 0.4, -0.9, 0.7, -0.3, 0.2, -0.6, 0.1], min_reports=4)
    assert tight["beta"] == pytest.approx(0.5, abs=0.02) and tight["t"] > 10
    assert abs(noisy["t"]) < 1.5


def test_daily_excess_keeps_a_missing_print_missing():
    idx = pd.bdate_range("2026-01-05", periods=4)
    closes = pd.DataFrame({"A": [100.0, np.nan, 110.0, 121.0]}, index=idx)
    index_close = pd.Series([100.0, 100.0, 100.0, 110.0], index=idx)
    out = E.daily_excess(closes, index_close)["A"]
    assert pd.isna(out.iloc[1]) and pd.isna(out.iloc[2])      # no one-day move across the gap
    assert round(out.iloc[3], 6) == 0.0                        # +10% against +10%


def test_index_impact_is_weight_times_move():
    out = E.index_impact({"SPX": 1.832, "NDX": 5.087}, 9.06)
    assert out["NDX"]["points_pct"] == 0.46 and out["SPX"]["points_pct"] == 0.17
    assert E.index_impact({"SPX": 1.0}, None) == {}


def test_yahoo_consensus_is_used_only_for_the_calendar_quarter():
    event = {"fiscal_quarter": "Aug/2026", "eps_forecast": 31.24, "estimates": 10, "last_year_eps": 2.86}
    trend = {"0q": {"end": "2026-08-31", "eps": 31.7, "eps_30d": 31.0, "low": 28.0, "high": 37.4,
                    "revenue": 51.35e9, "revenue_year_ago": 11.3e9, "up_30d": 3, "down_30d": 1}}
    out = E.consensus(trend, event)
    assert out["source"] == "nasdaq + yahoo" and out["revenue"] == 51.35e9
    assert out["eps"] == 31.24 and out["eps_change_30d_pct"] == round(100 * (31.7 / 31.0 - 1), 2)
    rolled = {"0q": {**trend["0q"], "end": "2026-11-30"}}         # Yahoo already on the next quarter
    out = E.consensus(rolled, event)
    assert out["source"] == "nasdaq" and "revenue" not in out
    assert out["eps_growth_pct"] == round(100 * (31.24 / 2.86 - 1), 1)


def test_pre_event_snapshot_day_and_reaction_session():
    assert E.pre_event_day(date(2026, 9, 30), "amc") == date(2026, 9, 30)
    assert E.pre_event_day(date(2026, 10, 5), "bmo") == date(2026, 10, 2)    # Monday -> Friday
    sessions = [date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2)]
    assert E.reaction_session(date(2026, 9, 30), "amc", sessions) == date(2026, 10, 1)
    assert E.reaction_session(date(2026, 9, 30), "bmo", sessions) == date(2026, 9, 30)


def test_setup_reads_the_run_in_against_the_sector():
    idx = pd.bdate_range("2025-01-01", periods=300)
    close = pd.Series(np.linspace(100, 130, 300), index=idx)
    sector = pd.Series(np.linspace(100, 100, 300), index=idx)
    out = E.setup(close, sector)
    assert out["from_high_pct"] == 0.0 and out["above_50d"] is True
    assert out["vs_sector_20d"] == out["ret_20d"]


def test_outcome_compares_the_move_with_the_implied_move_the_afternoon_before():
    from market_recap.panels import events as panel

    entry = {"reactions": [{"date": "2026-09-29", "timing": "amc", "session": "2026-09-30",
                            "move_pct": -12.0, "excess_pct": -10.0, "index_pct": -2.0}]}
    event = {"symbol": "AAA", "date": "2026-09-29", "timing": "amc", "eps": 1.1, "eps_forecast": 1.0, "surprise_pct": 10.0}
    history = pd.DataFrame([
        {"underlying": "AAA", "day": "2026-09-29", "expiry": "2026-10-02", "days": 3, "straddle_pct": 8.0, "atm_iv": 0.9},
        {"underlying": "AAA", "day": "2026-09-28", "expiry": "2026-10-02", "days": 4, "straddle_pct": 9.0, "atm_iv": 0.9},
    ])
    excess = pd.DataFrame({"PEER": [-4.5]}, index=[pd.Timestamp("2026-09-30")])
    out = panel._outcome("AAA", event, entry, history, excess, {"with": [{"symbol": "PEER", "beta": 0.5}]})
    assert out["implied"]["snapshot_day"] == "2026-09-29" and out["implied"]["straddle_pct"] == 8.0
    assert out["vs_implied"] == 1.5
    assert out["peers"] == [{"symbol": "PEER", "beta": 0.5, "expected_pct": -5.0, "excess_pct": -4.5}]
    # No reaction on file for that report yet: no outcome card, rather than a blank one.
    assert panel._outcome("AAA", {**event, "date": "2026-09-30"}, entry, history, excess, {}) is None


# --- Guidance, report history, revisions -------------------------------------------
from market_recap.sources import releases as R


MICRON = ("Business Outlook The following table presents Micron's guidance for the fourth quarter of 2026: "
          "FQ4-26 GAAP (1) Outlook Non-GAAP (2) Outlook Revenue $50.0 billion ± $1.0 billion $50.0 billion ± $1.0 billion "
          "Gross margin Approximately 86% Approximately 86% Operating expenses Approximately $1.86 billion "
          "Diluted earnings per share $30.73 ± $1.00 $31.00 ± $1.00 Further information")


def test_outlook_reads_a_gaap_non_gaap_table_and_takes_non_gaap():
    o = R.outlook("Revenue $ 4,634 $ 2,708 $ 1,127 Gross margin 79 % 68 % " + MICRON)
    assert (o["revenue_low"], o["revenue_high"]) == (49e9, 51e9)
    assert (o["eps_low"], o["eps_high"]) == (30.0, 32.0)
    assert o["gross_margin_pct"] == 86.0 and "fourth quarter" in o["period"]


@pytest.mark.parametrize("text,key,expected", [
    ("For the third quarter of 2026, AMD expects revenue to be approximately $13 billion, plus or minus $300 million.",
     "revenue", (12.7e9, 13.3e9)),
    ("Outlook: Revenue is expected to be $108.0 billion, plus or minus 2%.", "revenue", (105.84e9, 110.16e9)),
    ("Outlook For the third quarter of 2026, the Company expects net revenue to be in the range of $2.290 billion to $2.320 billion",
     "revenue", (2.29e9, 2.32e9)),
    ("TI's third quarter outlook is for revenue in the range of $5.65 billion to $6.15 billion, and earnings per share between $2.23 and $2.57",
     "eps", (2.23, 2.57)),
])
def test_outlook_wordings(text, key, expected):
    o = R.outlook(text)
    assert (o[f"{key}_low"], o[f"{key}_high"]) == pytest.approx(expected)


def test_outlook_growth_guidance_and_none():
    o = R.outlook("Guidance for Q2 FY 2027: Total revenues are expected to grow between 30% and 34% in constant currency.")
    assert (o["revenue_growth_low"], o["revenue_growth_high"]) == (30.0, 34.0)
    assert R.outlook("We will discuss our outlook on the call.") is None


def test_guide_is_checked_against_the_companys_own_scale():
    outlook = {"revenue_low": 1.93e9, "revenue_high": 1.95e9, "eps_low": 6.30, "eps_high": 6.35, "quote": "q"}
    # A segment line against $6.4bn of quarterly revenue is dropped; the EPS stays.
    g = E.checked_guide(outlook, revenue_ref=6.4e9, eps_ref=5.9)
    assert "revenue_low" not in g and g["eps_horizon"] == "quarter"
    # A full-year range is kept and marked so.
    g = E.checked_guide({"revenue_low": 46.1e9, "revenue_high": 46.4e9}, revenue_ref=10.2e9, eps_ref=None)
    assert g["revenue_horizon"] == "year"
    assert E.checked_guide({"eps_low": 1.0, "eps_high": 1.2}, revenue_ref=None, eps_ref=40.0) is None


def test_report_history_drift_and_guide_follow_through():
    sessions = pd.bdate_range("2026-01-02", periods=60)
    close = pd.Series(range(100, 160), index=sessions, dtype=float)
    index = pd.Series(100.0, index=sessions)
    reactions = [{"date": "2026-02-26", "session": "2026-02-27", "timing": "amc", "move_pct": 5.0, "excess_pct": 4.0},
                 {"date": "2026-01-05", "session": "2026-01-06", "timing": "amc", "move_pct": -3.0, "excess_pct": -3.5}]
    calendar = {"2026-02-26": {"eps": 1.1, "eps_forecast": 1.0, "surprise_pct": 10.0, "fiscal_quarter": "Jan/2026"},
                "2026-01-05": {"eps": 0.9, "eps_forecast": 1.0, "surprise_pct": -10.0}}
    guides = {"2026-01-05": {"eps_low": 0.95, "eps_high": 1.05, "eps_horizon": "quarter"}}
    rows = E.report_history(reactions, calendar, guides, close, index)
    newest, older = rows
    at = sessions.get_loc(pd.Timestamp("2026-02-27"))
    assert newest["drift_5d"] == pytest.approx(round((close.iloc[at + 5] / close.iloc[at] - 1) * 100, 2))
    assert newest["drift_20d"] is None                           # not 20 sessions yet
    assert older["next_eps_vs_guide_pct"] == pytest.approx(10.0)  # 1.1 against a 1.00 midpoint
    summary = E.history_summary(rows)
    assert summary["beats"] == 1 and summary["measured"] == 2 and summary["beat_own_guide"] == 1


def test_against_guide_places_the_consensus_in_the_range():
    guide = {"eps_low": 30.0, "eps_high": 32.0, "eps_horizon": "quarter",
             "revenue_low": 49e9, "revenue_high": 51e9, "revenue_horizon": "quarter"}
    out = E.against_guide(guide, {"eps": 31.35, "revenue": 51.47e9})
    assert out["eps"]["position"] == "inside" and out["eps"]["vs_mid_pct"] == pytest.approx(1.1)
    assert out["revenue"]["position"] == "above"
    assert E.against_guide({"eps_low": 100.0, "eps_high": 110.0, "eps_horizon": "year"}, {"eps": 31.0}) is None


def test_revision_table_changes_and_spread():
    trend = {"0q": {"eps": 11.0, "eps_7d": 10.0, "eps_30d": 10.0, "eps_60d": None, "eps_90d": 8.0,
                    "low": 10.0, "high": 12.0, "end": "2026-12-31", "up_30d": 3, "down_30d": 1, "analysts": 20}}
    row = E.revision_table(trend)[0]
    assert row["changes"] == {"7d": 10.0, "30d": 10.0, "60d": None, "90d": 37.5}
    assert row["spread_pct"] == pytest.approx(18.2)


def test_a_straddle_running_weeks_past_the_report_is_not_its_implied_move():
    from market_recap.panels import events as P

    rows = pd.DataFrame([{"expiry": "2026-10-30", "days": 30, "straddle_pct": 6.1, "atm_iv": 0.3}])
    assert P._event_implied(rows, date(2026, 10, 13)) is None
    rows = pd.DataFrame([{"expiry": "2026-10-16", "days": 16, "straddle_pct": 4.0, "atm_iv": 0.3}])
    assert P._event_implied(rows, date(2026, 10, 13))["straddle_pct"] == 4.0


def test_factset_insight_pdf_text_and_the_weekly_merge():
    from market_recap.panels import earnings as P
    from market_recap.sources import factset

    text = ("Valuation: Forward P/E Ratio is 19.2, Above the 10-Year Average (19.0)\n"
            "The forward 12-month P/E ratio for the S&P 500 is 19.2. This P/E ratio is below the 5-year average of 19.8 but above the\n"
            "10-year average of 19.0. ... The trailing 12-month P/E ratio is 25.8, which is above the 5-year average of 24.4.")
    got = factset.parse_insight_text(text)
    assert got == {"forward_12m_pe": 19.2, "forward_12m_pe_5y_avg": 19.8, "forward_12m_pe_10y_avg": 19.0, "trailing_12m_pe": 25.8}
    assert factset.parse_insight_text("no valuation here") is None
    blog = [{"report_date": "2026-08-07", "forward_12m_pe": 20.0, "forward_12m_pe_10y_avg": 19.0},
            {"report_date": "2026-07-31", "forward_12m_pe": 19.6, "forward_12m_pe_10y_avg": 19.0}]
    pdf = [{"report_date": "2026-08-06", **got}, {"report_date": "2026-09-25", **got}]
    merged = P._forward_pe(blog, pdf)
    # The PDF of 08-06 and the blog of 08-07 are one week: the PDF's is kept.
    assert [p["date"] for p in merged] == ["2026-07-31", "2026-08-06", "2026-09-25"]
    assert merged[-1]["five_year_average"] == 19.8


def test_consensus_snapshot_rows():
    from market_recap.snapshots import consensus as C

    trend = {"0q": {"end": "2026-12-31", "eps": 1.5, "low": 1.4, "high": 1.6, "analysts": 20},
             "+1y": {"end": "2027-12-31", "eps": 7.0}, "0y": {"eps": None}}
    rows = C.rows_for("2026-10-01T23:50:00Z", "AAA", trend)
    assert [(r["period"], r["eps"]) for r in rows] == [("0q", 1.5), ("+1y", 7.0)]
    assert set(rows[0]) == set(C.COLUMNS)


def test_big_moves_are_large_against_the_names_own_volatility():
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2025-01-01", periods=200)
    excess = pd.Series(rng.normal(scale=0.5, size=200), index=days)   # 2.5 sigma is under the 2% floor: only the spikes count
    excess.iloc[150] = 6.0
    excess.iloc[160] = -5.5
    excess.iloc[170] = 6.0                                   # a report session: skipped
    out = E.big_moves(excess, since="2025-03-01", skip={days[170].strftime("%Y-%m-%d")})
    assert [m["date"] for m in out] == [days[150].strftime("%Y-%m-%d"), days[160].strftime("%Y-%m-%d")]
    assert out[0]["z"] > 2.5 and out[1]["excess_pct"] == -5.5
    calm = pd.Series(rng.normal(scale=0.3, size=200), index=days)
    calm.iloc[150] = 1.5                                     # five sigmas but under the 2% floor
    assert E.big_moves(calm, since="2025-03-01", skip=set()) == []


def test_headlines_that_name_and_explain_the_move_rank_first():
    start, end = 1_000_000.0, 1_100_000.0
    rows = [
        {"datetime": 1_050_000, "headline": "Stocks making the biggest moves midday: Micron, Nike", "source": "CNBC", "url": "a"},
        {"datetime": 1_050_100, "headline": "Why Micron Stock Soared Today", "source": "Yahoo", "url": "b"},
        {"datetime": 1_050_200, "headline": "Micron raises outlook on AI memory demand", "source": "Reuters", "url": "c"},
        {"datetime": 1_200_000, "headline": "Micron shares slide after hours", "source": "Reuters", "url": "d"},   # after the close
        {"datetime": 1_050_300, "headline": "Fed minutes due Wednesday", "source": "Reuters", "url": "e"},
    ]
    out = E.rank_headlines(rows, "MU", "Micron Technology Inc", start, end)
    assert sorted(h["url"] for h in out) == ["b", "c"]                  # the roundup, the after-close story and the unrelated one left out


def test_move_reasons_collect_what_happened_that_day():
    timeline = [{"kind": "rating", "date": "2026-03-10", "firm": "Citi", "action": "up", "to": "Buy", "target": 150, "prior_target": 120},
                {"kind": "filing", "date": "2026-03-09", "labels": ["material agreement"], "url": "u"},
                {"kind": "earnings", "date": "2026-03-10"}]
    out = E.move_reasons("2026-03-10", timeline, {"LRCX": ["2026-03-10"], "AMAT": ["2026-02-01"]},
                         {"2026-03-10": ["TSMC monthly revenue, y/y"]})
    assert [r["kind"] for r in out] == ["rating", "filing", "peer", "data"]
    assert out[0]["text"] == "Citi: upgrade to Buy, target 120 → 150" and out[2]["symbol"] == "LRCX"


def test_announced_events_need_an_event_phrase_and_a_date_ahead():
    import calendar
    import time
    ts = lambda d: calendar.timegm(time.strptime(d + " 15", "%Y-%m-%d %H"))  # noqa: E731
    rows = [
        {"datetime": ts("2026-09-20"), "headline": "Micron to host Investor Day on November 18, 2026", "summary": "", "source": "BW", "url": "u1"},
        {"datetime": ts("2026-09-22"), "headline": "Micron's investor day in March 2025, a recap", "summary": "", "source": "x", "url": "u3"},
        {"datetime": ts("2026-09-23"), "headline": "Micron stock rises", "summary": "Micron will hold its annual shareholder meeting on January 15.", "source": "x", "url": "u4"},
        {"datetime": ts("2026-09-24"), "headline": "Samsung plans investor day on November 3", "summary": "", "source": "x", "url": "u5"},
    ]
    out = E.announced_events(rows, "MU", "Micron Technology Inc", date(2026, 10, 3))
    assert [(e["date"], e["kind"], e["url"]) for e in out] == [("2026-11-18", "investor day", "u1"),
                                                               ("2027-01-15", "shareholder meeting", "u4")]
    fda = [{"datetime": ts("2026-09-21"), "headline": "Vertex: FDA sets PDUFA target action date of Jan. 9", "summary": "", "source": "R", "url": "v"}]
    assert E.announced_events(fda, "VRTX", "Vertex Pharmaceuticals", date(2026, 10, 3))[0]["date"] == "2027-01-09"


def test_a_name_quoted_as_the_commentator_is_not_the_story():
    start, end = 0.0, 10.0
    rows = [{"datetime": 1, "headline": "AVGO Stock Jumps — JPMorgan Says Investors Should Be Aggressive Buyers", "source": "Yahoo", "url": "a"},
            {"datetime": 2, "headline": "JPMorgan CEO Sees Hyperscaler Spending Hitting $1 Trillion", "source": "Yahoo", "url": "b"},
            {"datetime": 3, "headline": "JPMorgan shares fall after trading revenue warning", "source": "Reuters", "url": "c"}]
    assert "a" not in [h["url"] for h in E.rank_headlines(rows, "JPM", "JPMorgan Chase & Co", start, end)]
    analyst = [{"datetime": 1, "headline": "JPMorgan analysts upgrade Nvidia to overweight", "source": "Reuters", "url": "d"}]
    assert E.rank_headlines(analyst, "JPM", "JPMorgan Chase & Co", start, end) == []


def test_each_name_is_asked_once_in_any_run_of_rotation_weekdays():
    from datetime import date, timedelta
    import numpy as np
    from market_recap.panels.events import rotation_due

    days = [d for d in (date(2026, 9, 1) + timedelta(n) for n in range(60)) if d.weekday() < 5]
    for symbol in ("AAPL", "MSFT", "NVDA", "BRK-B", "000660.KS"):
        due = [rotation_due(symbol, d, 3) for d in days]
        for i in range(len(days) - 2):
            assert sum(due[i:i + 3]) == 1, (symbol, days[i])     # a weekend does not skip a turn
    assert all(rotation_due("AAPL", d, 1) for d in days)
    shares = np.mean([[rotation_due(f"S{i}", d, 3) for i in range(300)] for d in days[:3]], axis=1)
    assert all(0.25 < s < 0.42 for s in shares)                   # about a third of names each night


def test_a_names_last_event_window_is_read_again_between_its_turns(tmp_path, monkeypatch):
    import gzip
    import json
    from datetime import date
    from market_recap import cache
    from market_recap.sources import finnhub

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    folder = tmp_path / finnhub.NAMESPACE
    folder.mkdir()
    write = lambda name, rows: (folder / name).write_bytes(gzip.compress(json.dumps(rows).encode()))  # noqa: E731
    write("AAPL-2026-08-20-2026-10-04.json.gz", [{"headline": "older"}])
    write("AAPL-2026-08-21-2026-10-05.json.gz", [{"headline": "newest"}])
    write("AAPL-2026-10-04-2026-10-07.json.gz", [{"headline": "a move window"}])
    write("AAPLX-2026-08-21-2026-10-05.json.gz", [{"headline": "another name"}])
    assert finnhub.recent_window("AAPL", date(2026, 10, 7), 45, max_age=10) == [{"headline": "newest"}]
    assert finnhub.recent_window("AAPL", date(2026, 10, 30), 45, max_age=10) is None
    assert finnhub.recent_window("MSFT", date(2026, 10, 7), 45, max_age=10) is None


INDEX_PAGE = """<table class="tableFile"><tr><td>1</td><td>Press release</td><td>a.htm</td>
<td>EX-99.1</td><td><a href="/Archives/a.htm">a.htm</a></td></tr></table>"""


def test_a_release_is_turned_into_text_once(monkeypatch, tmp_path):
    from market_recap import cache
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    asked = []
    monkeypatch.setattr(R.sec, "_get", lambda url, timeout: asked.append(url) or (INDEX_PAGE if "index" in url else "<p>Revenue is expected to be $5.0 billion.</p>"))
    parsed = []
    real = R._text
    monkeypatch.setattr(R, "_text", lambda html: parsed.append(html) or real(html))
    first = R._exhibit(320193, "0000320193-26-000001")
    again = R._exhibit(320193, "0000320193-26-000001")
    assert first == again == ("https://www.sec.gov/Archives/a.htm", "Revenue is expected to be $5.0 billion.")
    assert len(asked) == 2 and len(parsed) == 1


def test_a_release_past_the_budget_is_counted_as_waiting(monkeypatch, tmp_path):
    from market_recap import cache
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    block = {"form": ["8-K"], "items": ["2.02,9.01"], "filingDate": ["2026-10-01"], "accessionNumber": ["0000320193-26-000001"]}
    counts = {"waiting": 0}
    assert R.release_on(320193, "2026-10-01", block, fetch=False, counts=counts) is None
    assert counts["waiting"] == 1
