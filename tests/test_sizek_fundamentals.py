"""SIZE & STYLE fundamentals: each arm of a pair as a basket of its names' P/E and earnings.

Every history and holding here is a fake: the reader and the iShares fetch are
monkeypatched, so nothing reaches the network.
"""

import json

import numpy as np
import pandas as pd
import pytest

from market_recap import validate as V
from market_recap.config import load_config
from market_recap.panels import kshape as KP
from market_recap.panels import sizek as P
from market_recap.sources.http import FetchError


def weeks(n=80, start="2021-01-08"):
    return pd.date_range(start, periods=n, freq="W-FRI")


def artifact(close, ey, dates=None):
    """A per-ticker VALUATION artifact as far as the fundamentals read it: weekly close and earnings yield."""
    dates = weeks(len(close)) if dates is None else dates
    return {"dates": [d.strftime("%Y-%m-%d") for d in dates], "close": [float(c) for c in close],
            "ey": [float(e) for e in ey]}


def flat(ey, n=80):
    """A name whose price never moves and whose earnings yield is ``ey`` percent: its P/E is 100 / ey."""
    return artifact([100.0] * n, [ey] * n)


def row(ticker, *, indices=("SPX",), sector="Information Technology", cap=100.0):
    return {"ticker": ticker, "indices": list(indices), "sector": sector, "market_cap": cap}


class _Log:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)


class _Ctx:
    def __init__(self, config=None, as_of="2026-10-12"):
        self.config = config or {}
        self.as_of = as_of
        self.log = _Log()


def _no_fetch(*args, **kwargs):
    raise AssertionError("no network: the iShares fetch must not run here")


def _holdings(lines):
    """An iShares equity file as the parser leaves it: fraction weights, the names as tickers."""
    return pd.DataFrame({"ticker": [t for t, _ in lines], "name": [f"{t} Inc" for t, _ in lines],
                         "sector": ["Information Technology"] * len(lines), "asset_class": ["Equity"] * len(lines),
                         "weight": [w for _, w in lines]})


def _histories(monkeypatch, histories):
    """Route the VALUATION reader to ``histories`` and count the reads per name."""
    reads: list[str] = []

    def read(ticker):
        reads.append(ticker)
        return histories.get(ticker)

    monkeypatch.setattr(KP, "_read_history", read)
    return reads


# --- the spec of a basket -------------------------------------------------------------

def test_a_basket_spec_reads_three_kinds_and_refuses_the_rest():
    assert P.parse_basket("index:SPX") == ("index", "SPX", False)
    assert P.parse_basket("index:SPX:equal") == ("index", "SPX", True)
    assert P.parse_basket("sector:Consumer Staples") == ("sector", "Consumer Staples", False)
    assert P.parse_basket("holdings:IWD") == ("holdings", "IWD", False)
    for bad in ("index", "index:", "fund:IWD", "index:SPX:cap", "holdings:IWD:equal"):
        with pytest.raises(ValueError):
            P.parse_basket(bad)


def test_an_arm_without_a_configured_label_is_named_from_its_spec():
    assert P.basket_label("index", "SPX", False) == "S&P 500 cap-weighted"
    assert P.basket_label("index", "NDX", True) == "Nasdaq-100 equal-weight"
    assert P.basket_label("sector", "Consumer Staples", False) == "Consumer Staples sector"
    assert P.basket_label("holdings", "IWD", False) == "IWD"                 # a fund's full name comes from the config


def test_the_real_config_gives_each_pair_both_baskets_or_says_why_not():
    pairs = {p["key"]: p for p in load_config()["sizek"]["pairs"]}
    with_baskets = {k for k, p in pairs.items() if p.get("big_basket")}
    assert with_baskets == {"sp500", "nasdaq100", "value_growth", "staples_market", "lowvol_market"}
    for key in with_baskets:
        assert pairs[key].get("small_basket"), key
        P.parse_basket(pairs[key]["big_basket"])
        P.parse_basket(pairs[key]["small_basket"])
    for key in set(pairs) - with_baskets:
        assert isinstance(pairs[key].get("fundamentals_note"), str) and pairs[key]["fundamentals_note"], key
    assert pairs["value_growth"]["big_basket_label"] == "IWD · Russell 1000 Value"


