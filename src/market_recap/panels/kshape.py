"""RELATIVE VALUE -> K-SHAPE: high-income legs against low-income legs.

For each configured pair (cruise, airlines, homebuilders, casinos, cards) and
for all of them together: the two legs' price index and their ratio, the
median trailing P/E of each leg and its ratio through time, the median growth
of trailing EPS, and a table of the names with their forward P/E, where it
sits in its own history, consensus EPS growth and revenue growth. Each ratio
carries where today's value sits in its own history. The legs are named in
the config by judgment; see compute.kshape.

The P/E and EPS histories come from this session's VALUATION artifacts (SEC
filings and closes); a name VALUATION does not cover has prices only, and a
build without VALUATION shows prices only. Nothing is filled in.

Each view also carries ``fundamentals``: each leg as an equal-weight basket of
its names (compute.baskets), so the leg ratio's P/E and earnings parts are the
same measured figures the page's P/E chart shows. The arm helpers here are
shared with SIZE K (panels.sizek).
"""

from __future__ import annotations

import json

import pandas as pd

from ..compute import baskets as B
from ..compute import kshape as K
from ..compute import valuation as V
from ..config import PERIOD_TRADING_DAYS, VALUATION_ARTIFACT_DIR
from ..context import YAHOO_URL
from ..sources import estimates, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

INPUTS = ("valuation",)
DAILY_DAYS = 365


def _thin(frame: pd.DataFrame, years: int) -> pd.DataFrame:
    """The last ``DAILY_DAYS`` daily, older weeks' last observation (and the first row), within ``years``."""
    frame = frame.sort_index()
    if frame.empty:
        return frame
    last = frame.index[-1]
    frame = frame[frame.index > last - pd.DateOffset(years=years)]
    cut = last - pd.Timedelta(days=DAILY_DAYS)
    older = frame[frame.index <= cut]
    first = older.iloc[:1]                  # the series' own start survives the thinning: a ratio rebased there begins at 1
    older = older.groupby(older.index.to_period("W-FRI")).tail(1)
    return pd.concat([first[~first.index.isin(older.index)], older, frame[frame.index > cut]]).sort_index()


def _series_payload(frame: pd.DataFrame, years: int, digits: int = 2) -> dict:
    thin = _thin(frame, years)
    return {"dates": [d.strftime("%Y-%m-%d") for d in thin.index],
            **{col: [clean_float(v, digits) for v in thin[col]] for col in thin.columns}}


def _read_history(ticker: str) -> dict | None:
    path = VALUATION_ARTIFACT_DIR / f"{ticker}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _pe_series(history: dict | None) -> pd.Series | None:
    if not history or not history.get("dates") or not history.get("pe"):
        return None
    return pd.Series(history["pe"], index=pd.to_datetime(history["dates"]), dtype=float)


# --- Fundamentals: an arm as a basket of its names' P/E and earnings ------------------
# The same baskets the page's P/E charts are drawn from (compute.baskets), so a
# ratio of two arms splits into a ratio of multiples and a ratio of earnings.

FUNDAMENTAL_YEARS = 10     # the arms' history on the page, at most; the artifacts run back further
NO_VALUATION = ("The VALUATION tab was not built in this session, so there are no filings histories "
                "to build the baskets from.")


class Histories:
    """Each name's VALUATION history, read once per build, and the weekly closes
    and earnings yields of any set of names (compute.baskets.frames). A name
    without a history is absent from both frames. The frames are kept per set
    of names, since several arms share names."""

    def __init__(self) -> None:
        self._read: dict[str, dict | None] = {}
        self._frames: dict[frozenset, tuple[pd.DataFrame, pd.DataFrame]] = {}

    def frames(self, tickers) -> tuple[pd.DataFrame, pd.DataFrame]:
        key = frozenset(tickers)
        if key not in self._frames:
            for ticker in key:
                if ticker not in self._read:
                    self._read[ticker] = _read_history(ticker)
            self._frames[key] = B.frames({t: self._read[t] for t in sorted(key)})
        return self._frames[key]


