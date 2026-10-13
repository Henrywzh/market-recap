"""CATALYST LOG: an event's price move and whether consensus followed, with the snapshot table stubbed."""

import numpy as np
import pandas as pd
import pytest

from market_recap.config import load_config
from market_recap.panels import catalyst_log as P


class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)


def _snapshots(rows):
    return pd.DataFrame(rows, columns=["date", "symbol", "period", "end", "eps", "analysts", "revenue", "up_30d", "down_30d", "up_7d", "down_7d"])


def _ctx(monkeypatch, table, *, fetched=None):
    idx = pd.bdate_range("2026-10-01", "2026-10-12")                   # 1 Oct .. 12 Oct
    closes = pd.DataFrame({"A": np.linspace(100, 90, len(idx)), "B": np.linspace(50, 40, len(idx)), "C": np.linspace(20, 22, len(idx))}, index=idx)
    etf = pd.DataFrame({"SPY": np.linspace(600, 606, len(idx))}, index=idx)
    cfg = {**load_config(), "catalyst_log": {
        "price_move_pct": 3.0, "revision_pct": 1.0, "min_names": 2, "periods": ["0y", "+1y"], "period_labels": {"0y": "THIS YEAR", "+1y": "NEXT YEAR"},
        "read_period": "0y",
        "items": [{"key": "e1", "date": "2026-10-08", "title": "Event one", "kind": "demand", "source": "src", "url": "http://x", "exposed": ["A", "B", "C"]},
                  {"key": "e0", "date": "2026-09-20", "title": "Before the snapshots", "exposed": ["A", "B"]},
                  {"key": "e2", "date": "2026-10-10", "title": "Weekend, with an Asian name", "exposed": ["A", "ASIA"]}]}}
    ctx = type("C", (), {"config": cfg, "as_of": "2026-10-12", "closes": closes, "etf_closes": etf, "log": _Log()})()
    monkeypatch.setattr(P.snapshot_store, "consensus_table", lambda since, until: table)
    asia = pd.DataFrame({"ASIA": [10.0, 9.0, 8.0]}, index=pd.to_datetime(["2026-10-08", "2026-10-12", "2026-10-13"]))
    monkeypatch.setattr(P.yahoo, "fetch_closes", lambda syms, **kw: asia if fetched is None else fetched)
    return ctx


def _rows():
    out = []
    for day, a, b, c in (("2026-10-07", 10.0, 5.0, 2.0), ("2026-10-12", 10.0, 5.0, 2.1)):
        out += [[day, "A", "0y", "2026-12-31", a, 30, 100.0, 5, 1, np.nan, np.nan], [day, "B", "0y", "2026-12-31", b, 20, 50.0, 2, 0, 3, 1],
                [day, "C", "0y", "2026-12-31", c, 10, 20.0, 1, 1, np.nan, np.nan]]
    return _snapshots(out)


def test_an_event_reads_price_down_and_estimates_flat_against_the_close_before_it(monkeypatch):
    ctx = _ctx(monkeypatch, _rows())
    p = P.build(ctx)
    e1 = next(i for i in p["items"] if i["key"] == "e1")
    assert e1["reference"] == "2026-10-07" and e1["snapshots"] == {"reference": "2026-10-07", "latest": "2026-10-12", "note": None}
    names = {n["ticker"]: n for n in e1["names"]}
    a_close = ctx.closes["A"]
    assert names["A"]["price_pct"] == pytest.approx((a_close.iloc[-1] / a_close.loc["2026-10-07"] - 1) * 100, abs=0.06)
    assert names["A"]["eps"]["0y"] == 0.0 and names["C"]["eps"]["0y"] == pytest.approx(5.0)
    assert names["B"]["counts"] == {"up_7d": 3, "down_7d": 1, "up_30d": 2, "down_30d": 0, "analysts": 20}
    assert names["A"]["counts"]["up_7d"] is None                                    # not recorded: None, not zero
    assert e1["basket"]["price"]["n"] == 3 and e1["basket"]["eps"]["0y"]["median"] == 0.0
    assert e1["state"] == {"price": "down", "estimates": "flat", "read_period": "0y", "names_with_estimates": 3}
    assert e1["basket"]["path"]["dates"][0] == "2026-10-07" and e1["basket"]["path"]["basket"][0] == 100.0
    assert [i["key"] for i in p["items"]] == ["e2", "e1", "e0"]                     # newest first


def test_an_event_before_the_snapshots_has_prices_only_and_says_so(monkeypatch):
    p = P.build(_ctx(monkeypatch, _rows()))
    e0 = next(i for i in p["items"] if i["key"] == "e0")
    assert e0["snapshots"]["reference"] is None and "prices only" in e0["snapshots"]["note"]
    assert all(n["eps"]["0y"] is None for n in e0["names"]) and e0["state"]["estimates"] is None and e0["basket"]["price"]["n"] == 0
    assert all(n["price_pct"] is None for n in e0["names"]) and e0["state"]["price"] is None       # the closes start after the event: nothing is invented


def test_a_weekend_event_uses_the_friday_close_a_name_fetched_here_is_clipped_to_the_session_and_few_names_give_no_reading(monkeypatch):
    ctx = _ctx(monkeypatch, _rows())
    p = P.build(ctx)
    e2 = next(i for i in p["items"] if i["key"] == "e2")
    assert e2["reference"] == "2026-10-09"
    asia = next(n for n in e2["names"] if n["ticker"] == "ASIA")
    assert asia["price_last"] == "2026-10-12" and asia["price_pct"] == pytest.approx(-10.0)    # 10-13 is after the page's session
    assert asia["has_estimates"] is False and asia["eps"]["0y"] is None
    assert e2["state"]["estimates"] is None and e2["state"]["names_with_estimates"] == 1       # one name with an estimate is not a basket
    assert p["inputs"]["prices_through"] == "2026-10-12"


def test_without_any_snapshot_every_item_keeps_its_prices(monkeypatch):
    p = P.build(_ctx(monkeypatch, _snapshots([])))
    assert p["snapshots"] == {"first": None, "last": None, "days": 0}
    e1 = next(i for i in p["items"] if i["key"] == "e1")
    assert e1["state"]["price"] == "down" and e1["state"]["estimates"] is None and e1["snapshots"]["latest"] is None
    assert any("snapshots began" in n for n in p["notes"])
