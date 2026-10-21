"""SCENARIOS: what each data release did to rates and to stocks.

For each configured release (CPI, PPI, payrolls, claims, ISM ...): how many
past releases came in above, in line with and below TradingView's forecast, how
far the 2-year and 10-year yields, SPY and each sector moved on those days
(with standard errors and counts), whether the sector ordering held out of
sample, and the next release with its forecast. Beside them: the rolling
stock-versus-yield correlation (is the market driven by rates or by growth),
the FOMC days against other days, and how the stock reaction to a surprise depends on what was driving the market.

The measurements are the point, not a forecast: most effects on stocks are not
detectable at these sample sizes and the panel says so (see compute.scenarios).
A figure that cannot be measured is None.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..compute import scenarios as S
from ..context import YAHOO_URL
from ..sources import expectations as X
from ..sources import fred, yahoo
from ..util import SourceRecord, clean_float, describe_error, to_iso_date

NOTES = (
    "Surprise = actual less TradingView's forecast; classes use the robust spread of each series' own surprises.",
    "A class with too few releases shows its count and no figure; an effect under about 0.3 percentage points on "
    "a day cannot be told from noise at 20-60 releases a class.",
    "Rates respond to surprises reliably; stocks and sectors mostly do not detectably. Sector 'persistence' is a "
    "permutation test of whether the ordering found before the split held after it.",
    "Not shown: a nowcast of each sector from the day's rates, credit, oil and dollar moves. Tested out of sample "
    "(loadings fitted on a year, scored on the next month, 2012-2026, 40 sector and industry funds) the median fund "
    "scored 0.03; only energy, metals, staples, utilities and REITs reached 0.1 or more.",
)


def _num(value, digits: int = 3):
    return clean_float(value, digits)


def _clean(value, digits: int = 3):
    """A nested result with every float rounded and every NaN or infinity an absence."""
    if isinstance(value, dict):
        return {k: _clean(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v, digits) for v in value]
    if isinstance(value, (float, np.floating)):
        return _num(float(value), digits)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _slope(entry: dict, digits: int = 3) -> dict:
    return {"slope": _num(entry["slope"], digits), "t": _num(entry["t"], 2), "n": entry["n"]}


def _next_release(rows: list[dict], driver: dict, as_of: date) -> dict | None:
    """The soonest upcoming release of a driver's line from a calendar window."""
    found = []
    for r in rows:
        if (r.get("title") or "").strip() != driver["title"] or not r.get("date"):
            continue
        day = pd.Timestamp(r["date"]).tz_convert("America/New_York")
        if day.date() <= as_of:
            continue
        found.append((day, r))
    if not found:
        return None
    day, r = min(found, key=lambda item: item[0])
    return {"date": day.date().isoformat(), "time": day.strftime("%H:%M"), "forecast": _num(r.get("forecast"), 3),
            "previous": _num(r.get("previous"), 3), "unit": driver["unit"]}


def _fomc(rows: list[dict], cfg: dict, days: pd.DatetimeIndex, frame: pd.DataFrame) -> dict:
    """FOMC decision days against other days: how big the moves are, which way
    stocks go when the 2-year yield moves, and what hawkish and dovish days did."""
    decisions = []
    for r in rows:
        if (r.get("title") or "").strip() != cfg["fomc_title"] or r.get("actual") is None or not r.get("date"):
            continue
        day = pd.Timestamp(r["date"]).tz_convert("America/New_York").normalize().tz_localize(None)
        if day >= pd.Timestamp(cfg["history_start"]) and day in days:
            decisions.append({"day": day, "actual": r["actual"], "forecast": r.get("forecast"), "previous": r.get("previous")})
    if not decisions:
        return {"decisions": 0}
    meeting = pd.DataFrame(decisions).drop_duplicates("day").set_index("day")
    is_f = frame.index.isin(meeting.index)
    fo, other = frame[is_f], frame[~is_f]
    bucket = float(cfg["fomc_bucket_bp"])
    hawk, dove = fo[fo["dY2"] >= bucket], fo[fo["dY2"] <= -bucket]
    out = {
        "decisions": int(len(meeting)),
        "decisions_with_surprise": int(((meeting["actual"] - meeting["forecast"]).abs() > 1e-9).sum()),
        "abs_move": {"spy_fomc": _num(fo["SPY"].abs().mean(), 2), "spy_other": _num(other["SPY"].abs().mean(), 2),
                     "dY2_fomc": _num(fo["dY2"].abs().mean(), 2), "dY2_other": _num(other["dY2"].abs().mean(), 2)},
        "spy_per_bp_of_2y": {"fomc_days": _slope(S.slope_t(fo["dY2"], fo["SPY"], min_n=cfg["min_era_releases"]), 4),
                             "other_days": _slope(S.slope_t(other["dY2"], other["SPY"], min_n=cfg["min_era_releases"]), 4)},
        "buckets": {"bp": bucket, "hawkish": {"n": int(len(hawk)), "spy": _num(hawk["SPY"].mean(), 2)},
                    "dovish": {"n": int(len(dove)), "spy": _num(dove["SPY"].mean(), 2)}},
        "recent": [{"date": d.date().isoformat(), "rate": _num(meeting.loc[d, "actual"], 3), "previous": _num(meeting.loc[d, "previous"], 3),
                    "spy": _num(frame.loc[d, "SPY"], 2), "dY2": _num(frame.loc[d, "dY2"], 1)}
                   for d in fo.index[-5:]],
    }
    return out


