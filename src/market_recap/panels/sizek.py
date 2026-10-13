"""RELATIVE VALUE -> SIZE K: one arm of a pair against the other.

For each configured pair (the S&P 500 and Nasdaq-100 cap-weighted against
equal-weight, large against small and mid caps, the FTSE 100 against the
FTSE 250, and style pairs such as value against growth, staples against the
market, low volatility against the market): the two arms' price series and
their ratio with where today's ratio sits among its own weeks, returns by
window, the rolling one-year return gap and how often and how long the first
arm led, and each calendar year's gap. Each pair names its arms (``big_arm`` /
``small_arm``, default LARGE / SMALL).
Where a pair names a basket for each arm (``big_basket`` / ``small_basket``),
each arm is also rebuilt as a basket of its names' trailing P/E and earnings,
the way the VALUATION tab builds an index, so the gap splits into a re-rating
and an earnings difference (``fundamentals``; each arm also carries its
``history`` by fiscal year, see panels.kshape.arm). Specs:
``index:SPX`` / ``index:SPX:equal`` / ``index:NDX`` / ``index:NDX:equal`` (index
members, cap-weighted or equal), ``sector:<GICS sector>`` (S&P 500 members,
cap-weighted or equal), and ``holdings:<iShares fund>`` (the fund's own holding weights,
looked through to the names). A pair without baskets is prices only, and says
why in ``fundamentals_note``. See compute.sizek.
A pair with ``source = "french"`` takes its arms from Kenneth French's daily
portfolio returns instead of Yahoo: factor series (the Fama-French value and
size sorts), not funds, and published monthly with a lag. See sources.french.
"""

from __future__ import annotations

import pandas as pd

from ..compute import kshape as K
from ..compute import sizek as S
from ..compute import xray as X
from ..config import FINANCIALS_ARTIFACT_DIR, PERIOD_TRADING_DAYS
from ..context import YAHOO_URL
from ..sources import french, ishares, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date
from .kshape import FUNDAMENTAL_YEARS, NO_VALUATION, Histories, Revenues, Statements, _series_payload
from .kshape import arm as basket_arm
from .kshape import fundamentals as basket_fundamentals
from .xray import _equity_lines

INPUTS = ("valuation",)
# The index the sector groups are drawn from (config universe.indices, primary = true).
PRIMARY_INDEX = "SPX"
INDEX_NAMES = {"SPX": "S&P 500", "NDX": "Nasdaq-100"}
BASKET_KINDS = ("index", "sector", "holdings")

NOTES = (
    "Prices are the ratio of the two arms. Where a pair has a basket for each arm, the page also splits the gap into the arms' P/E "
    "and earnings: each arm is rebuilt from its names' SEC filings and closes, as the VALUATION tab builds an index, at today's "
    "weights and members. A pair without baskets is prices only: its arms are outside the filings universe (S&P 500 and Nasdaq-100 "
    "members), and the pair says so.",
    "A ratio's percentile is where today's value sits among its own past weeks. A ratio that has risen for years says only that "
    "the first arm has led, not that it must turn.",
    "Some pairs differ in how they are built: the equal-weight funds rebalance on a schedule and hold more small and mid-sized names than "
    "the cap-weighted ones, so part of such a gap is construction, not only the names.",
)


FRENCH_LABEL = "Kenneth French's daily size and book-to-market portfolios (value-weighted)"
# A French arm is an equal mix of the daily returns of the portfolios it names,
# compounded from 100: VALUE and GROWTH are HML's own two halves, so their
# ratio follows HML's compounded return.
FRENCH_ARMS = {
    "FF_VALUE": ("SMALL HiBM", "BIG HiBM"),
    "FF_GROWTH": ("SMALL LoBM", "BIG LoBM"),
    "FF_BIG_VALUE": ("BIG HiBM",),
    "FF_BIG_GROWTH": ("BIG LoBM",),
}


