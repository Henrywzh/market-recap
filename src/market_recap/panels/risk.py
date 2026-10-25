"""RISK tab: how much risk the market is pricing, one tile per series.

Sources are Cboe's index files and VIX futures, FRED, Yahoo, the CFTC's TFF
report and the members' own closes (docs/risk_sources.md has the probe of each);
the valuation tiles add Shiller's CAPE data and Damodaran's implied ERP, each
named beside its values.
A source that fails leaves its tiles empty with the reason; the others render.
Nothing is combined into a score: see compute.risk.
"""

from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Callable

import numpy as np
import pandas as pd

from ..compute import anchor as A
from ..compute import risk as R
from ..compute import sentiment as S
from ..config import ARTIFACT_DIR
from ..sources import cboe, cftc, damodaran, fred, shiller, snapshot_store, treasury, yahoo
from ..util import SourceRecord, describe_error, to_iso_date, write_json

CBOE_INDICES = ("VIX", "VIX9D", "VIX3M", "VIX6M", "VIX1Y", "VVIX", "SKEW", "COR1M")
# Cboe's secondary indices were launched after their first row; the earlier
# part is Cboe's back-calculation (cboe module docstring).
BACKCALC = {"VIX9D", "VIX3M", "VIX6M", "VIX1Y", "VVIX", "SKEW", "COR1M"}
FRED_SERIES = {
    "BAA10Y": "Moody's Baa corporate yield relative to 10-year Treasury",
    "BAMLH0A0HYM2": "ICE BofA US High Yield OAS",
    "BAMLC0A0CM": "ICE BofA US Corporate (IG) OAS",
    "BAMLH0A3HYC": "ICE BofA CCC & lower OAS",
    "WALCL": "Fed total assets (weekly)",
    "WTREGEN": "Treasury General Account (weekly)",
    "RRPONTSYD": "Overnight reverse repo (daily)",
    "NFCI": "Chicago Fed NFCI (weekly)",
    "DFII10": "10-year TIPS real yield",
    "OVXCLS": "Cboe crude oil volatility (OVX)",
    "DGS10": "10-year Treasury yield",
    "THREEFYTP10": "Kim-Wright 10-year term premium",
}
ARCHIVED_ICE = ("BAMLH0A0HYM2", "BAMLC0A0CM", "BAMLH0A3HYC")
YAHOO_SYMBOLS = ("^MOVE", "HYG", "IEF", "LQD", "^GSPC", "DX-Y.NYB", "HG=F", "CL=F")
DOLLAR_WINDOW = 63
# Changes the matrix reads as leads (sessions back), not tiles of their own:
# BAA - 10Y over a month, and the real yield over three months.
HY_OAS_CHANGE_SESSIONS = 20
REAL_YIELD_CHANGE_SESSIONS = 63
CFTC_CODES = {"cftc_es": "13874A", "cftc_nq": "209742", "cftc_zn": "043602", "cftc_vx": "1170E1"}
PUT_CALL_FIELD = "TOTAL PUT/CALL RATIO"
PUT_CALL_BUDGET_SECONDS = 240
# How many expired VIX futures are read to give the front-month spread a year of history.
VX_HISTORY_MONTHS = 13
TERM_TENORS = {"9D": "VIX9D", "30D": "VIX", "3M": "VIX3M", "6M": "VIX6M", "1Y": "VIX1Y"}
# Matrix leads that are derived series rather than tiles: their label, unit and
# risk direction live here, as a tile's would in [[risk.tiles]].
# Credit's speed is read on Moody's BAA - 10Y: ICE's HY index on FRED reaches back
# only three years, too short for a 10-year percentile of its 20-session change.
DERIVED_LEADS = {"baa10y_4w": {"label": "BAA − 10Y · 20D CHANGE", "unit": "bp", "risk_when": "high"},
                 "real_10y_3m": {"label": "10Y REAL YIELD · 3M CHANGE", "unit": "bp", "risk_when": "high"}}


