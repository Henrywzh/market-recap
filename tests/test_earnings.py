"""EARNINGS: calendarization, bottom-up revisions, the season, FactSet parsing."""

from datetime import date

import pytest

from market_recap.compute import earnings as E
from market_recap.sources import factset


def test_fiscal_periods_count_toward_the_calendar_period_holding_most_months():
    assert E.calendar_year("2026-12-31") == 2026
    assert E.calendar_year("2027-01-31") == 2026   # retailers
    assert E.calendar_year("2027-06-30") == 2026   # Microsoft-style, a tie goes back
    assert E.calendar_year("2027-07-31") == 2027
    assert E.calendar_quarter("2026-08-02") == (2026, 3)
    assert E.nasdaq_quarter("Aug/2026") == (2026, 3)
    assert E.nasdaq_quarter("n/a") is None
    # Off-cycle reporters start a season before its quarter ends; mid-November is still Q3.
    assert E.season_quarter(date(2026, 9, 24)) == (2026, 3)
    assert E.season_quarter(date(2026, 11, 15)) == (2026, 3)
    assert E.season_quarter(date(2026, 12, 20)) == (2026, 4)


def _trend(end, eps, then):
    return {"0y": {"end": end, "eps": eps, "eps_7d": eps, "eps_30d": then, "eps_60d": then, "eps_90d": then}}


def test_revisions_weight_by_shares_and_name_the_movers():
    companies = [
        {"symbol": "BIG", "sector": "Tech", "shares": 10.0, "trend": _trend("2026-12-31", 11.0, 10.0)},
        {"symbol": "SMALL", "sector": "Tech", "shares": 1.0, "trend": _trend("2026-12-31", 9.0, 10.0)},
        {"symbol": "JUNE", "sector": "Energy", "shares": 1.0, "trend": _trend("2027-06-30", 5.0, 5.0)},
        {"symbol": "NEXT", "sector": "Energy", "shares": 1.0, "trend": _trend("2027-12-31", 5.0, 4.0)},
    ]
    out = E.revisions(companies, ("year", 2026))
    assert out["companies"] == 3
    # (110 + 9 + 5) / (100 + 10 + 5) - 1
    assert out["windows"]["30d"]["pct"] == pytest.approx((124 / 115 - 1) * 100, abs=0.01)
    assert out["breadth_30d"] == {"up": 1, "down": 1, "unchanged": 1}
    assert out["movers_30d"]["up"][0]["symbol"] == "BIG"
    tech = next(s for s in out["sectors"] if s["sector"] == "Tech")
    assert tech["leader_30d"]["symbol"] == "BIG"


def test_season_counts_beats_and_growth_only_where_known():
    universe = {"A": {"sector": "Tech", "shares": 1.0}, "B": {"sector": "Tech", "shares": 1.0},
                "C": {"sector": "Energy", "shares": 1.0}}
    reports = [
        {"symbol": "A", "date": "2026-09-10", "eps": 1.1, "eps_forecast": 1.0, "surprise_pct": 10.0,
         "fiscal_quarter": "Aug/2026", "year_ago_eps": 1.0},
        {"symbol": "B", "date": "2026-09-11", "eps": 0.9, "eps_forecast": 1.0, "surprise_pct": -10.0,
         "fiscal_quarter": "Aug/2026", "year_ago_eps": None},
        # Another quarter, and a non-member: neither counts.
        {"symbol": "C", "date": "2026-09-12", "eps": 2.0, "eps_forecast": 1.0, "fiscal_quarter": "May/2026"},
        {"symbol": "Z", "date": "2026-09-12", "eps": 2.0, "eps_forecast": 1.0, "fiscal_quarter": "Aug/2026"},
    ]
    out = E.season(reports, universe, (2026, 3))
    assert (out["reported"], out["beat"], out["miss"]) == (2, 1, 1)
    assert out["beat_share"] == 50.0
    assert out["aggregate_surprise_pct"] == pytest.approx(0.0)
    assert out["growth_companies"] == 1 and out["growth_yoy_pct"] == pytest.approx(10.0)


def test_factset_parser_reads_revision_note_figures():
    text = ("Analysts Increasing EPS Estimates\nGiven concerns, have analysts lowered EPS estimates? "
            "The answer is no. The Q3 bottom-up EPS estimate (which is an aggregation) increased by 1.2% "
            "(to $89.69 from $88.64) from June 30 to August 31. During the past five years (20 quarters), "
            "the average decline in the bottom-up EPS estimate during the first two months of a quarter has "
            "been 1.7%. led by the Energy (+11.8%) sector. led by the Materials (-9.1%) sector. "
            "From June 30 through August 31, the CY 2026 bottom-up EPS estimate increased by 6.1% (to $361.38).")
    obs = factset.Parser.parse_summary_metrics(text, "2026-09-04", "2026Q3", source_url="https://x")
    assert obs.quarterly_eps_revision_pct == 1.2
    assert obs.annual_eps_revision_pct == 6.1
    narrative = factset.parse_article_narrative(text)
    assert narrative["typical"] == [{"years": 5, "window": "first two months", "value": -1.7}]
    assert factset.Parser.report_date_from_url("https://insight.factset.com/sp-500-earnings-season-update-august-7-2026") == "2026-08-07"


