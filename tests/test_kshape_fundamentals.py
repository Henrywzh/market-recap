"""K-SHAPE fundamentals: each leg as an equal-weight basket of its names' P/E and earnings.

The VALUATION reader and the price and estimate fetches are monkeypatched; no network.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

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
    monkeypatch.setattr(P, "FINANCIALS_ARTIFACT_DIR", Path(__file__).with_name("no-financials-here"))
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
    # No VALUATION rows here, so B1 has no market cap either: it is out of the history too, and the note says so.
    assert arms[1]["note"] == ("Left out for lack of a filings history: NEW. "
                               "Left out of the fundamentals history for lack of a market cap: B1.")
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


def _valued(ticker, *, eps_ntm, prev, now, nxt):
    """A VALUATION row at a price of 100: consensus EPS for last year, this year and next."""
    return {"ticker": ticker, "price": 100.0, "market_cap": 1e9, "eps_ntm": eps_ntm,
            "eps_fy_prev": prev, "eps_fy0": now, "eps_fy1": nxt}


def test_each_leg_carries_its_outlook_over_the_names_with_a_filings_history(monkeypatch):
    histories = {"T1": artifact(5.0), "T2": artifact(4.0), "B1": artifact(10.0), "LOW": artifact(20.0)}
    ctx = _ctx(monkeypatch, histories)
    rows = [_valued("T1", eps_ntm=5.0, prev=4.0, now=5.0, nxt=5.5), _valued("T2", eps_ntm=4.0, prev=3.6, now=4.0, nxt=4.2)]
    panel = P.build(ctx, inputs={"valuation": {"rows": rows, "as_of": ctx.as_of}})

    air = panel["views"][1]
    top, bottom = (arm["outlook"] for arm in air["fundamentals"]["arms"])
    # Equal value: forward 2 / (0.05 + 0.04); EPS 0.076 -> 0.09 -> 0.097; no revenue file, so no revenue growth.
    assert top == {"forward_pe": 22.2, "eps_growth_this": 18.4, "eps_growth_next": 7.8, "revenue_growth": None, "names": 2}
    # B1 has a filings history but no VALUATION row, so it has no earnings to total and the leg has no figure.
    assert bottom["names"] == 1 and bottom["forward_pe"] is None and bottom["eps_growth_this"] is None


def test_a_leg_with_no_filings_history_at_all_makes_its_view_missing_with_that_leg_named(monkeypatch):
    histories = {"B1": artifact(10.0)}                                            # the top leg has no history
    ctx = _ctx(monkeypatch, histories)
    panel = P.build(ctx, inputs={"valuation": {"rows": [], "as_of": ctx.as_of}})
    air = panel["views"][1]
    assert set(air["fundamentals"]) == {"missing"} and air["fundamentals"]["missing"].startswith("Top leg: no name has a filings history")


# --- each arm's history: revenue growth and margins by fiscal year ---------------------

def _statement(revenue, ebit, years=(2023, 2024), gross=None):
    """A FINANCIALS artifact as far as the history reads it: annual revenue and operating profit by fiscal year."""
    values = {"revenue": list(revenue), "ebit": list(ebit)}
    if gross is not None:
        values["gross_profit"] = list(gross)
    return {"columns": [{"fiscal_year": y} for y in years], "values": values}


def _write_statement(directory, ticker, statement):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ticker}.json").write_text(json.dumps(statement))


def test_statements_are_read_once_and_the_revenue_weights_read_them_the_way_baskets_does(tmp_path, monkeypatch):
    _write_statement(tmp_path, "A", _statement([100.0, 110.0], [20.0, 22.0]))
    reads = []
    original = B.read_statements

    def counting(directory, ticker):
        reads.append(ticker)
        return original(directory, ticker)

    monkeypatch.setattr(B, "read_statements", counting)
    statements = P.Statements(tmp_path)
    revenues = P.Revenues(tmp_path, statements)
    assert revenues.of(["A", "NOPE"]) == {"A": 110.0, "NOPE": None}
    assert revenues.of(["A"]) == {"A": 110.0}
    assert statements.of(["A", "NOPE"])["A"]["values"]["ebit"] == [20.0, 22.0]
    assert sorted(reads) == ["A", "NOPE"]                                        # each file opened once, however often asked
    assert P.Revenues(tmp_path).of(["A"]) == {"A": B.latest_revenue(tmp_path, "A")}     # the same reading as baskets


def test_an_equal_weight_arm_holds_each_name_at_one_over_its_market_cap(tmp_path):
    _write_statement(tmp_path, "A", _statement([100.0, 120.0], [20.0, 24.0]))
    _write_statement(tmp_path, "B", _statement([300.0, 330.0], [30.0, 33.0]))
    closes, yields = B.frames({"A": artifact(5.0), "B": artifact(10.0)})
    rows = {"A": {"market_cap": 300.0}, "B": {"market_cap": 100.0}}
    arm, reason = P.arm("top", "Top leg", ["A", "B"], closes, yields, years=10, rows=rows,
                        statements=P.Statements(tmp_path))
    assert reason is None and arm["note"] is None
    # Shares of each company: 1/300 and 1/100. Margins and growth are ratios, so the scale of the shares cancels.
    share_a, share_b = 1 / 300, 1 / 100
    history = arm["history"]
    assert history["years"] == [2023, 2024]
    assert history["revenue_growth"][0] is None
    assert history["revenue_growth"][1] == pytest.approx(
        ((120 * share_a + 330 * share_b) / (100 * share_a + 300 * share_b) - 1) * 100, abs=0.05)
    assert history["operating_margin"][1] == pytest.approx(
        (24 * share_a + 33 * share_b) / (120 * share_a + 330 * share_b) * 100, abs=0.05)


def test_a_name_with_no_market_cap_is_left_out_of_an_equal_weight_history_and_the_note_says_so(tmp_path):
    _write_statement(tmp_path, "A", _statement([100.0, 120.0], [20.0, 24.0]))
    _write_statement(tmp_path, "C", _statement([50.0, 50.0], [25.0, 25.0]))           # a margin of 50% that must not count
    closes, yields = B.frames({"A": artifact(5.0), "C": artifact(5.0)})
    arm, _ = P.arm("top", "Top leg", ["A", "C"], closes, yields, years=10, rows={"A": {"market_cap": 100.0}},
                   statements=P.Statements(tmp_path))
    assert arm["history"]["operating_margin"][1] == pytest.approx(24 / 120 * 100, abs=0.05)   # A alone
    assert arm["note"] == "Left out of the fundamentals history for lack of a market cap: C."
    assert arm["basket"]["names"] == 2                                                        # C still counts in the basket


def test_an_arm_without_statements_has_no_history(monkeypatch):
    closes, yields = B.frames({"A": artifact(5.0)})
    arm, _ = P.arm("top", "Top leg", ["A"], closes, yields, years=10, rows={"A": {"market_cap": 1.0}})
    assert arm["history"] is None and arm["note"] is None


def test_the_panel_gives_each_leg_a_history_from_the_filings_on_disk(monkeypatch, tmp_path):
    for ticker, revenue in {"T1": [100.0, 120.0], "T2": [60.0, 66.0], "B1": [300.0, 330.0]}.items():
        _write_statement(tmp_path, ticker, _statement(revenue, [r / 10 for r in revenue]))
    histories = {"T1": artifact(5.0), "T2": artifact(4.0), "B1": artifact(10.0), "LOW": artifact(20.0)}
    ctx = _ctx(monkeypatch, histories)
    monkeypatch.setattr(P, "FINANCIALS_ARTIFACT_DIR", tmp_path)
    rows = [{**_valued(t, eps_ntm=5.0, prev=4.0, now=5.0, nxt=5.5), "market_cap": cap}
            for t, cap in (("T1", 200.0), ("T2", 100.0), ("B1", 300.0))]
    panel = P.build(ctx, inputs={"valuation": {"rows": rows, "as_of": ctx.as_of}})
    json.dumps(panel, allow_nan=False)

    arms = panel["views"][1]["fundamentals"]["arms"]
    top, bottom = arms[0]["history"], arms[1]["history"]
    assert top["years"] == [2023, 2024] and bottom["years"] == [2023, 2024]
    # Top leg: 2 shares at 1/200 and 1/100 over revenue 120 and 66 against 100 and 60 the year before.
    assert top["revenue_growth"][1] == pytest.approx(((120 / 200 + 66 / 100) / (100 / 200 + 60 / 100) - 1) * 100, abs=0.05)
    assert bottom["revenue_growth"][1] == pytest.approx(10.0)                              # B1 alone: 330 over 300
    assert bottom["operating_margin"][1] == pytest.approx(33.0 / 330.0 * 100, abs=0.05)