def assemble(*, as_of: date, closes: pd.DataFrame, y10: pd.Series, y2: pd.Series, rows: list[dict],
             upcoming: list[dict], sectors: dict[str, str], market: str, cfg: dict) -> dict:
    """The panel from plain data: daily closes (one column per symbol), the two
    yield series in percent, TradingView calendar rows (history, then the
    coming window) and the sector -> ETF map. Pure: no fetching."""
    closes = closes[closes.index <= pd.Timestamp(as_of)].sort_index()
    ret = closes.pct_change() * 100
    # Bond holidays carry the last yield; sessions after FRED's last reading have
    # none (it lags the close by a day), so their yield moves are absent, not zero.
    last_yield = min(y10.dropna().index.max(), y2.dropna().index.max())
    yields = pd.DataFrame({"y10": y10, "y2": y2}).reindex(closes.index).ffill()
    yields[yields.index > last_yield] = np.nan
    dy10, dy2 = yields["y10"].diff() * 100, yields["y2"].diff() * 100
    spy = ret[market]
    excess = pd.DataFrame({etf: ret[etf] - spy for etf in sectors.values() if etf in ret.columns})
    relative = pd.DataFrame({sym: ret[sym] - spy for sym in cfg["relative"] if sym in ret.columns})
    frame = pd.DataFrame({"SPY": spy, "dY2": dy2, "dY10": dy10})
    days = closes.index
    exclude = [(w["start"], w["end"]) for w in cfg["exclude"]]
    corr_now = S.regime(spy, dy10, sessions=cfg["regime_sessions"])
    rolling_corr = spy.rolling(cfg["regime_sessions"]).corr(dy10).shift(1)
    min_class, min_era = cfg["min_class_releases"], cfg["min_era_releases"]
    outcomes = pd.concat([frame[["dY2", "dY10", "SPY"]], relative.add_suffix("-SPY"), excess], axis=1)

    # Windows left out of the release tables are left out of the comparison days too.
    keep = pd.Series(True, index=days)
    for lo, hi in exclude:
        keep[(days >= pd.Timestamp(lo)) & (days <= pd.Timestamp(hi))] = False
    spy_kept, dy2_kept = spy.where(keep), dy2.where(keep)
    tables: dict[str, pd.DataFrame] = {}
    drivers = []
    for d in cfg["drivers"]:
        table, scale = S.release_table(rows, d["title"], start=cfg["history_start"], exclude=exclude, days=days,
                                       threshold_sd=cfg["class_threshold_sd"], clip_sd=cfg["surprise_clip_sd"],
                                       miss_threshold=d.get("miss_threshold"))
        entry: dict = {"key": d["key"], "label": d["label"], "unit": d["unit"], "n": int(len(table)),
                       "first": table.index.min().date().isoformat() if len(table) else None,
                       "last": table.index.max().date().isoformat() if len(table) else None,
                       "scale": _num(scale, 3), "next": _next_release(upcoming, d, as_of),
                       "miss_threshold": d.get("miss_threshold")}
        if scale is None or len(table) < min_era:
            entry["status"] = "insufficient"
            drivers.append(entry)
            continue
        entry["status"] = "ok"
        tables[d["key"]] = table
        size = S.event_size(table.index, spy_kept, dy2_kept, start=cfg["history_start"])
        entry["event_size"] = {k: (_num(v, 2) if isinstance(v, float) else v) for k, v in size.items()}
        z = table["z"]
        j = outcomes.reindex(table.index)
        row, move = table.iloc[-1], j.iloc[-1]
        entry["latest"] = {"date": table.index[-1].date().isoformat(), "actual": _num(row["actual"]),
                           "forecast": _num(row["forecast"]), "surprise": _num(row["surprise"]), "cls": row["cls"],
                           "dY2": _num(move["dY2"]), "SPY": _num(move["SPY"])}
        entry["rates_per_sd"] = {"dY2": _slope(S.slope_t(z, j["dY2"], min_n=min_era), 2),
                                 "dY10": _slope(S.slope_t(z, j["dY10"], min_n=min_era), 2)}
        entry["spy_per_sd"] = _slope(S.slope_t(z, j["SPY"], min_n=min_era), 3)
        entry["spy_by_era"] = [{"era": e["era"], **_slope(e, 3)} for e in S.era_slopes(z, j["SPY"], cfg["era_breaks"], min_n=min_era)]
        in_rates = rolling_corr.reindex(table.index) < 0
        entry["spy_when_rates_drive"] = _slope(S.slope_t(z[in_rates], j["SPY"][in_rates], min_n=min_era), 3)
        classes = S.class_means(table, outcomes, min_n=min_class)
        entry["classes"] = {
            cls: {"n": c["n"], **{k: ({"mean": _num(v["mean"], 3), "se": _num(v["se"], 3)} if v else None)
                                  for k, v in c.items() if k != "n"}}
            for cls, c in classes.items()
        }
        entry["persistence"] = S.persistence(table, excess, split=cfg["persistence_split"], min_n=min_class,
                                             permutations=cfg["permutations"], seed=cfg["permutation_seed"])
        entry["persistence"] = {k: (_num(v, 3) if isinstance(v, float) else v) for k, v in entry["persistence"].items()}
        drivers.append(entry)

    sector_list = [{"sector": sector, "etf": etf} for sector, etf in sectors.items() if etf in excess.columns]

    hawkish = {d["key"]: int(d.get("hawkish", 1)) for d in cfg["drivers"]}
    release = S.release_days(tables, hawkish, spy_kept, dy2_kept, rolling_corr)
    comparison = pd.DataFrame({"spy": spy_kept, "dy2": dy2_kept, "corr": rolling_corr}).loc[pd.Timestamp(cfg["history_start"]):]
    comparison = comparison[~comparison.index.isin(release.index)].dropna()
    comparison["rates"] = comparison["corr"] < 0
    regime_response = S.regime_response(release, comparison, split=cfg["persistence_split"], min_n=min_era,
                                        permutations=cfg["permutations"], seed=cfg["permutation_seed"])

    return {
        "as_of": as_of.isoformat(),
        "settings": {k: cfg[k] for k in ("history_start", "class_threshold_sd", "surprise_clip_sd", "min_class_releases",
                                         "min_era_releases", "era_breaks", "regime_sessions",
                                         "persistence_split", "permutations")} | {"exclude": cfg["exclude"]},
        "inputs": {"prices_through": to_iso_date(closes.index[-1]), "yields_through": to_iso_date(last_yield)},
        "regime": {k: (_num(v, 3) if isinstance(v, float) else v) for k, v in corr_now.items()},
        "drivers": drivers,
        "regime_response": _clean(regime_response),
        "fomc": _fomc(rows, cfg, days, frame),
        "sectors": sector_list,
        "notes": list(NOTES),
    }