def test_members_of_a_sector_arm_are_the_primary_index_names_in_that_sector():
    rows = {"A": row("A", sector="Consumer Staples"), "B": row("B", sector="Consumer Staples", indices=("NDX",)),
            "C": row("C", sector="Information Technology")}
    assert P._members("sector", "Consumer Staples", rows) == ["A"]
    assert P._members("index", "NDX", rows) == ["B"]
    assert P._members("index", "SPX", rows) == ["A", "C"]


# --- index and sector arms ------------------------------------------------------------

def test_a_cap_weighted_arm_is_the_total_value_over_total_earnings_and_an_equal_arm_is_the_same_on_equal_value(monkeypatch):
    # A and B flat in price, A on earnings yield 5 and B on 10; C has no market cap, so cap-weighting leaves it out.
    histories = {"A": flat(5.0), "B": flat(10.0), "C": flat(5.0)}
    _histories(monkeypatch, histories)
    rows = {"A": row("A", cap=300.0), "B": row("B", cap=100.0), "C": row("C", cap=None)}
    ctx = _Ctx()

    cap, cap_reason = P._arm("big", "index:SPX", None, rows, KP.Histories(), {}, ctx, 10)
    equal, equal_reason = P._arm("small", "index:SPX:equal", None, rows, KP.Histories(), {}, ctx, 10)

    # Value 3 and 1 on earnings 0.15 and 0.10 of price: 4 over 0.25 is 16 on every week.
    assert cap_reason is None and cap["label"] == "S&P 500 cap-weighted" and cap["fund_coverage"] is None
    assert set(cap["basket"]["pe"]) == {16.0} and cap["basket"]["names"] == 2
    assert "C" in cap["note"] and "market cap" in cap["note"]
    # Equal value: 3 over 0.20 is 15, all three names.
    assert equal_reason is None and set(equal["basket"]["pe"]) == {15.0} and equal["basket"]["names"] == 3
    assert equal["note"] is None


def test_an_arm_whose_names_have_no_history_has_no_basket_and_says_so(monkeypatch):
    _histories(monkeypatch, {})
    arm, reason = P._arm("big", "sector:Consumer Staples", None, {"A": row("A", sector="Consumer Staples")}, KP.Histories(), {}, _Ctx(), 10)
    assert arm["basket"] is None and reason.startswith("Consumer Staples sector: no name has a filings history")


# --- fund arms -------------------------------------------------------------------------

def test_a_fund_arm_is_weighted_by_the_fund_s_holdings_and_says_how_much_of_the_fund_it_covers(monkeypatch):
    _histories(monkeypatch, {"A": flat(5.0), "B": flat(10.0)})
    seen = []

    def fetch(ticker, **kwargs):
        seen.append(ticker)
        return _holdings([("A", 0.5), ("B", 0.3), ("Z", 0.2)]), "2026-10-09", f"https://example.test/{ticker}"

    monkeypatch.setattr(P.ishares, "fetch_holdings", fetch)
    ctx = _Ctx()
    rows = {"A": row("A"), "B": row("B")}     # Z is not in VALUATION: its 20% is in the denominator only

    arm, reason = P._arm("big", "holdings:IWD", "IWD · Russell 1000 Value", rows, KP.Histories(), {}, ctx, 10)

    # Shares from the holding weights at a price of 100: values 0.5 and 0.3. Earnings 0.5 x 5% + 0.3 x 10% = 0.055 on 0.8.
    assert reason is None and arm["label"] == "IWD · Russell 1000 Value"
    assert arm["fund_coverage"] == pytest.approx(0.8)
    assert set(arm["basket"]["pe"]) == {round(0.8 / 0.055, 2)} and arm["basket"]["names"] == 2
    assert "as of 2026-10-09" in arm["note"]
    record = [r for r in ctx.log.records if r.source_id == "sizek_iwd_holdings"][0]
    assert record.status == "ok" and record.rows == 3 and record.observed_date == "2026-10-09" and seen == ["IWD"]