class _Inputs:
    """Fetches each input once, remembering failures by source."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.cboe: dict[str, pd.Series] = {}
        self.fred: dict[str, pd.Series] = {}
        self.yahoo = pd.DataFrame()
        self.cftc = pd.DataFrame()
        self.vx = pd.DataFrame()
        self.put_call = pd.Series(dtype=float)
        self.shiller = pd.DataFrame()
        self.damodaran = pd.Series(dtype=float)
        self.auctions = pd.DataFrame()
        self.failed: dict[str, str] = {}

    def load(self, settings: dict) -> None:
        ctx = self.ctx
        session = date.fromisoformat(ctx.as_of) if ctx.as_of else None
        for symbol in CBOE_INDICES:
            try:
                self.cboe[symbol] = cboe.fetch_index(symbol, session=session)
            except Exception as exc:
                self.failed[f"cboe {symbol}"] = describe_error(exc)
        self._log("cboe_indices", "Cboe index histories (VIX family, VVIX, SKEW, COR1M)", cboe.HOME_URL,
                  [s.index[-1] for s in self.cboe.values() if not s.empty], len(self.cboe), len(CBOE_INDICES))

        for series_id in FRED_SERIES:
            try:
                frame, _ = fred.fetch_series(series_id)
                self.fred[series_id] = frame.set_index("date")["value"]
            except Exception as exc:
                self.failed[f"fred {series_id}"] = describe_error(exc)
        # FRED serves the ICE spreads for three years only; the site's own
        # archive (snapshots/risk.py) keeps what it served before, and
        # supplies the dates FRED no longer does. FRED wins where both exist.
        for series_id in ARCHIVED_ICE:
            older = snapshot_store.risk_archive("fred", series_id)
            current = self.fred.get(series_id, pd.Series(dtype=float))
            if older.empty:
                continue
            if not current.empty:
                older = older[older.index < pd.to_datetime(current.index).min()]
            self.fred[series_id] = pd.concat([older, current]).sort_index()
        self._log("fred_risk", "FRED: credit spreads, Fed balance sheet, NFCI, real yield, OVX",
                  "https://fred.stlouisfed.org", [s.index[-1] for s in self.fred.values() if not s.empty],
                  len(self.fred), len(FRED_SERIES), policy="weekly_release")

        try:
            self.yahoo = yahoo.fetch_closes(YAHOO_SYMBOLS, period="max")
            if ctx.as_of and not self.yahoo.empty:
                # Never a session the rest of the page has not reached.
                self.yahoo = self.yahoo.loc[: pd.Timestamp(ctx.as_of)]
        except Exception as exc:
            self.failed["yahoo"] = describe_error(exc)
        missing = [s for s in YAHOO_SYMBOLS if s not in self.yahoo.columns]
        for symbol in missing:
            self.failed[f"yahoo {symbol}"] = "no closes returned"
        self._log("yahoo_risk", "Yahoo: MOVE, HYG, IEF, LQD, S&P 500, dollar index, copper and crude closes", "https://finance.yahoo.com",
                  [self.yahoo.index[-1]] if not self.yahoo.empty else [], len(YAHOO_SYMBOLS) - len(missing), len(YAHOO_SYMBOLS))

        try:
            self.cftc = cftc.fetch_tff(list(CFTC_CODES.values()), start=str(settings.get("cftc_start", "2006-01-01")))
        except Exception as exc:
            self.failed["cftc"] = describe_error(exc)
        self._log("cftc_tff", "CFTC Traders in Financial Futures (leveraged money)", cftc.HOME_URL,
                  [self.cftc["date"].max()] if not self.cftc.empty else [], 1 if not self.cftc.empty else 0, 1,
                  policy="weekly_release")

        self._load_valuation()
        self._load_auctions()
        self._load_vx(int(settings.get("vx_contracts", 8)), session)
        self._load_put_call(int(settings.get("put_call_sessions", 260)))

    def _load_valuation(self) -> None:
        """Shiller's CAPE data and Damodaran's implied ERP: monthly research datasets."""
        try:
            self.shiller = shiller.fetch()
        except Exception as exc:
            self.failed["shiller"] = describe_error(exc)
        rows = self.shiller.dropna(subset=["cape"]) if not self.shiller.empty else self.shiller
        self._log("shiller", shiller.ATTRIBUTION, shiller.HOME_URL, [rows.index[-1]] if not rows.empty else [],
                  0 if rows.empty else 1, 1, policy="monthly_release")
        try:
            self.damodaran = damodaran.fetch()
        except Exception as exc:
            self.failed["damodaran"] = describe_error(exc)
        self._log("damodaran", damodaran.ATTRIBUTION, damodaran.HOME_URL,
                  [self.damodaran.index[-1]] if not self.damodaran.empty else [],
                  0 if self.damodaran.empty else 1, 1, policy="monthly_release")

    def _load_auctions(self) -> None:
        """Treasury's coupon auction results since 2008, for the auction-demand cell."""
        try:
            self.auctions = R.auction_demand(treasury.fetch_auction_history())
        except Exception as exc:
            self.failed["treasury auctions"] = describe_error(exc)
        # Coupon auctions cluster in two weeks of each month (3/10/30-year early,
        # 2/5/7-year late) and Fiscal Data posts results a few days after: a
        # two-week gap with no complete result is routine (2026-10-08 to -24).
        self._log("treasury_auctions_risk", "Treasury auction results (bid-to-cover, dealer share)", treasury.AUCTIONS_PAGE,
                  [self.auctions.index[-1]] if not self.auctions.empty else [], 0 if self.auctions.empty else 1, 1,
                  policy="biweekly_release")

    def _load_vx(self, count: int, session: date | None = None) -> None:
        today = date.today()
        expiries = cboe.vx_expiries(today - timedelta(days=31 * VX_HISTORY_MONTHS), count + VX_HISTORY_MONTHS)
        frames, missing = [], []
        for expiry in expiries:
            try:
                frames.append(cboe.fetch_vx(expiry, session=session))
            except Exception:
                missing.append(expiry.isoformat())
        self.vx = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if missing and len(missing) == len(expiries):
            self.failed["cboe VX"] = "no VIX futures file answered"
        self._log("cboe_vx", "Cboe VIX futures daily settlements", "https://www.cboe.com/us/futures/market_statistics/historical_data/",
                  [self.vx["trade_date"].max()] if not self.vx.empty else [], len(frames), len(expiries))

    def _load_put_call(self, sessions: int) -> None:
        days = [d.date() for d in self.ctx.closes.index[-sessions:]] if not self.ctx.closes.empty else []
        today = days[-1] if days else date.today()
        values: dict[pd.Timestamp, float] = {}
        started = time.monotonic()
        for day in reversed(days):
            if time.monotonic() - started > PUT_CALL_BUDGET_SECONDS:
                self.failed["cboe put/call"] = f"time budget reached after {len(values)} sessions"
                break
            ratios = cboe.fetch_put_call(day, today=today)
            if ratios and ratios.get(PUT_CALL_FIELD):
                values[pd.Timestamp(day)] = ratios[PUT_CALL_FIELD]
        self.put_call = pd.Series(values).sort_index()
        self._log("cboe_put_call", "Cboe daily put/call ratios", "https://www.cboe.com/us/options/market_statistics/daily/",
                  [self.put_call.index[-1]] if not self.put_call.empty else [], len(self.put_call), len(days))

    def _log(self, source_id: str, label: str, url: str, dates: list, got: int, wanted: int,
             *, policy: str = "daily_close") -> None:
        self.ctx.log.add(SourceRecord(
            source_id, label, url, to_iso_date(max(dates)) if dates else None, rows=got, policy=policy,
            status="ok" if got == wanted else ("partial" if got else "error"),
            error=None if got == wanted else f"{wanted - got} of {wanted} did not answer",
        ))

    # --- series ------------------------------------------------------------------

    def yahoo_close(self, symbol: str) -> pd.Series:
        return self.yahoo[symbol].dropna() if symbol in self.yahoo.columns else pd.Series(dtype=float)

    def spx(self) -> pd.Series:
        """The build's index closes, extended back with Yahoo's full history so
        the long percentiles span more than one cycle. The build's own closes
        win where both exist, and nothing after the page's session is used."""
        closes = self.ctx.index_closes
        symbol = self.ctx.primary.symbol
        own = closes[symbol].dropna() if symbol in closes.columns else pd.Series(dtype=float)
        longer = self.yahoo_close(symbol)
        if longer.empty:
            return own
        if not own.empty:
            longer = longer[longer.index < own.index[0]]
            return pd.concat([longer, own]).sort_index()
        return longer[longer.index <= pd.Timestamp(self.ctx.as_of)] if self.ctx.as_of else longer

    def vx_front(self) -> pd.Series:
        """Settle of the nearest unexpired monthly contract on each trade date."""
        if self.vx.empty:
            return pd.Series(dtype=float)
        frame = self.vx.copy()
        frame = frame[pd.to_datetime(frame["expiry"]) > frame["trade_date"]]
        frame = frame.sort_values(["trade_date", "expiry"]).groupby("trade_date").first()
        return frame["settle"]

    def vx_curve(self) -> dict:
        """Settlements by expiry today, a week and a month ago (unexpired contracts only)."""
        if self.vx.empty:
            return {"curves": []}
        last = self.vx["trade_date"].max()
        curves = []
        for lag in (0, 7, 30):
            day = self.vx.loc[self.vx["trade_date"] <= last - timedelta(days=lag), "trade_date"].max()
            if pd.isna(day):
                continue
            rows = self.vx[(self.vx["trade_date"] == day) & (pd.to_datetime(self.vx["expiry"]) > day)]
            rows = rows.sort_values("expiry").head(8)
            curves.append({
                "lag_days": lag, "date": day.strftime("%Y-%m-%d"),
                "expiries": rows["expiry"].tolist(),
                "days": [(pd.Timestamp(e) - day).days for e in rows["expiry"]],
                "settles": [round(float(v), 2) for v in rows["settle"]],
            })
        return {"curves": curves}

    def cftc_net(self, code: str) -> pd.Series:
        if self.cftc.empty:
            return pd.Series(dtype=float)
        rows = self.cftc[self.cftc["code"] == code]
        return rows.set_index("date")["net_pct_oi"].dropna()