def build(ctx) -> dict:
    cfg = ctx.config["scenarios"]
    as_of = date.fromisoformat(ctx.as_of)
    market = ctx.config["universe"]["market_proxy"]
    sectors = ctx.sector_etfs
    symbols = sorted({market, *sectors.values(), *cfg["relative"]})
    years = int(ctx.config["universe"]["history_years"])
    closes = yahoo.fetch_closes(symbols, period=f"{years}y")
    ctx.log.add(SourceRecord("scenarios_prices", "Daily closes for the market proxy, the sector ETFs and the relative-strength funds", YAHOO_URL,
                             to_iso_date(closes.index[-1]) if not closes.empty else None, rows=int(closes.shape[1]),
                             status="ok" if set(symbols) <= set(closes.columns) else "partial",
                             error=None if set(symbols) <= set(closes.columns) else f"no data: {', '.join(sorted(set(symbols) - set(closes.columns)))}"))
    y10, url10 = fred.fetch_series(cfg["fred_10y"])
    y2, _ = fred.fetch_series(cfg["fred_2y"])
    ctx.log.add(SourceRecord("scenarios_yields", "Treasury constant-maturity 10-year and 2-year yields (FRED)", url10,
                             to_iso_date(y10["date"].max()), rows=int(len(y10) + len(y2))))
    rows, failed = X.tradingview_history(date.fromisoformat(cfg["history_start"]), as_of)
    try:
        upcoming = X.fetch_tradingview(as_of + timedelta(days=1), as_of + timedelta(days=int(cfg["upcoming_days"])))
        upcoming_error = None
    except Exception as exc:  # noqa: BLE001 -- the history still stands without the coming window
        upcoming, upcoming_error = [], describe_error(exc)
    errors = [f"months not answered: {', '.join(failed[:6])}"] if failed else []
    if upcoming_error:
        errors.append(f"coming window: {upcoming_error}")
    ctx.log.add(SourceRecord("scenarios_calendar", "TradingView economic calendar: releases, forecasts and actuals", X.TV_URL,
                             ctx.as_of, rows=len(rows), policy="daily_close", status="ok" if not errors else "partial",
                             error="; ".join(errors) or None))
    payload = assemble(as_of=as_of, closes=closes, y10=y10.set_index("date")["value"], y2=y2.set_index("date")["value"],
                       rows=rows, upcoming=upcoming, sectors=sectors, market=market, cfg=cfg)
    payload["inputs"]["calendar_months_missing"] = failed
    return payload
