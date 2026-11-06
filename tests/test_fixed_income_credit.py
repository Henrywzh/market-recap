import pandas as pd

from market_recap.panels import fixed_income


class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)


class _Ctx:
    def __init__(self):
        self.log = _Log()


def _frame(dates, values):
    return pd.DataFrame({"date": pd.to_datetime(dates), "value": values})


def test_credit_joins_the_archive_before_fred_and_fred_wins_where_both_exist(monkeypatch):
    fred_data = {"A": _frame(["2026-01-02", "2026-01-05"], [3.0, 3.1]),
                 "Y": _frame(["2026-01-02", "2026-01-05"], [7.0, 7.2])}
    archive = {"A": pd.Series([2.5, 2.9, 9.9], index=pd.to_datetime(["2025-12-30", "2025-12-31", "2026-01-02"]))}
    monkeypatch.setattr(fixed_income.fred, "fetch_series", lambda sid: (fred_data[sid], "url"))
    monkeypatch.setattr(fixed_income.snapshot_store, "risk_archive", lambda src, sid: archive.get(sid, pd.Series(dtype=float)))
    ctx = _Ctx()
    out = fixed_income._credit(ctx, {"credit_spreads": [{"label": "B", "series_id": "A"}],
                                     "credit_yields": [{"label": "HY", "series_id": "Y"}]})
    assert out["spreads"]["B"]["dates"] == ["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"]
    assert out["spreads"]["B"]["values"] == [2.5, 2.9, 3.0, 3.1]
    assert out["first"] == {"B": "2025-12-30", "HY": "2026-01-02"}
    assert [(r.source_id, r.status, r.observed_date) for r in ctx.log.records] == [
        ("fred_credit_spreads", "ok", "2026-01-05"), ("fred_credit_yields", "ok", "2026-01-05")]


def test_a_failed_series_is_left_out_and_marks_the_source_partial(monkeypatch):
    def fetch(sid):
        raise RuntimeError("FRED down")
    monkeypatch.setattr(fixed_income.fred, "fetch_series", fetch)
    monkeypatch.setattr(fixed_income.snapshot_store, "risk_archive", lambda src, sid: pd.Series(dtype=float))
    ctx = _Ctx()
    out = fixed_income._credit(ctx, {"credit_spreads": [{"label": "B", "series_id": "A"}]})
    assert out["spreads"] == {}
    assert ctx.log.records[0].status == "partial" and "FRED down" in ctx.log.records[0].error


def test_yield_history_takes_the_sessions_fred_has_not_posted_from_treasurys_curve(monkeypatch):
    fred_data = {"DGS2": _frame(["2026-11-03", "2026-11-04"], [4.61, 4.58]),
                 "DGS10": _frame(["2026-11-03", "2026-11-04"], [4.95, 4.90])}
    monkeypatch.setattr(fixed_income.fred, "fetch_series", lambda sid: (fred_data[sid], "url"))
    curve = pd.DataFrame({"2Y": [4.58, 4.46], "10Y": [4.90, 4.84]}, index=pd.to_datetime(["2026-11-04", "2026-11-05"]))
    out = fixed_income._history(_Ctx(), {"history_series": [{"label": "2Y", "series_id": "DGS2"}, {"label": "10Y", "series_id": "DGS10"}],
                                         "history_spread": {"label": "10Y − 2Y", "long": "10Y", "short": "2Y"}}, curve)
    assert out["series"]["10Y"]["dates"][-1] == "2026-11-05" and out["series"]["10Y"]["values"][-1] == 4.84
    assert out["series"]["10Y − 2Y"]["values"][-1] == 38 and out["from_treasury"] == ["2026-11-05"]
    # Where FRED has a session, FRED's value stands.
    assert out["series"]["10Y"]["values"][-2] == 4.90