def _builders(inputs: _Inputs) -> dict[str, Callable[[], pd.Series]]:
    c, f = inputs.cboe, inputs.fred
    get = lambda d, k: d.get(k, pd.Series(dtype=float))
    members = inputs.ctx.priced(inputs.ctx.primary.key)
    weights = members.drop_duplicates("yahoo_symbol").set_index("yahoo_symbol")["weight"].astype(float) \
        if not members.empty else pd.Series(dtype=float)
    member_closes = inputs.ctx.closes[[s for s in weights.index if s in inputs.ctx.closes.columns]] \
        if not weights.empty else pd.DataFrame()
    corr_disp: dict[str, pd.Series] = {}

    def corr(kind: str) -> pd.Series:
        if not corr_disp and not member_closes.empty:
            corr_disp["corr"], corr_disp["disp"] = R.correlation_and_dispersion(member_closes, weights)
        return corr_disp.get(kind, pd.Series(dtype=float))

    rv = lambda: R.realised_vol(inputs.spx())
    return {
        "vix": lambda: get(c, "VIX"),
        "vix_term": lambda: R.ratio(get(c, "VIX"), get(c, "VIX3M")),
        "vix9d_term": lambda: R.ratio(get(c, "VIX9D"), get(c, "VIX")),
        "vvix": lambda: get(c, "VVIX"),
        "skew": lambda: get(c, "SKEW"),
        "rv20": rv,
        "vrp": lambda: (get(c, "VIX") - rv()).dropna(),
        "vx_front": lambda: (inputs.vx_front() - get(c, "VIX")).dropna(),
        "move": lambda: inputs.yahoo_close("^MOVE"),
        "ovx": lambda: get(f, "OVXCLS"),
        "hyg_ief": lambda: R.vs_moving_average(R.ratio(inputs.yahoo_close("HYG"), inputs.yahoo_close("IEF")), R.CREDIT_TREND_WINDOW),
        "lqd_ief": lambda: R.vs_moving_average(R.ratio(inputs.yahoo_close("LQD"), inputs.yahoo_close("IEF")), R.CREDIT_TREND_WINDOW),
        "baa10y": lambda: get(f, "BAA10Y") * 100,
        "hy_oas": lambda: get(f, "BAMLH0A0HYM2") * 100,
        "baa10y_4w": lambda: R.change_over(get(f, "BAA10Y") * 100, HY_OAS_CHANGE_SESSIONS),
        "real_10y_3m": lambda: R.change_over(get(f, "DFII10") * 100, REAL_YIELD_CHANGE_SESSIONS),
        "ecy": lambda: R.excess_cape_yield(inputs.spx(), get(f, "DGS10"), inputs.shiller),
        "erp_damodaran": lambda: inputs.damodaran,
        "term_premium": lambda: get(f, "THREEFYTP10"),
        "stock_bond_corr": lambda: R.stock_bond_correlation(inputs.spx(), get(f, "DGS10")),
        "auction_btc": lambda: inputs.auctions.get("bid_to_cover", pd.Series(dtype=float)).dropna(),
        "auction_dealer": lambda: inputs.auctions.get("dealer_share", pd.Series(dtype=float)).dropna(),
        "ig_oas": lambda: get(f, "BAMLC0A0CM") * 100,
        "ccc_oas": lambda: get(f, "BAMLH0A3HYC") * 100,
        "cor1m": lambda: get(c, "COR1M"),
        "realised_corr": lambda: corr("corr"),
        "dispersion": lambda: corr("disp"),
        "spx_vs_200d": lambda: R.vs_moving_average(inputs.spx(), 200),
        "spx_drawdown": lambda: R.drawdown_from_high(inputs.spx()),
        "breadth_200d": lambda: R.share_above_average(member_closes) if not member_closes.empty else pd.Series(dtype=float),
        "net_liquidity": lambda: R.change_over(R.net_liquidity(get(f, "WALCL"), get(f, "WTREGEN"), get(f, "RRPONTSYD")),
                                               R.LIQUIDITY_CHANGE_WEEKS),
        "nfci": lambda: get(f, "NFCI"),
        "real_10y": lambda: get(f, "DFII10"),
        **{key: (lambda code=code: inputs.cftc_net(code)) for key, code in CFTC_CODES.items()},
        "put_call": lambda: R.smoothed(inputs.put_call, R.PUT_CALL_SMOOTHING),
        "dxy_3m": lambda: R.pct_change_over(inputs.yahoo_close("DX-Y.NYB"), DOLLAR_WINDOW),
        # The anchor's own gate input, so the tile and the anchor cannot disagree.
        "copper_oil": lambda: copper_oil_z(inputs.yahoo_close("HG=F"), inputs.yahoo_close("CL=F")),
    }


