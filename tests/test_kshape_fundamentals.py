"""K-SHAPE fundamentals: each leg as an equal-weight basket of its names' P/E and earnings.

The VALUATION reader and the price and estimate fetches are monkeypatched; no network.
"""

import json

import numpy as np
import pandas as pd

from market_recap.compute import baskets as B
from market_recap.config import load_config
from market_recap.panels import kshape as P


def weeks(n=80, start="2023-01-06"):
    return pd.date_range(start, periods=n, freq="W-FRI")


def artifact(ey, n=80, close=100.0):
    """A VALUATION artifact as far as the fundamentals read it: a flat price and a flat earnings yield (percent)."""
    dates = weeks(n)
    return {"dates": [d.strftime("%Y-%m-%d") for d in dates], "close": [close] * n, "ey": [float(ey)] * n,
            "pe": [100 / ey] * n, "eps": []}


def flat_closes(columns, n=80):
    return pd.DataFrame({c: [100.0] * n for c in columns}, index=weeks(n))


def _frames(histories, names):
    """The weekly closes and earnings yields the arm builder takes, from the same artifacts the panel reads."""
    return B.frames({t: histories.get(t) for t in names})


# --- the arm -----------------------------------------------------------------------------

def test_an_arm_is_an_equal_weight_basket_of_the_names_with_a_filings_history_and_names_the_rest():
    histories = {"A": artifact(5.0), "B": artifact(10.0)}                     # NEW has no artifact
    closes, yields = _frames(histories, ["A", "B", "NEW"])
    arm, reason = P.arm("top", "Top leg", ["A", "B", "NEW"], closes, yields, years=10)
    # Equal value in each name: 2 over (0.05 + 0.10) is 13.33 on every week.
    assert reason is None and arm["basket"]["names"] == 2 and set(arm["basket"]["pe"]) == {13.33}
    assert arm["note"] == "Left out for lack of a filings history: NEW."
    assert arm["fund_coverage"] is None and arm["key"] == "top" and arm["label"] == "Top leg"


def test_an_arm_with_no_name_that_has_a_history_has_no_basket_and_gives_the_reason():
    arm, reason = P.arm("bottom", "Bottom leg", ["X", "Y"], pd.DataFrame(), pd.DataFrame(), years=10)
    assert arm["basket"] is None
    assert reason == "Bottom leg: no name has a filings history, so no basket can be built."


def test_an_arm_whose_names_never_had_a_pe_gives_the_reason_not_an_empty_basket():
    histories = {"A": {**artifact(5.0), "ey": [-5.0] * 80}}                       # a loss every week: no P/E ever
    closes, yields = _frames(histories, ["A"])
    arm, reason = P.arm("top", "Top leg", ["A"], closes, yields, years=10)
    assert arm["basket"] is None and reason.startswith("Top leg: none of its names had a P/E")


def test_a_long_list_of_names_left_out_is_cut_to_twelve_and_counted():
    names = [f"N{i:02d}" for i in range(15)]
    closes, yields = _frames({"A": artifact(5.0)}, ["A"])
    arm, _ = P.arm("top", "Top leg", ["A"] + names, closes, yields, years=10)
    assert arm["note"].endswith("N00, N01, N02, N03, N04, N05, N06, N07, N08, N09, N10, N11 and 3 more.")


def test_fundamentals_is_missing_when_either_leg_has_no_basket_and_is_both_arms_otherwise():
    ok, _ = P.arm("top", "Top leg", ["A"], *_frames({"A": artifact(5.0)}, ["A"]), years=10)
    none, reason = P.arm("bottom", "Bottom leg", ["X"], pd.DataFrame(), pd.DataFrame(), years=10)
    assert P.fundamentals([(ok, None), (none, reason)]) == {"missing": reason}
    built = P.fundamentals([(ok, None), (ok | {"key": "bottom"}, None)], notes=["n"])
    assert [a["key"] for a in built["arms"]] == ["top", "bottom"] and built["notes"] == ["n"]