def _french_arms(returns: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Each French arm as a price index over the window from ``start`` to ``end``.
    A missing return in a portfolio that an arm uses raises rather than being
    averaged away: the arm's history would then describe fewer names on that day."""
    used = sorted({leg for legs in FRENCH_ARMS.values() for leg in legs})
    if returns[used].isna().any().any():
        raise ValueError("missing daily returns in the French portfolios")
    index = {symbol: 100 * (1 + returns[list(legs)].mean(axis=1)).cumprod() for symbol, legs in FRENCH_ARMS.items()}
    frame = pd.DataFrame(index)
    return frame[(frame.index >= start) & (frame.index <= end)]


def _french_series(ctx, years: int) -> tuple[pd.DataFrame, SourceRecord]:
    """The French arms for the SIZE K window, and the record of the fetch. A
    failed fetch returns no columns, so its pairs read as having no prices."""
    end = pd.Timestamp(ctx.as_of)
    try:
        returns = french.fetch_value_weighted_daily()
    except Exception as exc:  # noqa: BLE001 - a missing factor file must not take the Yahoo pairs down with it
        return pd.DataFrame(), SourceRecord("french_portfolios", FRENCH_LABEL, french.URL, status="error",
                                            error=describe_error(exc), policy="monthly_release")
    try:
        arms = _french_arms(returns, end - pd.DateOffset(years=years), end)
    except Exception as exc:  # noqa: BLE001 - the same: the record says why, the rest of the page still builds
        return pd.DataFrame(), SourceRecord("french_portfolios", FRENCH_LABEL, french.URL, to_iso_date(returns.index[-1]),
                                            rows=int(len(returns)), status="error", error=describe_error(exc),
                                            policy="monthly_release")
    return arms, SourceRecord("french_portfolios", FRENCH_LABEL, french.URL, to_iso_date(returns.index[-1]),
                              rows=int(len(returns)), policy="monthly_release")


def _view(pair: dict, closes: pd.DataFrame, cfg: dict, periods: dict[str, int], gap_sessions: int) -> dict:
    big, small = pair["big"], pair["small"]
    out: dict = {"key": pair["key"], "label": pair["label"], "note": pair.get("note"), "big": big, "small": small,
                 "big_name": pair.get("big_name", big), "small_name": pair.get("small_name", small),
                 "big_arm": pair.get("big_arm", "LARGE"), "small_arm": pair.get("small_arm", "SMALL"),
                 "price_index": bool(pair.get("price_index")), "price": None}
    missing = [s for s in (big, small) if s not in closes.columns or closes[s].dropna().empty]
    out["no_prices"] = missing
    if missing:
        return out
    both = closes[[big, small]].dropna().sort_index()
    if len(both) < 2:
        return out
    # Both rebased to 100 on the first day both are priced, so the ratio starts at 1.
    rebased = 100 * both / both.iloc[0]
    ratio = K.ratio(rebased[big], rebased[small])
    weekly = ratio.groupby(ratio.index.to_period("W-FRI")).tail(1)
    gap = S.rolling_gap(both[big], both[small], gap_sessions)
    extremes = S.ratio_extremes(ratio)
    years = int(cfg["history_years"])
    frame = pd.DataFrame({"big": rebased[big], "small": rebased[small], "ratio": ratio})
    out["price"] = {
        **_series_payload(frame, years),
        "since": to_iso_date(both.index[0]), "through": to_iso_date(both.index[-1]), "sessions": int(len(both)),
        "ratio_now": clean_float(ratio.iloc[-1], 3),
        "ratio_percentile": clean_float(K.percentile(weekly, float(ratio.iloc[-1])), 0),
        "extremes": None if extremes is None else {
            "high": clean_float(extremes["high"], 3), "high_date": to_iso_date(extremes["high_date"]),
            "low": clean_float(extremes["low"], 3), "low_date": to_iso_date(extremes["low_date"]),
            "from_high_pct": clean_float(extremes["from_high_pct"], 1), "from_low_pct": clean_float(extremes["from_low_pct"], 1)},
        "spreads": [{k: (clean_float(v, 1) if k != "period" else v) for k, v in r.items()}
                    for r in K.spread_table(rebased[big], rebased[small], periods)],
    }
    out["gap"] = None
    if len(gap) >= 2:
        weekly_gap = gap.groupby(gap.index.to_period("W-FRI")).tail(1)
        out["gap"] = {
            **_series_payload(pd.DataFrame({"gap": gap}), years, 1),
            "window": cfg["gap_period"], "now": clean_float(gap.iloc[-1], 1),
            "percentile": clean_float(K.percentile(weekly_gap, float(gap.iloc[-1])), 0),
            "share_big_ahead": clean_float(S.share_of_windows(gap), 0),
            "longest_big": int(S.longest_run(gap) // 5), "longest_small": int(S.longest_run(gap, positive=False) // 5),
            "windows": int(len(gap)), "first": to_iso_date(gap.index[0]),
        }
    out["years"] = [{k: (clean_float(v, 1) if k in ("big", "small", "gap") else v) for k, v in r.items()}
                    for r in S.calendar_years(both[big], both[small])]
    return out


def _from_french(pair: dict) -> bool:
    return pair.get("source") == "french"


# --- Fundamentals: each arm as a basket of its names' P/E and earnings -------------

def parse_basket(text: str) -> tuple[str, str, bool]:
    """A basket spec as (kind, name, equal weight): 'index:SPX', 'index:SPX:equal',
    'sector:Consumer Staples', 'holdings:IWD'. Equal weight is for index and sector
    arms only; a fund's arm is weighted by the fund's own holdings."""
    kind, _, rest = str(text).partition(":")
    name, _, mode = rest.partition(":")
    if kind not in BASKET_KINDS or not name or mode not in ("", "equal") or (mode and kind == "holdings"):
        raise ValueError(f"unknown basket spec {text!r}")
    return kind, name, mode == "equal"


def basket_label(kind: str, name: str, equal: bool) -> str:
    """The arm's name on the page when the config gives none. A fund's arm is
    named by its ticker, so a fund's full name goes in the config instead."""
    if kind == "index":
        return f"{INDEX_NAMES.get(name, name)} {'equal-weight' if equal else 'cap-weighted'}"
    if kind == "sector":
        return f"{name} sector" + (", equal-weight" if equal else "")
    return name


def _members(kind: str, name: str, rows: dict[str, dict]) -> list[str]:
    """The names an index or sector arm holds today, from this session's VALUATION rows."""
    if kind == "index":
        return [t for t, r in rows.items() if name in (r.get("indices") or [])]
    return [t for t, r in rows.items() if r.get("sector") == name and PRIMARY_INDEX in (r.get("indices") or [])]


def _fund(ticker: str, memo: dict, ctx) -> dict:
    """A fund's equity lines from its iShares file, fetched once per build. A
    failed fetch is kept and logged, never raised: the other arms still build."""
    if ticker not in memo:
        label = f"{ticker} holdings (iShares), for the SIZE & STYLE fundamentals"
        try:
            frame, as_of, url = ishares.fetch_holdings(ticker)
            lines = _equity_lines(frame, "ishares", "")
            memo[ticker] = {"lines": lines, "as_of": as_of, "error": None}
            ctx.log.add(SourceRecord(f"sizek_{ticker.lower()}_holdings", label, url, observed_date=as_of, rows=int(len(lines)),
                                     policy="fund_holdings"))
        except Exception as exc:  # noqa: BLE001 -- the arm says why it has no basket; the page's other arms still build
            memo[ticker] = {"lines": None, "as_of": None, "error": describe_error(exc)}
            ctx.log.add(SourceRecord(f"sizek_{ticker.lower()}_holdings", label, ishares.HOME_URL, policy="fund_holdings",
                                     status="error", error=describe_error(exc)))
    return memo[ticker]


def _holdings_arm(which: str, label: str, ticker: str, rows: dict[str, dict], histories: Histories, memo: dict, ctx,
                  years: int, revenues: Revenues, statements: Statements | None = None) -> tuple[dict, str | None]:
    """A fund's arm: its holding weights on the names with a filings history.
    Fund coverage is the share of the fund's equity weight those names hold."""
    fund = _fund(ticker, memo, ctx)
    if fund["lines"] is None:
        return ({"key": which, "label": label, "basket": None, "fund_coverage": None, "note": None},
                f"{label}: the holdings of {ticker} could not be fetched ({fund['error']}).")
    lines = fund["lines"]
    total = float(lines["weight"].sum())
    us = lines[lines["us_listed"]]
    # The same mapping the X-RAY tab uses: an issuer's ticker onto this build's own symbol.
    symbols = X.resolve_symbols(us["ticker"], list(rows))
    by_symbol = us["weight"].groupby(symbols.to_numpy()).sum()
    names = [s for s in by_symbol.index if s in rows]
    closes, yields = histories.frames(names)
    weights = {s: float(by_symbol[s]) for s in names if s in closes.columns}
    coverage = sum(weights.values()) / total if total > 0 else None
    note = f"Weights are {ticker}'s own holding weights as of {fund['as_of']}, for the names with a filings history."
    return basket_arm(which, label, list(weights), closes, yields, weights, years=years, fund_coverage=coverage, note=note,
                      rows=rows, revenue=revenues.of(list(weights)), statements=statements)


def _arm(which: str, spec: str, label: str | None, rows: dict[str, dict], histories: Histories, memo: dict, ctx,
         years: int, revenues: Revenues, statements: Statements | None = None) -> tuple[dict, str | None]:
    kind, name, equal = parse_basket(spec)
    label = label or basket_label(kind, name, equal)
    if kind == "holdings":
        return _holdings_arm(which, label, name, rows, histories, memo, ctx, years, revenues, statements)
    names = _members(kind, name, rows)
    # Cap-weighted arms use this session's market caps; a name without one is left out and says so.
    weights = None if equal else {t: float(rows[t]["market_cap"]) for t in names if rows[t].get("market_cap")}
    closes, yields = histories.frames(names)
    return basket_arm(which, label, names, closes, yields, weights, years=years, rows=rows, revenue=revenues.of(names),
                      statements=statements)


def _valuation_rows(inputs: dict | None) -> dict[str, dict] | None:
    """VALUATION's rows by ticker, or None when VALUATION was not built this session."""
    panel = (inputs or {}).get("valuation")
    if panel is None:
        return None
    return {r["ticker"]: r for r in panel.get("rows", []) if r.get("ticker")}


def _pair_fundamentals(pair: dict, rows: dict[str, dict] | None, histories: Histories, memo: dict, ctx, years: int,
                       revenues: Revenues, statements: Statements | None = None) -> dict:
    """The pair's fundamentals block, or the reason it has none. A pair with no
    baskets carries its ``fundamentals_note``; a pair with baskets but no
    VALUATION this session says that instead of showing nothing."""
    specs = [(pair.get("big_basket"), pair.get("big_basket_label"), "big"),
             (pair.get("small_basket"), pair.get("small_basket_label"), "small")]
    if not all(spec for spec, _, _ in specs):
        return {"fundamentals_note": pair.get("fundamentals_note")}
    if rows is None:
        return {"fundamentals": {"missing": NO_VALUATION}, "fundamentals_note": None}
    built = [_arm(which, spec, label, rows, histories, memo, ctx, years, revenues, statements) for spec, label, which in specs]
    return {"fundamentals": basket_fundamentals(built), "fundamentals_note": None}


def build(ctx, *, inputs: dict | None = None) -> dict:
    cfg = ctx.config["sizek"]
    pairs = cfg["pairs"]
    wanted = sorted({s for p in pairs if not _from_french(p) for s in (p["big"], p["small"])})
    closes = yahoo.fetch_closes(wanted, period=f"{int(cfg['history_years'])}y")
    missing = sorted(set(wanted) - set(closes.columns))
    ctx.log.add(SourceRecord("sizek_prices", "Closes for the SIZE K pairs: cap-weighted and equal-weight funds, size, style and index pairs", YAHOO_URL,
                             to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if not missing else "partial", error=f"no data: {', '.join(missing)}" if missing else None))
    if closes.empty:
        raise RuntimeError("no prices for the size-K pairs")
    closes = closes[closes.index <= pd.Timestamp(ctx.as_of)]
    french_wanted = sorted({s for p in pairs if _from_french(p) for s in (p["big"], p["small"])})
    if french_wanted:
        arms, record = _french_series(ctx, int(cfg["history_years"]))
        ctx.log.add(record)
        closes = closes.join(arms, how="outer")
        missing = sorted(set(missing) | (set(french_wanted) - set(arms.columns)))
    periods = {label: PERIOD_TRADING_DAYS[label] for label in cfg["price_periods"]}
    gap_sessions = PERIOD_TRADING_DAYS[cfg["gap_period"]]
    views = [_view(p, closes, cfg, periods, gap_sessions) for p in pairs]
    # Baskets come from this session's VALUATION rows and per-name histories, read once for all the pairs.
    rows = _valuation_rows(inputs)
    statements = Statements(FINANCIALS_ARTIFACT_DIR)
    histories, memo, revenues = Histories(), {}, Revenues(FINANCIALS_ARTIFACT_DIR, statements)
    years = min(int(cfg["history_years"]), FUNDAMENTAL_YEARS)
    for pair, view in zip(pairs, views):
        view.update(_pair_fundamentals(pair, rows, histories, memo, ctx, years, revenues, statements))
    return {
        "as_of": ctx.as_of,
        "settings": {k: cfg[k] for k in ("history_years", "price_periods", "gap_period")},
        "inputs": {"prices_through": to_iso_date(closes.index[-1]), "no_prices": missing, "valuation_built": rows is not None},
        "views": views,
        "notes": list(NOTES),
    }