def arm(key: str, label: str, names: list[str], closes: pd.DataFrame, yields: pd.DataFrame,
        weights: dict[str, float] | None = None, *, years: int, fund_coverage: float | None = None,
        note: str | None = None) -> tuple[dict, str | None]:
    """One arm of a fundamentals pair, and the reason it has no basket when it has none.

    A name takes part when it has a filings history in ``closes`` and, for a
    cap-weighted arm (``weights`` given), a positive weight. Names left out are
    listed in the arm's note rather than dropped silently: a basket that quietly
    has fewer names would look like the whole leg."""
    usable = [t for t in names if t in closes.columns and (weights is None or (weights.get(t) or 0) > 0)]
    left_out = [t for t in names if t not in usable]
    notes = [note] if note else []
    if left_out:
        why = "a filings history" if weights is None else "a filings history or a market cap"
        shown = ", ".join(left_out[:12]) + (f" and {len(left_out) - 12} more" if len(left_out) > 12 else "")
        notes.append(f"Left out for lack of {why}: {shown}.")
    basket, reason = None, None
    if not usable:
        reason = f"{label}: no name has a filings history, so no basket can be built."
    else:
        basket = B.payload(B.basket(closes[usable], yields.reindex(columns=usable), weights), years=years)
        if basket is None:
            reason = f"{label}: none of its names had a P/E from their filings, so no basket can be built."
    return {"key": key, "label": label, "basket": basket, "fund_coverage": clean_float(fund_coverage, 3),
            "note": " ".join(notes) or None}, reason


def fundamentals(built: list[tuple[dict, str | None]], notes: list[str] | None = None) -> dict:
    """The payload the page's cards read: both arms, or the reason they cannot be drawn.
    An arm with no basket makes the whole payload ``missing``: the cards need both."""
    reasons = [reason for _, reason in built if reason]
    if reasons:
        return {"missing": " ".join(reasons)}
    return {"arms": [a for a, _ in built], "notes": list(notes or [])}


def _leg_fundamentals(top: list[str], bottom: list[str], histories: dict, built: bool, years: int) -> dict:
    """Each leg as an equal-weight basket of its names with a filings history."""
    if not built:
        return {"missing": NO_VALUATION}
    closes, yields = B.frames({t: histories.get(t) for t in dict.fromkeys(top + bottom)})
    return fundamentals([arm("top", "Top leg", top, closes, yields, years=years),
                         arm("bottom", "Bottom leg", bottom, closes, yields, years=years)])


def _name_row(ticker: str, leg: str, closes: pd.DataFrame, valuation: dict, trends: dict, periods: dict[str, int],
              today: pd.Timestamp) -> dict:
    price = closes[ticker].dropna() if ticker in closes.columns else pd.Series(dtype=float)
    row = valuation.get(ticker) or {}
    eps_prev, eps_now = row.get("eps_fy_prev"), row.get("eps_fy0")      # last year's actual, this year's consensus
    out = {
        "ticker": ticker, "leg": leg,
        "price": clean_float(price.iloc[-1], 2) if len(price) else None,
        "first_price": to_iso_date(price.index[0]) if len(price) else None,
        "ret_3m": clean_float(K.period_return(price, periods["3M"]), 1),
        "ret_1y": clean_float(K.period_return(price, periods["1Y"]), 1),
        "pe_forward": clean_float(row.get("pe_forward"), 1),
        "pe_percentile": clean_float(row.get("pe_percentile"), 0),
        "eps_growth_this_year": clean_float((eps_now / eps_prev - 1) * 100, 1) if eps_prev and eps_now is not None and eps_prev > 0 else None,
        "revenue_growth": clean_float(row.get("revenue_growth"), 1),
        "operating_margin": clean_float(row.get("operating_margin"), 1),
        "net_debt_ebitda": clean_float(row.get("net_debt_ebitda"), 1),
        "has_valuation": bool(row), "forward_source": "valuation" if row else None,
    }
    if not row and ticker in trends and len(price):
        # Not in the valuation universe: forward P/E from the consensus alone (the
        # same NTM blend), growth from the consensus' last and this fiscal year.
        ntm = V.ntm_eps(trends[ticker], today)
        path = V.fiscal_path(trends[ticker], ntm)
        out["pe_forward"] = clean_float(V.forward_pe(float(price.iloc[-1]), ntm), 1)
        if path and path.get("fy_prev") and path["fy_prev"] > 0 and path.get("fy0") is not None:
            out["eps_growth_this_year"] = clean_float((path["fy0"] / path["fy_prev"] - 1) * 100, 1)
        out["forward_source"] = "consensus" if out["pe_forward"] is not None else None
    return out