def test_factset_seed_is_committed_and_typed():
    rows = factset.load_seed()
    assert len(rows) >= 369
    assert rows[0]["report_date"] <= rows[-1]["report_date"]
    assert any(isinstance(r["forward_12m_pe"], float) for r in rows)


def test_factset_row_drops_an_implausible_pe_average():
    from market_recap.sources import factset

    row = factset._row({"report_date": "2025-10-10", "forward_12m_pe": "22.8", "forward_12m_pe_10y_avg": "39.0"})
    assert row["forward_12m_pe"] == 22.8
    assert row["forward_12m_pe_10y_avg"] is None


def test_factset_article_growth_is_the_current_figure_not_the_june_30_comparison():
    text = ("As of today, the S&P 500 is expected to report (year-over-year) earnings growth of 29.5%, compared to the "
            "estimated (year-over-year) earnings growth rate of 26.7% on June 30. In terms of revenues, the S&P 500 is "
            "expected to report (year-over-year) revenue growth of 12.3%, compared to the estimated (year-over-year) "
            "revenue growth rate of 10.9% on June 30.")
    obs = factset.Parser.parse_summary_metrics(text, "2026-10-02", "2026Q3", source_url="https://x")
    assert obs.blended_earnings_growth_yoy == 29.5
    assert obs.blended_revenue_growth_yoy == 12.3
    # Only the comparison in the text: nothing is stored rather than the old figure.
    only = factset.Parser.parse_summary_metrics(
        "compared to the estimated (year-over-year) earnings growth rate of 26.7% on June 30.", "2026-10-02", "2026Q3", source_url="https://x")
    assert only.blended_earnings_growth_yoy is None
    # An in-season article that states the rate directly still reads.
    older = factset.Parser.parse_summary_metrics(
        "the blended earnings growth rate for the index is 12.4% for the quarter", "2026-08-07", "2026Q2", source_url="https://x")
    assert older.blended_earnings_growth_yoy == 12.4


PDF_TEXT = """Key Metrics
  Earnings Growth: For Q3 2026, the estimated (year-over-year) earnings growth rate for the S&P 500 is 29.6%. If
  Earnings Revisions: On June 30, the estimated (year-over-year) earnings growth rate for the S&P 500 for Q3
  2026 was 26.7%. Four sectors are expected to report higher earnings today.
  Earnings Guidance: For Q3 2026, 44 S&P 500 companies have issued negative EPS guidance and 72 S&P 500
  companies have issued positive EPS guidance.
Of the 19 S&P 500 companies that have reported actual earnings for Q3 2026 through October 9, 84% have reported
actual EPS above the mean EPS estimate. In aggregate, actual earnings reported by these 19 companies have
exceeded estimated earnings by 4.9%.
As of today, the S&P 500 is expected to report (year-over-year) revenue growth of 12.4%, compared to 10.9% on June 30."""


def test_factset_pdf_season_figures_skip_the_june_30_comparison():
    got = factset.parse_insight_season(PDF_TEXT)
    assert got == {
        "reference_quarter": "2026Q3", "blended_earnings_growth_yoy": 29.6, "blended_revenue_growth_yoy": 12.4,
        "companies_reported": 19, "eps_beat_rate": 84.0, "eps_surprise_pct": 4.9,
        "negative_eps_guidance_count": 44, "positive_eps_guidance_count": 72,
    }
    assert factset.parse_insight_season("nothing about the quarter") == {}


def test_snapshot_takes_the_newer_pdf_quarter_figures_only_for_the_same_quarter():
    from market_recap.panels import earnings as P

    snapshot = {"report_date": "2026-10-02", "reference_quarter": "2026Q3", "source_url": "blog",
                "blended_earnings_growth_yoy": 29.5, "blended_revenue_growth_yoy": None, "eps_beat_rate": None, "eps_surprise_pct": None}
    pdf = {"report_date": "2026-10-09", "source_url": "pdf", **factset.parse_insight_season(PDF_TEXT)}
    got = P._with_pdf_season(snapshot, [pdf])
    assert got["blended_earnings_growth_yoy"] == 29.6 and got["eps_beat_rate"] == 84.0
    assert got["season_date"] == "2026-10-09" and got["positive_eps_guidance_count"] == 72
    assert got["report_date"] == "2026-10-02"                       # still the article's own date
    assert P._with_pdf_season(snapshot, [{**pdf, "report_date": "2026-09-25"}]) == snapshot   # older PDF: unchanged
    assert P._with_pdf_season(snapshot, [{**pdf, "reference_quarter": "2026Q4"}]) == snapshot  # another quarter: unchanged
    assert P._with_pdf_season(None, [pdf]) is None