def copper_oil_z(copper: pd.Series, oil: pd.Series) -> pd.Series:
    both = pd.concat([copper, oil], axis=1).dropna()
    if both.empty:
        return pd.Series(dtype=float)
    return A.copper_oil(both.iloc[:, 0], both.iloc[:, 1], both.index, lag=0)["z"].dropna()


# Which raw inputs each tile rests on, for its source line and back-calculation note.
TILE_SOURCES = {
    "vix": ["Cboe VIX"], "vix_term": ["Cboe VIX", "Cboe VIX3M"], "vix9d_term": ["Cboe VIX9D", "Cboe VIX"],
    "vvix": ["Cboe VVIX"], "skew": ["Cboe SKEW"], "rv20": ["S&P 500 closes"], "vrp": ["Cboe VIX", "S&P 500 closes"],
    "vx_front": ["Cboe VX futures", "Cboe VIX"], "move": ["Yahoo ^MOVE"], "ovx": ["FRED OVXCLS"],
    "hyg_ief": ["Yahoo HYG, IEF"], "lqd_ief": ["Yahoo LQD, IEF"], "baa10y": ["FRED BAA10Y"],
    "hy_oas": ["FRED BAMLH0A0HYM2"], "ig_oas": ["FRED BAMLC0A0CM"], "ccc_oas": ["FRED BAMLH0A3HYC"],
    "cor1m": ["Cboe COR1M"], "realised_corr": ["S&P 500 member closes, SPY weights"],
    "dispersion": ["S&P 500 member closes, SPY weights"], "spx_vs_200d": ["S&P 500 closes"],
    "spx_drawdown": ["S&P 500 closes"], "breadth_200d": ["S&P 500 member closes"],
    "net_liquidity": ["FRED WALCL, WTREGEN, RRPONTSYD"], "nfci": ["FRED NFCI"], "real_10y": ["FRED DFII10"],
    "cftc_es": ["CFTC TFF 13874A"], "cftc_nq": ["CFTC TFF 209742"], "cftc_zn": ["CFTC TFF 043602"],
    "cftc_vx": ["CFTC TFF 1170E1"], "put_call": ["Cboe daily put/call"],
    "dxy_3m": ["Yahoo DX-Y.NYB"], "copper_oil": ["Yahoo HG=F, CL=F"],
    "ecy": [shiller.ATTRIBUTION, "S&P 500 closes", "FRED DGS10"], "erp_damodaran": [damodaran.ATTRIBUTION],
    "term_premium": ["FRED THREEFYTP10 (Kim and Wright, Federal Reserve Board)"],
    "stock_bond_corr": ["S&P 500 closes", "FRED DGS10"],
    "auction_btc": ["Treasury auction results (fiscaldata)"], "auction_dealer": ["Treasury auction results (fiscaldata)"],
}
TILE_BACKCALC = {"vix_term": "VIX3M", "vix9d_term": "VIX9D", "vvix": "VVIX", "skew": "SKEW", "cor1m": "COR1M"}
# Auction series move only on auction days, about weekly.
WEEKLY_TILES = {"net_liquidity", "nfci", "cftc_es", "cftc_nq", "cftc_zn", "cftc_vx", "auction_btc", "auction_dealer"}
# Published once a month: no one-session or one-week change, and a matrix lead
# from one is allowed a month and a half before it is stale.
MONTHLY_TILES = {"erp_damodaran"}
DIGITS = {"ratio": 3, "corr": 2, "pct_oi": 1, "bp": 0, "usd_bn": 0}