def test_a_failed_holdings_fetch_says_why_is_logged_and_is_fetched_once(monkeypatch):
    _histories(monkeypatch, {"A": flat(5.0)})
    calls = []

    def fetch(ticker, **kwargs):
        calls.append(ticker)
        raise FetchError("ishares.com: timed out")

    monkeypatch.setattr(P.ishares, "fetch_holdings", fetch)
    ctx, histories, memo = _Ctx(), KP.Histories(), {}
    rows = {"A": row("A")}

    arm, reason = P._arm("big", "holdings:USMV", None, rows, histories, memo, ctx, 10)
    again, again_reason = P._arm("small", "holdings:USMV", None, rows, histories, memo, ctx, 10)

    assert arm["basket"] is None and "could not be fetched" in reason and "timed out" in reason
    assert again["basket"] is None and calls == ["USMV"]                                   # one fetch per build, not per arm
    record = [r for r in ctx.log.records if r.source_id == "sizek_usmv_holdings"][0]
    assert record.status == "error" and "timed out" in record.error


# --- the pair's block -----------------------------------------------------------------

def test_a_pair_without_baskets_carries_its_note_and_fetches_nothing(monkeypatch):
    monkeypatch.setattr(P.ishares, "fetch_holdings", _no_fetch)
    pair = {"key": "small", "big": "IWM", "small": "SPY", "fundamentals_note": "Small companies are outside the universe."}
    block = P._pair_fundamentals(pair, {"A": row("A")}, KP.Histories(), {}, _Ctx(), 10)
    assert block == {"fundamentals_note": "Small companies are outside the universe."}     # no fundamentals key at all


def test_a_pair_with_baskets_but_no_valuation_this_session_says_so_and_fetches_nothing(monkeypatch):
    monkeypatch.setattr(P.ishares, "fetch_holdings", _no_fetch)
    pair = {"key": "vg", "big_basket": "holdings:IWD", "small_basket": "holdings:IWF"}
    block = P._pair_fundamentals(pair, None, KP.Histories(), {}, _Ctx(), 10)
    assert block == {"fundamentals": {"missing": KP.NO_VALUATION}, "fundamentals_note": None}


def test_a_pair_gives_both_arms_or_the_reason_one_arm_cannot_be_built(monkeypatch):
    _histories(monkeypatch, {"A": flat(5.0), "B": flat(10.0)})
    monkeypatch.setattr(P.ishares, "fetch_holdings", lambda ticker, **k: (_holdings([("A", 1.0)]), "2026-10-09", "u"))
    rows = {"A": row("A", cap=1.0), "B": row("B", cap=1.0)}
    pair = {"key": "sp", "big_basket": "index:SPX", "small_basket": "index:SPX:equal"}

    block = P._pair_fundamentals(pair, rows, KP.Histories(), {}, _Ctx(), 10)
    arms = block["fundamentals"]["arms"]
    assert [a["key"] for a in arms] == ["big", "small"] and block["fundamentals"]["notes"] == []

    pair_missing = {"key": "vg", "big_basket": "index:SPX", "small_basket": "holdings:NOPE"}

    def no_such_fund(ticker, **kwargs):
        raise FetchError("no such fund")

    monkeypatch.setattr(P.ishares, "fetch_holdings", no_such_fund)
    missing = P._pair_fundamentals(pair_missing, rows, KP.Histories(), {}, _Ctx(), 10)["fundamentals"]
    assert set(missing) == {"missing"} and "could not be fetched" in missing["missing"]


def test_the_histories_are_read_once_however_many_arms_share_a_name(monkeypatch):
    reads = _histories(monkeypatch, {"A": flat(5.0), "B": flat(10.0)})
    rows = {"A": row("A", cap=1.0), "B": row("B", cap=1.0)}
    histories = KP.Histories()
    for spec in ("index:SPX", "index:SPX:equal", "index:SPX"):
        P._arm("big", spec, None, rows, histories, {}, _Ctx(), 10)
    assert sorted(reads) == ["A", "B"]


# --- the panel, end to end on fakes -----------------------------------------------------

def _panel(monkeypatch, pairs, rows, holdings, inputs="valuation"):
    idx = pd.bdate_range("2021-01-04", periods=900)
    cfg = {**load_config(), "sizek": {"history_years": 25, "price_periods": ["1M", "1Y", "10Y"], "gap_period": "1Y", "pairs": pairs}}
    ctx = _Ctx(cfg, as_of=idx[-1].date().isoformat())

    def closes(syms, **kwargs):
        rng = np.random.default_rng(len(syms))
        return pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(idx)))) for s in syms}, index=idx)

    monkeypatch.setattr(P.yahoo, "fetch_closes", closes)
    monkeypatch.setattr(P.ishares, "fetch_holdings", lambda ticker, **k: (holdings[ticker], "2026-10-09", f"https://example.test/{ticker}"))
    panel_inputs = None if inputs is None else {"valuation": {"rows": rows, "as_of": ctx.as_of}}
    return P.build(ctx, inputs=panel_inputs), ctx