def _view(key: str, label: str, note: str | None, top: list[str], bottom: list[str], *, closes: pd.DataFrame,
          valuation: dict, trends: dict, today: pd.Timestamp, histories: dict[str, dict | None], cfg: dict, periods: dict[str, int],
          valuation_built: bool) -> dict:
    years = int(cfg["history_years"])
    top_ix, bottom_ix = K.leg_index(closes, top), K.leg_index(closes, bottom)
    out: dict = {"key": key, "label": label, "note": note, "top": top, "bottom": bottom}
    out["fundamentals"] = _leg_fundamentals(top, bottom, histories, valuation_built, min(years, FUNDAMENTAL_YEARS))

    both = pd.concat([top_ix.rename("top"), bottom_ix.rename("bottom")], axis=1).dropna()
    if len(both) > 1:
        # Both rebased to 100 on the first day both are priced, so the ratio starts at 1.
        both = 100 * both / both.iloc[0]
        ratio = K.ratio(both["top"], both["bottom"])
        weekly = ratio.groupby(ratio.index.to_period("W-FRI")).tail(1)
        out["price"] = {
            **_series_payload(pd.DataFrame({"top": both["top"], "bottom": both["bottom"], "ratio": ratio}), years),
            "since": to_iso_date(both.index[0]),
            "ratio_now": clean_float(ratio.iloc[-1], 3),
            "ratio_percentile": clean_float(K.percentile(weekly, float(ratio.iloc[-1])), 0),
            "sessions": int(len(both)),
            "spreads": [{k: (clean_float(v, 1) if k != "period" else v) for k, v in r.items()}
                        for r in K.spread_table(both["top"], both["bottom"], periods)],
        }
    else:
        out["price"] = None

    pe_by = {t: _pe_series(histories.get(t)) for t in top + bottom}
    pe_by = {t: s for t, s in pe_by.items() if s is not None}
    covered = {"top": [t for t in top if t in pe_by], "bottom": [t for t in bottom if t in pe_by]}
    out["pe"] = None
    if covered["top"] and covered["bottom"]:
        pe_top = K.median_multiple(pe_by, covered["top"], min_share=cfg["pe_min_share"], cap=cfg["pe_cap"])
        pe_bottom = K.median_multiple(pe_by, covered["bottom"], min_share=cfg["pe_min_share"], cap=cfg["pe_cap"])
        pe_ratio = K.ratio(pe_top, pe_bottom)
        if len(pe_ratio) >= 2:
            frame = pd.DataFrame({"top": pe_top, "bottom": pe_bottom, "ratio": pe_ratio}).loc[pe_ratio.index]
            out["pe"] = {
                **_series_payload(frame, years),
                "covered": covered,
                "now": {"top": clean_float(pe_top.iloc[-1], 1), "bottom": clean_float(pe_bottom.iloc[-1], 1),
                        "ratio": clean_float(pe_ratio.iloc[-1], 2), "date": to_iso_date(pe_ratio.index[-1])},
                "ratio_median": clean_float(pe_ratio.median(), 2),
                "ratio_p10": clean_float(pe_ratio.quantile(0.1), 2),
                "ratio_p90": clean_float(pe_ratio.quantile(0.9), 2),
                "ratio_percentile": clean_float(K.percentile(pe_ratio, float(pe_ratio.iloc[-1])), 0),
                "dates_used": int(len(pe_ratio)),
            }

    growth_by = {t: K.eps_growth((histories.get(t) or {}).get("eps") or [], cap=cfg["eps_growth_cap"]) for t in top + bottom}
    g_top = K.median_growth(growth_by, [t for t in top if t in growth_by])
    g_bottom = K.median_growth(growth_by, [t for t in bottom if t in growth_by])
    quarters = g_top.index.intersection(g_bottom.index)
    out["eps"] = None
    if len(quarters) >= 2:
        frame = pd.DataFrame({"top": g_top.loc[quarters], "bottom": g_bottom.loc[quarters]})
        frame["gap"] = frame["top"] - frame["bottom"]
        out["eps"] = {**_series_payload(frame, years, 1), "latest": to_iso_date(quarters[-1])}

    names = [_name_row(t, leg, closes, valuation, trends, periods, today) for leg, members in (("top", top), ("bottom", bottom)) for t in members]
    out["names"] = names

    def med(leg_name: str, field: str) -> float | None:
        return K.median_of(r[field] for r in names if r["leg"] == leg_name)

    now = {f"{field}_{leg_name}": clean_float(med(leg_name, field), 1)
           for field in ("pe_forward", "eps_growth_this_year", "revenue_growth", "operating_margin")
           for leg_name in ("top", "bottom")}
    pf_t, pf_b = med("top", "pe_forward"), med("bottom", "pe_forward")
    now["pe_forward_ratio"] = clean_float(pf_t / pf_b, 2) if pf_t and pf_b else None
    out["now"] = now
    return out