def _sentiment(inputs: _Inputs) -> dict:
    """The self-computed Fear & Greed gauge (compute.sentiment)."""
    ctx = inputs.ctx
    members = ctx.priced(ctx.primary.key)
    symbols = [s for s in members["yahoo_symbol"].drop_duplicates() if s in ctx.closes.columns] if not members.empty else []
    closes = ctx.closes[symbols]
    spx = inputs.spx()
    raw = {
        "momentum": S.momentum(spx),
        "strength": S.strength(closes) if symbols else pd.Series(dtype=float),
        "breadth": S.mcclellan_summation(closes) if symbols else pd.Series(dtype=float),
        "put_call": R.smoothed(inputs.put_call, R.PUT_CALL_SMOOTHING) if not inputs.put_call.empty else pd.Series(dtype=float),
        "volatility": S.vs_average(inputs.cboe.get("VIX", pd.Series(dtype=float))),
        "safe_haven": S.safe_haven(spx, inputs.yahoo_close("IEF")),
        "junk_bond": S.junk_spread(inputs.fred.get("BAMLH0A0HYM2", pd.Series(dtype=float)),
                                   inputs.fred.get("BAMLC0A0CM", pd.Series(dtype=float))),
    }
    calendar = spx.index[spx.index > spx.index[-1] - pd.Timedelta(days=3 * 365)]
    # The whole calendar as history, so the page's range switch can reach
    # past one year where the components allow.
    return S.gauge(raw, calendar, history_sessions=len(calendar))