def test_histories_are_read_once_per_name_and_frames_are_kept_per_set_of_names(monkeypatch):
    reads = []

    def read(ticker):
        reads.append(ticker)
        return {"A": artifact(5.0), "B": artifact(10.0)}.get(ticker)

    monkeypatch.setattr(P, "_read_history", read)
    histories = P.Histories()
    first = histories.frames(["A", "B"])
    again = histories.frames(["B", "A"])
    assert sorted(reads) == ["A", "B"] and again is first
    histories.frames(["A"])
    assert sorted(reads) == ["A", "B"]                                          # the one name already read is not read again


# --- the panel, end to end on fakes ------------------------------------------------------

def _cfg():
    cfg = dict(load_config()["kshape"])
    cfg.update(pairs=[{"key": "air", "label": "AIR", "top": ["T1", "T2"], "bottom": ["B1", "NEW"], "note": "n"}],
               bottom_only=["LOW"])
    return cfg


class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def fail(self, *a):
        raise AssertionError(a)


def _ctx(monkeypatch, histories):
    idx = pd.bdate_range("2023-01-02", periods=800)
    cols = ["T1", "T2", "B1", "LOW", "NEW"]
    rng = np.random.default_rng(3)
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, (len(idx), len(cols))), axis=0)), index=idx, columns=cols)
    cfg = {**load_config(), "kshape": _cfg()}
    ctx = type("C", (), {"config": cfg, "as_of": idx[-1].date().isoformat(), "closes": closes, "log": _Log()})()

    def no_fetch(*args, **kwargs):
        raise AssertionError("no network: prices and estimates are fakes")

    monkeypatch.setattr(P, "_read_history", lambda t: histories.get(t))
    monkeypatch.setattr(P.yahoo, "fetch_closes", no_fetch)
    monkeypatch.setattr(P.estimates, "fetch_trends", lambda syms, **kw: ({}, {}))
    return ctx


def test_the_panel_gives_each_view_its_two_legs_as_baskets_and_names_the_leg_member_with_no_history(monkeypatch):
    histories = {"T1": artifact(5.0), "T2": artifact(4.0), "B1": artifact(10.0), "LOW": artifact(20.0)}
    ctx = _ctx(monkeypatch, histories)
    valuation = {"rows": [], "as_of": ctx.as_of}
    panel = P.build(ctx, inputs={"valuation": valuation})
    json.dumps(panel, allow_nan=False)

    overall, air = panel["views"]
    arms = air["fundamentals"]["arms"]
    assert [a["label"] for a in arms] == ["Top leg", "Bottom leg"]
    assert arms[0]["basket"]["names"] == 2 and arms[1]["basket"]["names"] == 1
    assert arms[1]["note"] == "Left out for lack of a filings history: NEW."
    # Top: 2 over (0.05 + 0.04) is 22.22. Bottom: B1 alone, 10% yield, so P/E 10.
    assert set(arms[0]["basket"]["pe"]) == {22.22} and set(arms[1]["basket"]["pe"]) == {10.0}
    assert overall["fundamentals"]["arms"][1]["basket"]["names"] == 2                # B1 and LOW; NEW left out of both views' bottom
    assert panel["inputs"]["valuation_built"] is True


def test_without_valuation_every_view_says_so_and_has_no_baskets(monkeypatch):
    ctx = _ctx(monkeypatch, {})
    panel = P.build(ctx, inputs={})
    for view in panel["views"]:
        assert view["fundamentals"] == {"missing": P.NO_VALUATION}
    assert panel["inputs"]["valuation_built"] is False


def test_a_leg_with_no_filings_history_at_all_makes_its_view_missing_with_that_leg_named(monkeypatch):
    histories = {"B1": artifact(10.0)}                                            # the top leg has no history
    ctx = _ctx(monkeypatch, histories)
    panel = P.build(ctx, inputs={"valuation": {"rows": [], "as_of": ctx.as_of}})
    air = panel["views"][1]
    assert set(air["fundamentals"]) == {"missing"} and air["fundamentals"]["missing"].startswith("Top leg: no name has a filings history")