def build(ctx, *, inputs: dict | None = None) -> dict:
    cfg = ctx.config["kshape"]
    inputs = inputs or {}
    valuation_panel = inputs.get("valuation")
    valuation = {r["ticker"]: r for r in (valuation_panel or {}).get("rows", []) if r.get("ticker")}
    pairs = cfg["pairs"]
    top_all = sorted({t for p in pairs for t in p["top"]})
    bottom_all = sorted({t for p in pairs for t in p["bottom"]} | set(cfg.get("bottom_only") or []))
    wanted = sorted(set(top_all) | set(bottom_all))
    closes = ctx.closes.reindex(columns=[t for t in wanted if t in ctx.closes.columns])
    missing = [t for t in wanted if t not in closes.columns]
    fetched_note = None
    if missing:
        try:
            extra = yahoo.fetch_closes(missing, period=f"{int(cfg['history_years']) + 1}y")
            closes = pd.concat([closes, extra.reindex(columns=[t for t in missing if t in extra.columns])], axis=1)
        except Exception as exc:  # noqa: BLE001 -- those names are then absent, the page says which
            fetched_note = describe_error(exc)
    still = [t for t in wanted if t not in closes.columns or closes[t].dropna().empty]
    ctx.log.add(SourceRecord("kshape_prices", "Closes for the K-shape legs (index members from the build; others fetched)", YAHOO_URL,
                             to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if not still else "partial",
                             error=(f"no prices: {', '.join(still)}" + (f"; {fetched_note}" if fetched_note else "")) if still else None))
    histories = {t: _read_history(t) for t in wanted} if valuation_panel else {t: None for t in wanted}
    periods = {label: PERIOD_TRADING_DAYS[label] for label in cfg["price_periods"]}
    uncovered = [t for t in wanted if t not in valuation and t in closes.columns]
    try:
        trends, _ = estimates.fetch_trends(uncovered) if uncovered else ({}, {})
    except Exception:  # noqa: BLE001 -- those names then show no forward multiple
        trends = {}
    kw = dict(closes=closes, valuation=valuation, trends=trends, today=pd.Timestamp(ctx.as_of), histories=histories, cfg=cfg, periods=periods,
              valuation_built=bool(valuation_panel))
    views = [_view("overall", cfg["overall_label"], "Every pair's top leg against every pair's bottom leg, and the low-end names with no top-leg counterpart "
                   "(fast food, dollar stores). Equal weight.", top_all, bottom_all, **kw)]
    views += [_view(p["key"], p["label"], p.get("note"), list(p["top"]), list(p["bottom"]), **kw) for p in pairs]
    return {
        "as_of": ctx.as_of,
        "settings": {k: cfg[k] for k in ("history_years", "price_periods", "pe_cap", "pe_min_share")},
        "inputs": {"prices_through": to_iso_date(closes.index[-1]) if not closes.empty else None,
                   "valuation_built": bool(valuation_panel), "valuation_as_of": (valuation_panel or {}).get("as_of"),
                   "no_prices": still},
        "views": views,
        "notes": [
            "The legs are a judgment, set by hand in the config: top = customers mostly wealthy, bottom = mostly low-income households. "
            "The squeezed middle (LULU, RL, TPR, WSM) is left out. A name can sit between the two; the spreads are only as good as the split.",
            "P/E ratios use the trailing P/E from each company's filings (the VALUATION tab's operating basis) and only the dates where at least "
            f"half the names had a meaningful one (positive and at most {cfg['pe_cap']}x): cruise lines, airlines and casinos had no earnings in 2020-21.",
            "Forward P/E is today's snapshot only; its history has not been kept long enough to chart. A ratio's percentile is where today's value "
            "sits among its own past weeks, not a verdict on which leg is right.",
        ],
    }
