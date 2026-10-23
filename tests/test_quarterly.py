"""Quarterly statements from company facts: which figures are filed, which are
built from year-to-date filings, and the ratios read across the quarters."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_recap.compute import fundamentals as F
from market_recap.panels import financials as fin
from market_recap.sources import sec

REVENUE = "Revenues"
NET_INCOME = "NetIncomeLoss"
EPS = "EarningsPerShareDiluted"
OCF = "NetCashProvidedByUsedInOperatingActivities"
CASH = "CashAndCashEquivalentsAtCarryingValue"
EQUITY = "StockholdersEquity"
EBIT = "OperatingIncomeLoss"
PRETAX = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
TAX = "IncomeTaxExpenseBenefit"
DEBT = "LongTermDebtNoncurrent"


def _row(start, end, value, filed, form="10-Q", fp=None):
    row = {"end": end, "val": value, "filed": filed, "form": form}
    if start is not None:
        row["start"] = start
    if fp is not None:
        row["fp"] = fp
    return row


def _facts(entries):
    """entries: (tag, unit, row) triples, grouped into a companyfacts document."""
    gaap: dict = {}
    for tag, unit, row in entries:
        gaap.setdefault(tag, {"units": {}})["units"].setdefault(unit, []).append(row)
    return {"entityName": "Acme", "facts": {"us-gaap": gaap}}


def _usd(tag, *rows):
    return [(tag, "USD", row) for row in rows]


def _calendar_company():
    """Calendar-year filer: FY2024 and FY2025 10-Ks, 2025 and 2026 10-Qs."""
    entries = []
    # Revenue: FY2025 filed as 10-K; 9M and 3M quarters filed as 10-Q.
    entries += _usd(REVENUE,
                    _row("2024-01-01", "2024-12-31", 800.0, "2025-02-20", "10-K", "FY"),
                    _row("2025-01-01", "2025-12-31", 1000.0, "2026-02-20", "10-K", "FY"),
                    _row("2025-01-01", "2025-03-31", 200.0, "2025-05-01"),
                    _row("2025-04-01", "2025-06-30", 220.0, "2025-08-01"),
                    _row("2025-07-01", "2025-09-30", 280.0, "2025-11-05"),
                    _row("2025-01-01", "2025-09-30", 700.0, "2025-11-05"),
                    _row("2026-01-01", "2026-03-31", 240.0, "2026-05-05"),
                    _row("2026-04-01", "2026-06-30", 260.0, "2026-08-05"))
    # Net income: quarters filed; Q4 is the year less nine months.
    entries += _usd(NET_INCOME,
                    _row("2025-01-01", "2025-12-31", 150.0, "2026-02-20", "10-K", "FY"),
                    _row("2025-01-01", "2025-09-30", 105.0, "2025-11-05"),
                    _row("2025-07-01", "2025-09-30", 40.0, "2025-11-05"),
                    _row("2026-01-01", "2026-03-31", 36.0, "2026-05-05"))
    # Operating cash flow, filed year to date from Q2 onwards.
    entries += _usd(OCF,
                    _row("2025-01-01", "2025-12-31", 300.0, "2026-02-20", "10-K", "FY"),
                    _row("2025-01-01", "2025-03-31", 60.0, "2025-05-01"),
                    _row("2025-01-01", "2025-06-30", 130.0, "2025-08-01"),
                    _row("2025-01-01", "2025-09-30", 210.0, "2025-11-05"),
                    _row("2026-01-01", "2026-03-31", 30.0, "2026-05-05"),
                    _row("2026-01-01", "2026-06-30", 75.0, "2026-08-05"))
    # EPS: quarters as filed; Q4 = FY less the three quarters. Q2 2026 is only year to date.
    entries += [(EPS, "USD/shares", row) for row in (
                    _row("2025-01-01", "2025-12-31", 2.00, "2026-02-20", "10-K", "FY"),
                    _row("2025-01-01", "2025-03-31", 0.50, "2025-05-01"),
                    _row("2025-04-01", "2025-06-30", 0.55, "2025-08-01"),
                    _row("2025-07-01", "2025-09-30", 0.60, "2025-11-05"),
                    _row("2026-01-01", "2026-03-31", 0.60, "2026-05-05"),
                    _row("2026-01-01", "2026-06-30", 1.15, "2026-08-05"))]
    # Balance sheet, read at each quarter end (the June balance is dated two days early).
    entries += _usd(CASH,
                    _row(None, "2024-12-31", 100.0, "2025-02-20", "10-K", "FY"),
                    _row(None, "2025-12-31", 100.0, "2026-02-20", "10-K", "FY"),
                    _row(None, "2026-03-31", 110.0, "2026-05-05"),
                    _row(None, "2026-06-28", 120.0, "2026-08-05"))
    entries += _usd(EQUITY,
                    _row(None, "2024-12-31", 700.0, "2025-02-20", "10-K", "FY"),
                    _row(None, "2025-12-31", 800.0, "2026-02-20", "10-K", "FY"),
                    _row(None, "2026-03-31", 830.0, "2026-05-05"))
    # Annual-only lines for the return on invested capital.
    entries += _usd(EBIT,
                    _row("2024-01-01", "2024-12-31", 180.0, "2025-02-20", "10-K", "FY"),
                    _row("2025-01-01", "2025-12-31", 200.0, "2026-02-20", "10-K", "FY"))
    entries += _usd(PRETAX, _row("2025-01-01", "2025-12-31", 180.0, "2026-02-20", "10-K", "FY"))
    entries += _usd(TAX, _row("2025-01-01", "2025-12-31", 36.0, "2026-02-20", "10-K", "FY"))
    entries += _usd(DEBT,
                    _row(None, "2024-12-31", 300.0, "2025-02-20", "10-K", "FY"),
                    _row(None, "2025-12-31", 300.0, "2026-02-20", "10-K", "FY"))
    return _facts(entries)


def _by_label(rows):
    return {row["label"]: row for row in rows}


def test_three_month_filings_are_used_as_filed():
    rows = _by_label(sec.quarterly_statements(_calendar_company()))
    q1 = rows["FY2026 Q1"]
    assert q1["period_end"] == "2026-03-31" and q1["revenue"] == 240.0
    assert q1["revenue_derived"] is False and q1["revenue_filed"] == "2026-05-05"
    assert rows["FY2025 Q2"]["revenue"] == 220.0 and rows["FY2025 Q2"]["revenue_derived"] is False


def test_cash_flow_quarter_given_only_as_year_to_date_is_the_difference():
    rows = _by_label(sec.quarterly_statements(_calendar_company()))
    # Q2 2026 = six months (75) less the first quarter's three months (30).
    q2 = rows["FY2026 Q2"]
    assert q2["operating_cash_flow"] == 45.0 and q2["operating_cash_flow_derived"] is True
    assert q2["operating_cash_flow_filed"] == "2026-08-05"
    # Q3 2025 = nine months (210) less six months (130): the same rule, a quarter later.
    assert rows["FY2025 Q3"]["operating_cash_flow"] == 80.0
    assert rows["FY2025 Q3"]["operating_cash_flow_derived"] is True
    # A three-month figure filed as such is not derived.
    assert rows["FY2025 Q1"]["operating_cash_flow_derived"] is False


def test_fourth_quarter_is_the_year_less_nine_months():
    rows = _by_label(sec.quarterly_statements(_calendar_company()))
    q4 = rows["FY2025 Q4"]
    assert q4["period_end"] == "2025-12-31"
    assert q4["revenue"] == 300.0 and q4["revenue_derived"] is True
    assert q4["net_income"] == 45.0 and q4["net_income_derived"] is True
    assert q4["operating_cash_flow"] == 90.0 and q4["operating_cash_flow_derived"] is True


def test_eps_fourth_quarter_needs_all_three_quarters_filed():
    rows = _by_label(sec.quarterly_statements(_calendar_company()))
    q4 = rows["FY2025 Q4"]
    assert q4["eps_diluted"] == pytest.approx(2.00 - (0.50 + 0.55 + 0.60))
    assert q4["eps_diluted_derived"] is True
    # Year-to-date EPS is never differenced: Q2 2026 is blank, not 1.15 - 0.60.
    q2 = rows["FY2026 Q2"]
    assert q2["eps_diluted"] is None and q2["eps_diluted_derived"] is False
    # Without the second quarter filed, the fourth quarter cannot be built.
    facts = _calendar_company()
    eps_rows = facts["facts"]["us-gaap"][EPS]["units"]["USD/shares"]
    eps_rows[:] = [row for row in eps_rows if row["end"] != "2025-06-30"]
    assert _by_label(sec.quarterly_statements(facts))["FY2025 Q4"]["eps_diluted"] is None


def test_balance_item_is_read_at_the_quarter_end_within_a_few_days():
    rows = _by_label(sec.quarterly_statements(_calendar_company()))
    q2 = rows["FY2026 Q2"]
    assert q2["cash"] == 120.0 and q2["cash_derived"] is False
    assert q2["equity"] is None            # no June equity filed: blank, not carried


def test_year_over_year_growth_needs_the_same_quarter_four_back():
    rows = sec.quarterly_statements(_calendar_company())
    assert [r["label"] for r in rows] == ["FY2025 Q1", "FY2025 Q2", "FY2025 Q3", "FY2025 Q4",
                                          "FY2026 Q1", "FY2026 Q2"]
    growth = F.quarterly_ratio_table(rows)["revenue_growth"]
    assert growth[:4] == [None, None, None, None]        # no 2024 quarters to compare with
    assert growth[4] == pytest.approx(20.0)              # 240 against 200
    assert growth[5] == pytest.approx(100 * (260 / 220 - 1))


def test_annual_roic_is_nopat_over_average_invested_capital():
    rows = sec.annual_statements(_calendar_company())
    roic = F.ratio_table(rows)["roic"]
    # FY2025: NOPAT 200 x (1 - 36/180) = 160; capital 800 + 300 - 100 = 1000 and
    # 700 + 300 - 100 = 900 a year earlier; average 950.
    assert roic[-1] == pytest.approx(100 * 160 / 950)
    # FY2024 has no 2023 balance: its average is its own capital, with the 21% default rate.
    assert roic[0] == pytest.approx(100 * 180 * 0.79 / 900)


def test_nopat_tax_rate_is_clipped_and_defaults_to_21_percent():
    assert F.nopat(100.0, 5.0, -10.0) == pytest.approx(79.0)     # no profit before tax: 21%
    assert F.nopat(100.0, None, 50.0) == pytest.approx(79.0)     # no tax line: 21%
    assert F.nopat(100.0, 60.0, 100.0) == pytest.approx(50.0)    # rate capped at 50%
    assert F.nopat(None, 10.0, 100.0) is None


def test_ttm_returns_need_four_quarters_and_both_balances():
    def quarter(label, end, ni, equity, ebit=10.0, pretax=12.0, tax=2.4, cash=50.0, debt=100.0):
        return {"label": label, "period_end": end, "net_income": ni, "equity": equity, "ebit": ebit,
                "pretax_income": pretax, "taxes": tax, "cash": cash, "total_debt": debt,
                "debt_current": None, "short_term_investments": None}
    rows = [
        quarter("FY2025 Q1", "2025-03-31", 10.0, 500.0),
        quarter("FY2025 Q2", "2025-06-30", 10.0, 510.0),
        quarter("FY2025 Q3", "2025-09-30", 10.0, 520.0),
        quarter("FY2025 Q4", "2025-12-31", 10.0, 530.0),
        quarter("FY2026 Q1", "2026-03-31", 20.0, 600.0),
    ]
    table = F.quarterly_ratio_table(rows)
    assert table["roe"][:4] == [None, None, None, None]         # three quarters back: no TTM
    # TTM net income is Q2 2025 to Q1 2026: 10+10+10+20 = 50, over the average of
    # the equity now (600) and a year ago (500).
    assert table["roe"][4] == pytest.approx(100 * 50.0 / 550.0)
    # Invested capital: 600 + 100 - 50 = 650 now and 550 a year ago, average 600.
    # TTM EBIT 40, taxes 9.6 on pre-tax 48: a 20% rate, so NOPAT 32.
    assert table["roic"][4] == pytest.approx(100 * (10.0 + 10.0 + 10.0 + 10.0) * 0.8 / 600.0)


def test_quarters_payload_marks_derived_figures_and_keeps_blanks_blank():
    rows = sec.quarterly_statements(_calendar_company())
    extracted = {"entity_name": "Acme", "cik": 1, "source_ciks": [1], "source_url": "x", "rows": [],
                 "quarterly_rows": rows}
    payload = fin._payload("ACME", extracted, {})
    quarters = payload["quarters"]
    labels = [c["label"] for c in quarters["columns"]]
    assert labels[-1] == "FY2026 Q2" and quarters["columns"][-1]["filed"] == "2026-08-05"
    index = labels.index("FY2025 Q4")
    assert quarters["values"]["revenue"][index] == 300.0
    assert quarters["derived"]["revenue"][index] is True
    assert quarters["derived"]["operating_cash_flow"][labels.index("FY2026 Q2")] is True
    assert quarters["values"]["eps_diluted"][labels.index("FY2026 Q2")] is None
    assert set(quarters["derived"]) == {item.key for item in sec.LINE_ITEMS}
    assert len(quarters["ratios"]["revenue_growth"]) == len(labels)
    assert "roic" in payload["ratios"] and payload["ratios"]["roic"] == []   # no annual rows in this payload


def test_fiscal_quarters_on_a_52_53_week_year_with_ends_a_few_days_off():
    """A 52-week year ending 27 December: quarter ends fall on the 27th or 28th."""
    entries = _usd(REVENUE,
                   _row("2024-12-29", "2025-12-27", 1000.0, "2026-02-19", "10-K", "FY"),
                   _row("2024-12-29", "2025-03-28", 230.0, "2025-05-01"),
                   _row("2025-03-29", "2025-06-27", 240.0, "2025-08-01"),
                   _row("2025-06-28", "2025-09-27", 250.0, "2025-11-04"),
                   _row("2024-12-29", "2025-09-27", 720.0, "2025-11-04"),
                   _row("2025-12-28", "2026-03-28", 260.0, "2026-05-06"))
    # Net income's year ends a day later than revenue's: one fourth quarter, not two.
    entries += _usd(NET_INCOME,
                    _row("2024-12-29", "2025-12-28", 150.0, "2026-02-19", "10-K", "FY"),
                    _row("2024-12-29", "2025-09-27", 105.0, "2025-11-04"))
    entries += _usd(CASH, _row(None, "2026-03-31", 110.0, "2026-05-06"))
    rows = sec.quarterly_statements(_facts(entries))
    assert [r["label"] for r in rows] == ["FY2025 Q1", "FY2025 Q2", "FY2025 Q3", "FY2025 Q4", "FY2026 Q1"]
    q4 = rows[3]
    assert q4["period_end"] == "2025-12-27"
    assert q4["revenue"] == pytest.approx(280.0) and q4["revenue_derived"] is True    # 1000 - 720
    assert q4["net_income"] == pytest.approx(45.0) and q4["net_income_derived"] is True
    assert rows[4]["period_end"] == "2026-03-28" and rows[4]["cash"] == 110.0


def test_a_fiscal_year_with_no_quarter_data_is_left_out():
    rows = sec.quarterly_statements(_facts(_usd(REVENUE, _row("2024-01-01", "2024-12-31", 800.0, "2025-02-20", "10-K", "FY"))))
    # Only a year is reported: its fourth quarter needs nine months, which are missing.
    assert rows == []


def test_a_stray_revenue_quarter_off_its_neighbours_scale_is_blanked():
    rows = [{"revenue": v, "revenue_derived": True} for v in (25e9, 6.4e9, 23e9, 24e9, 26e9, -1e9, 25e9)]
    sec._drop_stray_revenue(rows)
    assert [r["revenue"] for r in rows] == [25e9, None, 23e9, 24e9, 26e9, None, 25e9]
    assert rows[1]["revenue_derived"] is False


def test_a_year_to_date_difference_needs_the_same_tag_on_both_sides():
    periods = {
        ("2025-01-01", "2025-12-31"): {"value": 26e9, "filed": "2026-02-20", "priority": 0, "rank": (0, 0)},
        ("2025-01-01", "2025-09-30"): {"value": 1.05e9, "filed": "2025-10-30", "priority": 2, "rank": (2, 0)},
    }
    assert sec._flow_quarter(periods, "2025-12-31") is None


# --- revenue: the largest tag wins, tag by tag; a bank's parts as the fallback --

CONTRACT = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _insurer():
    """An insurer: contract revenue (fees) is a sliver of its total Revenues."""
    entries = _usd(CONTRACT,
                   _row("2025-01-01", "2025-12-31", 40.0, "2026-02-20", "10-K", "FY"),
                   _row("2025-01-01", "2025-09-30", 30.0, "2025-11-05"),
                   _row("2025-07-01", "2025-09-30", 10.0, "2025-11-05"),
                   _row("2026-01-01", "2026-03-31", 11.0, "2026-05-05"))
    # Revenues: the year and the three months, but no nine months -- so its Q4 cannot be derived.
    entries += _usd(REVENUE,
                    _row("2025-01-01", "2025-12-31", 1000.0, "2026-02-20", "10-K", "FY"),
                    _row("2025-07-01", "2025-09-30", 250.0, "2025-11-05"),
                    _row("2026-01-01", "2026-03-31", 260.0, "2026-05-05"))
    entries += _usd(NET_INCOME,
                    _row("2025-07-01", "2025-09-30", 20.0, "2025-11-05"),
                    _row("2025-01-01", "2025-12-31", 90.0, "2026-02-20", "10-K", "FY"),
                    _row("2025-01-01", "2025-09-30", 70.0, "2025-11-05"),
                    _row("2026-01-01", "2026-03-31", 22.0, "2026-05-05"))
    return _facts(entries)


def test_revenue_takes_the_largest_tag_in_each_period_annual_and_quarterly():
    facts = _insurer()
    item = sec.ITEMS_BY_KEY["revenue"]
    annual = sec._annual_series(facts, item, sec.share_splits(facts))
    assert annual["2025-12-31"]["value"] == 1000.0 and annual["2025-12-31"]["tag"] == REVENUE
    q = {r["period_end"]: r for r in sec.quarterly_statements(facts)}
    assert q["2025-09-30"]["revenue"] == 250.0 and q["2026-03-31"]["revenue"] == 260.0


def test_a_fourth_quarter_is_derived_within_one_tag_never_across_two():
    q = {r["period_end"]: r for r in sec.quarterly_statements(_insurer())}
    # Revenues has the year but not the nine months; contract revenue has both: its Q4 (40 - 30)
    # stands, rather than the total's year less the contract's nine months (1000 - 30).
    assert q["2025-12-31"]["revenue"] == 10.0 and q["2025-12-31"]["revenue_derived"] is True


def test_a_bank_without_a_revenue_tag_reads_net_interest_plus_noninterest_income():
    entries = _usd("InterestIncomeExpenseNet",
                   _row("2025-01-01", "2025-12-31", 600.0, "2026-02-20", "10-K", "FY"),
                   _row("2026-01-01", "2026-03-31", 160.0, "2026-05-05"))
    entries += _usd("NoninterestIncome",
                    _row("2025-01-01", "2025-12-31", 250.0, "2026-02-20", "10-K", "FY"),
                    _row("2026-01-01", "2026-03-31", 70.0, "2026-05-05"))
    entries += _usd(NET_INCOME,
                    _row("2025-01-01", "2025-12-31", 200.0, "2026-02-20", "10-K", "FY"),
                    _row("2026-01-01", "2026-03-31", 55.0, "2026-05-05"))
    facts = _facts(entries)
    annual = sec._annual_series(facts, sec.ITEMS_BY_KEY["revenue"], sec.share_splits(facts))
    assert annual["2025-12-31"]["value"] == 850.0
    q = {r["period_end"]: r for r in sec.quarterly_statements(facts)}
    assert q["2026-03-31"]["revenue"] == 230.0
    # A bank that tags a revenue line keeps it: the parts stand in only where no tag gives one.
    entries += _usd(REVENUE, _row("2026-01-01", "2026-03-31", 228.0, "2026-05-05"))
    assert {r["period_end"]: r for r in sec.quarterly_statements(_facts(entries))}["2026-03-31"]["revenue"] == 228.0


def test_a_lasting_fall_under_the_same_tag_is_kept_and_a_spike_or_fragment_is_blanked():
    def rows(values):
        return [{"period_end": f"2025-{i + 1:02d}-28", "revenue": v, "revenue_derived": False} for i, v in enumerate(values)]
    # A real collapse: two quarters on the new, lower scale, same tag throughout.
    fall = rows([10.0, 11.0, 10.5, 10.8, 3.0, 2.8])
    sec._drop_stray_revenue(fall, [0] * 6)
    assert [r["revenue"] for r in fall][-2:] == [3.0, 2.8]
    # A year filed under a quarter's dates: far above, blanked even in the same tag.
    spike = rows([10.0, 11.0, 42.0, 10.5, 10.8])
    sec._drop_stray_revenue(spike, [0] * 5)
    assert spike[2]["revenue"] is None
    # A one-quarter fragment, and a fall read from another tag than its neighbours: blanked.
    fragment = rows([10.0, 11.0, 0.2, 10.5, 10.8])
    sec._drop_stray_revenue(fragment, [0] * 5)
    assert fragment[2]["revenue"] is None
    other = rows([10.0, 11.0, 10.5, 10.8, 3.0, 2.8])
    sec._drop_stray_revenue(other, [0, 0, 0, 0, 1, 1])
    assert other[4]["revenue"] is None