def test_the_panel_gives_each_view_its_fundamentals_and_the_gap_only_where_it_has_none(monkeypatch):
    rows = [row("A", cap=300.0), row("B", cap=100.0), row("C", cap=100.0, indices=("SPX", "NDX"))]
    histories = {"A": flat(5.0), "B": flat(10.0), "C": flat(8.0)}
    _histories(monkeypatch, histories)
    holdings = {"IWD": _holdings([("A", 0.6), ("B", 0.4)]), "IWF": _holdings([("C", 1.0)])}
    pairs = [
        {"key": "sp", "label": "SP", "big": "SPY", "small": "RSP", "big_basket": "index:SPX", "small_basket": "index:SPX:equal"},
        {"key": "vg", "label": "VG", "big": "IWD", "small": "IWF", "big_basket": "holdings:IWD", "small_basket": "holdings:IWF",
         "big_basket_label": "IWD · Russell 1000 Value", "small_basket_label": "IWF · Russell 1000 Growth"},
        {"key": "sm", "label": "SM", "big": "SPY", "small": "IWM", "fundamentals_note": "Small companies have no filings universe."},
    ]
    panel, ctx = _panel(monkeypatch, pairs, rows, holdings)

    sp, vg, sm = panel["views"]
    assert [a["label"] for a in sp["fundamentals"]["arms"]] == ["S&P 500 cap-weighted", "S&P 500 equal-weight"]
    assert vg["fundamentals"]["arms"][0]["label"] == "IWD · Russell 1000 Value"
    assert vg["fundamentals"]["arms"][0]["fund_coverage"] == pytest.approx(1.0)
    assert vg["fundamentals"]["arms"][1]["fund_coverage"] == pytest.approx(1.0)
    assert "fundamentals" not in sm and sm["fundamentals_note"] == "Small companies have no filings universe."
    assert panel["inputs"]["valuation_built"] is True
    assert [r.source_id for r in ctx.log.records if r.source_id.endswith("_holdings")] == ["sizek_iwd_holdings", "sizek_iwf_holdings"]
    json.dumps(panel, allow_nan=False)


def test_the_panel_without_valuation_marks_every_basket_pair_missing_and_fetches_nothing(monkeypatch):
    monkeypatch.setattr(P.ishares, "fetch_holdings", _no_fetch)
    pairs = [{"key": "vg", "label": "VG", "big": "IWD", "small": "IWF", "big_basket": "holdings:IWD", "small_basket": "holdings:IWF"}]
    idx = pd.bdate_range("2021-01-04", periods=900)
    cfg = {**load_config(), "sizek": {"history_years": 5, "price_periods": ["1M"], "gap_period": "1Y", "pairs": pairs}}
    ctx = _Ctx(cfg, as_of=idx[-1].date().isoformat())
    monkeypatch.setattr(P.yahoo, "fetch_closes", lambda syms, **k: pd.DataFrame({s: np.linspace(100, 110, len(idx)) for s in syms}, index=idx))
    panel = P.build(ctx)
    assert panel["views"][0]["fundamentals"] == {"missing": KP.NO_VALUATION}
    assert panel["inputs"]["valuation_built"] is False


# --- the validator -------------------------------------------------------------------

def test_validate_flags_a_basket_pair_without_its_block_and_notes_a_missing_one():
    config = {"sizek": {"pairs": [
        {"key": "vg", "big_basket": "holdings:IWD", "small_basket": "holdings:IWF"},
        {"key": "sp", "big_basket": "index:SPX", "small_basket": "index:SPX:equal"},
        {"key": "sm", "fundamentals_note": "n"}]}}
    payload = {"views": [
        {"key": "vg", "fundamentals": {"missing": "IWD's holdings could not be fetched."}},
        {"key": "sp"},
        {"key": "sm"}]}
    findings = [f.as_dict() for f in V._check_sizek(config, payload)]
    assert {"severity": "notice", "check": "sizek", "detail": "vg: IWD's holdings could not be fetched."} in findings
    assert {"severity": "error", "check": "sizek", "detail": "sp names baskets but has no fundamentals block"} in findings
    assert len(findings) == 2
    assert V._check_sizek(config, None) == []
