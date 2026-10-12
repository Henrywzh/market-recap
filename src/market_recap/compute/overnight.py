"""OVERNIGHT VS INTRADAY: where a fund's return was made.

Each session's total return splits exactly into two legs: overnight, from the
previous close to the open (news, earnings and foreign markets while New York
is shut), and intraday, from the open to the close. The open and the close are
split-adjusted prices; the dividend goes to the overnight leg, because the
price falls by it at the open of the ex-date. So (1 + overnight) x
(1 + intraday) is the session's total return on adjusted closes.

A description of where the gains came from, not a strategy: holding only
overnight means trading twice a day, and the costs are not counted here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def legs(adjusted: pd.Series, price: pd.Series, open_: pd.Series) -> pd.DataFrame:
    """Daily ``overnight`` and ``intraday`` simple returns, and their ``total``.

    ``adjusted`` is the close adjusted for splits and dividends, ``price`` and
    ``open_`` are adjusted for splits only. A session without a positive open,
    or after one without a close, is left out rather than guessed.
    """
    frame = pd.concat([adjusted.rename("adj"), price.rename("close"), open_.rename("open")], axis=1).sort_index()
    frame = frame[(frame["adj"] > 0) & (frame["close"] > 0)]
    factor = frame["adj"] / frame["close"]            # dividends since, as a price multiple
    previous = frame["adj"].shift(1)
    out = pd.DataFrame(index=frame.index)
    out["overnight"] = frame["open"] * factor / previous - 1
    out["intraday"] = frame["close"] / frame["open"] - 1
    out = out[(frame["open"] > 0) & previous.notna()].dropna()
    out["total"] = (1 + out["overnight"]) * (1 + out["intraday"]) - 1
    return out


def growth(daily: pd.DataFrame) -> pd.DataFrame:
    """Growth of 1 held in each leg alone, and in both (the fund itself)."""
    return (1 + daily[["overnight", "intraday", "total"]]).cumprod()


def window(daily: pd.DataFrame, sessions: int | None) -> dict | None:
    """Each leg's compound return over the last ``sessions`` (all when None),
    annualised from a year up, with the share of sessions it was positive."""
    part = daily if sessions is None else daily.tail(sessions)
    if part.empty or (sessions is not None and len(part) < sessions):
        return None
    n = len(part)
    out: dict = {"sessions": n, "from": part.index[0]}
    for leg in ("overnight", "intraday", "total"):
        compound = float(np.prod(1 + part[leg].to_numpy()) - 1)
        out[leg] = compound * 100
        out[f"{leg}_ann"] = ((1 + compound) ** (TRADING_DAYS / n) - 1) * 100 if n >= TRADING_DAYS else None
        out[f"{leg}_up"] = float((part[leg] > 0).mean() * 100)
    return out


def calendar_years(daily: pd.DataFrame) -> list[dict]:
    """Each calendar year's overnight, intraday and total return, in percent;
    the first and the current year flagged as part years."""
    rows = []
    for year, part in daily.groupby(daily.index.year):
        rows.append({"year": int(year), **{leg: float(np.prod(1 + part[leg].to_numpy()) - 1) * 100
                                           for leg in ("overnight", "intraday", "total")},
                     "sessions": int(len(part))})
    if rows:
        rows[0]["partial"] = daily.index[0].month > 1 or daily.index[0].day > 7
        rows[-1]["to_date"] = True
    return rows


def stale_opens(open_: pd.Series, price: pd.Series) -> pd.Series:
    """Share of each year's sessions whose open equals the previous close:
    in an old feed, an open that was never recorded, not a trade."""
    frame = pd.concat([open_.rename("open"), price.rename("close")], axis=1).dropna()
    same = (frame["open"] == frame["close"].shift(1)).iloc[1:]
    return same.groupby(same.index.year).mean() * 100