def vix_context(series: pd.Series, as_of: str | None) -> dict:
    """The daily Cboe VIX closes MOVE CHECK reads for episode context: finite
    values only, rounded to cents, cut at the page's session."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    clean = clean[np.isfinite(clean.to_numpy(dtype=float))]
    if as_of:
        clean = clean[clean.index <= pd.Timestamp(as_of)]
    return {
        "as_of": as_of,
        "source": "Cboe VIX",
        "dates": [d.strftime("%Y-%m-%d") for d in pd.to_datetime(clean.index)],
        "close": [round(float(v), 2) for v in clean.to_numpy(dtype=float)],
    }


def _write_vix_context(ctx, inputs: _Inputs) -> None:
    """Writes context/vix.json for MOVE CHECK. It is optional, so a failure only logs."""
    try:
        write_json(ARTIFACT_DIR / "context" / "vix.json",
                   vix_context(inputs.cboe.get("VIX", pd.Series(dtype=float)), ctx.as_of))
    except Exception as exc:  # noqa: BLE001 - the context is optional; RISK still renders
        ctx.log.fail("risk:vix_context", exc)


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _lead_series(lead: str, series_of: dict, builders: dict) -> pd.Series:
    """A lead's full series: a tile's own, or built now for a derived lead."""
    if lead not in series_of:
        series_of[lead] = builders[lead]()
    return series_of[lead]


def _matrix_cell(row: str, column: str, spec: dict, *, tiles: dict, series_of: dict, builders: dict,
                 cfg: dict, as_of: str | None) -> dict:
    """One row x column cell. A cell with no lead is a placeholder and shows its pending text."""
    lead = spec.get("lead")
    cell = {"row": row, "column": column, "lead": lead, "label": None, "value": None, "unit": None,
            "date": None, "risk_when": None, "percentile": None, "state": "grey", "state_prev": None,
            "change_1m": None, "worse_1m": None, "scale": spec.get("scale", "percentile"),
            "bands": spec.get("bands"), "evidence": spec.get("evidence", "description"),
            "caution": spec.get("caution"), "note": spec.get("note"),
            "pending": spec.get("pending", None if lead else "—"), "members": list(spec.get("members", []))}
    if not lead:
        return cell
    meta = dict(tiles.get(lead) or DERIVED_LEADS[lead])
    # A cell may read its lead the other way round: a credit spread is stress
    # when wide (its tile) and a thin premium, a rich market, when tight (VALUATION).
    meta["risk_when"] = spec.get("risk_when", meta["risk_when"])
    # A weekly series is allowed a longer gap before it is stale, as its tile is read weekly.
    stale_days = (cfg["stale_days_monthly"] if lead in MONTHLY_TILES
                  else cfg["stale_days_weekly"] if lead in WEEKLY_TILES else cfg["stale_days_daily"])
    try:
        series = _lead_series(lead, series_of, builders)
    except Exception:  # noqa: BLE001 - a lead that did not build leaves its cell grey, never the panel
        series = pd.Series(dtype=float)
    reading = R.matrix_reading(series, risk_when=meta["risk_when"], as_of=as_of, years=cfg["years"],
                               min_years=cfg["min_years"], stale_days=stale_days,
                               thresholds={"elevated": cfg["elevated"], "stressed": cfg["stressed"]},
                               scale=cell["scale"], bands=cell["bands"],
                               since=spec.get("since", cfg.get("valuation_since")),
                               valuation=cfg.get("valuation"))
    if cell["scale"] == "valuation":
        # The span actually read: the configured start, or the series' own first year if later.
        since = pd.Timestamp(spec.get("since", cfg.get("valuation_since")))
        first = series.dropna().index.min() if not series.dropna().empty else since
        cell["since"] = max(since, pd.Timestamp(first)).strftime("%Y-%m-%d")
    digits = DIGITS.get(meta["unit"], 2)
    cell.update(reading)
    cell.update({"label": meta["label"], "unit": meta["unit"], "risk_when": meta["risk_when"],
                 "value": _round(reading["value"], digits), "change_1m": _round(reading["change_1m"], digits)})
    return cell


def _matrix(settings: dict, builders: dict, series_of: dict, as_of: str | None) -> dict:
    """The RISK matrix: one cell per row and column, each read from its own lead."""
    cfg = settings["matrix"]
    tiles = {t["key"]: t for t in settings.get("tiles", [])}
    specs = {(c["row"], c["column"]): c for c in cfg.get("cells", [])}
    cells = [_matrix_cell(row["key"], column["key"], specs.get((row["key"], column["key"]), {}), tiles=tiles,
                          series_of=series_of, builders=builders, cfg=cfg, as_of=as_of)
             for row in cfg["rows"] for column in cfg["columns"]]
    return {
        "thresholds": {"elevated": cfg["elevated"], "stressed": cfg["stressed"]},
        "valuation": cfg.get("valuation"),
        "years": cfg["years"],
        "rows": [{"key": r["key"], "label": r["label"]} for r in cfg["rows"]],
        "columns": [{"key": c["key"], "label": c["label"]} for c in cfg["columns"]],
        "cells": cells,
    }


def build(ctx) -> dict:
    settings = ctx.config.get("risk", {})
    inputs = _Inputs(ctx)
    inputs.load(settings)
    _write_vix_context(ctx, inputs)
    builders = _builders(inputs)

    sections = []
    # Each tile's full series, kept for the matrix: its leads are read from these.
    series_of: dict[str, pd.Series] = {}
    for section in settings.get("sections", []):
        tiles = []
        for spec in (t for t in settings.get("tiles", []) if t["section"] == section["key"]):
            key = spec["key"]
            builder = builders.get(key)
            try:
                series = builder() if builder else pd.Series(dtype=float)
                series_of[key] = series
                reading = R.tile(series, risk_when=spec["risk_when"], threshold=spec.get("threshold"),
                                 digits=DIGITS.get(spec.get("unit"), 2),
                                 daily=key not in WEEKLY_TILES and key not in MONTHLY_TILES)
                error = None if reading.get("value") is not None else "no observations"
            except Exception as exc:
                reading, error = {"value": None, "date": None}, describe_error(exc)
            backcalc = TILE_BACKCALC.get(key)
            tiles.append({
                "key": key,
                "core": bool(spec.get("core")),
                "label": spec["label"],
                "unit": spec.get("unit"),
                "risk_when": spec["risk_when"],
                "threshold": spec.get("threshold"),
                "note": spec.get("note"),
                "sources": TILE_SOURCES.get(key, []),
                "frequency": "monthly" if key in MONTHLY_TILES else "weekly" if key in WEEKLY_TILES else "daily",
                "backcalc": (f"{backcalc}'s early history is Cboe's back-calculation, not a record published at the time"
                             if backcalc in BACKCALC else None),
                "error": error,
                **reading,
            })
        sections.append({**section, "tiles": tiles})

    charts = {
        "vix_term": R.term_structure({tenor: inputs.cboe.get(symbol, pd.Series(dtype=float))
                                      for tenor, symbol in TERM_TENORS.items()}),
        "vx_curve": inputs.vx_curve(),
    }
    breaches = [
        {"key": t["key"], "label": t["label"], "section": s["key"], "horizon": s["horizon"],
         "value": t["value"], "unit": t["unit"], "crossed": t.get("crossed")}
        for s in sections for t in s["tiles"] if t.get("breach")
    ]
    crossed = [
        {"key": t["key"], "label": t["label"], "section": s["key"], "horizon": s["horizon"],
         "value": t["value"], "unit": t["unit"], "crossed": t["crossed"]}
        for s in sections for t in s["tiles"] if t.get("crossed")
    ]
    try:
        sentiment = _sentiment(inputs)
    except Exception as exc:
        sentiment = {"score": None, "error": describe_error(exc), "components": [], "history": {"dates": [], "score": []}}
    return {
        "as_of": ctx.as_of,
        "sections": sections,
        "matrix": _matrix(settings, builders, series_of, ctx.as_of),
        "sentiment": sentiment,
        "charts": charts,
        "breaches": breaches,
        "crossed": crossed,
        "failed": inputs.failed,
    }
