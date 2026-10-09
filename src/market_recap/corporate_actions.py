"""Corporate actions a price feed does not adjust for.

Yahoo adjusts closes for splits and dividends. It does not adjust for a
spin-off: when Corteva distributed Vylor on 2026-10-01 (one Vylor share for each
Corteva share), CTVA fell from 77.65 to 12.57 in one session and every return
window that spans the date reported a loss of 84% -- on a holder who had lost
nothing. That put Materials 4 points under water on the rotation tab.

Which actions to adjust is a choice, so they live in ``[[corporate_actions]]``
in config/dashboard.toml. The factor is not typed in: it is read from the
prices on the ex-date, so it cannot disagree with the feed it corrects.

    factor = P(ticker, ex) / (P(ticker, ex) + ratio * P(distributed, ex))

Every price before the ex-date is multiplied by it. The ex-date's own return is
then what a holder of the stub and of the distributed shares together earned
that day. If the distributed line has no price on the ex-date the factor is
unknown, and history before the date is dropped rather than left wrong: a
panel must not invent a value, and a false -84% is one.

Both lines are downloaded with the members whether or not the index still
holds them (``priced_lines``), then dropped again (``drop_extra``). Index
membership moves around a spin-off: by 2026-10-06 SPY held Vylor and no longer
Corteva, the build stopped pricing CTVA, the factor went with it, and the
strict build refused to publish.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED = ("ticker", "kind", "ex_date", "distributed", "ratio", "source")


@dataclass(frozen=True)
class Adjustment:
    ticker: str
    kind: str
    ex_date: pd.Timestamp
    distributed: str
    ratio: float
    source: str
    factor: float | None  # None: not computable, so history before ex_date is dropped
    unpriced: tuple[str, ...] = ()  # the lines with no price on ex_date

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker, "kind": self.kind, "ex_date": self.ex_date.strftime("%Y-%m-%d"),
            "distributed": self.distributed, "ratio": self.ratio, "source": self.source,
            "factor": None if self.factor is None else round(self.factor, 6),
            "unpriced": list(self.unpriced),
        }


def priced_lines(config: dict) -> set[str]:
    """Both lines of every configured action: its factor needs their prices."""
    return {str(e[key]).upper() for e in config.get("corporate_actions") or []
            for key in ("ticker", "distributed") if e.get(key)}


def drop_extra(frame: pd.DataFrame, extra: set[str]) -> pd.DataFrame:
    """``frame`` without the columns fetched only to compute a factor."""
    return frame.drop(columns=[c for c in extra if c in frame.columns]) if extra and not frame.empty else frame


def _price(prices: pd.DataFrame, symbol: str, day: pd.Timestamp) -> float | None:
    if symbol not in prices.columns or day not in prices.index:
        return None
    value = prices.at[day, symbol]
    return float(value) if pd.notna(value) and value > 0 else None


def resolve(config: dict, prices: pd.DataFrame) -> list[Adjustment]:
    """The configured actions that have taken effect, with their factors.

    An action dated after the last session is not in effect yet and is left
    out. A malformed entry is a configuration error, not something to skip.
    """
    out = []
    last = prices.index[-1] if len(prices.index) else None
    for entry in config.get("corporate_actions") or []:
        missing = [key for key in REQUIRED if entry.get(key) in (None, "")]
        if missing:
            raise ValueError(f"corporate_actions entry {entry.get('ticker')!r} lacks {', '.join(missing)}")
        ratio = float(entry["ratio"])
        if ratio <= 0:
            raise ValueError(f"corporate_actions entry {entry['ticker']!r}: ratio must be positive")
        ex_date = pd.Timestamp(entry["ex_date"])
        if last is None or ex_date > last:
            continue
        ticker, distributed = str(entry["ticker"]).upper(), str(entry["distributed"]).upper()
        held, spun = _price(prices, ticker, ex_date), _price(prices, distributed, ex_date)
        factor = held / (held + ratio * spun) if held is not None and spun is not None else None
        unpriced = tuple(s for s, p in ((ticker, held), (distributed, spun)) if p is None)
        out.append(Adjustment(ticker, str(entry["kind"]), ex_date, distributed, ratio, str(entry["source"]), factor, unpriced))
    return out


def adjust(frame: pd.DataFrame, adjustments: list[Adjustment]) -> pd.DataFrame:
    """``frame`` with each adjusted ticker's pre-ex-date prices rescaled, or
    blanked when the factor is unknown. Pass price columns only: volume is a
    count of shares that really traded and is not rescaled."""
    if frame.empty or not adjustments:
        return frame
    out = frame.copy()
    for item in adjustments:
        if item.ticker not in out.columns:
            continue
        before = out.index < item.ex_date
        if item.factor is None:
            out.loc[before, item.ticker] = float("nan")
        else:
            out.loc[before, item.ticker] = out.loc[before, item.ticker] * item.factor
    return out


def unexplained_moves(prices: pd.DataFrame, splits: pd.DataFrame | None, *, drop_pct: float,
                      rise_pct: float, sessions: int) -> list[dict]:
    """Recent one-session moves too large to take on trust.

    ``prices`` are split-adjusted closes, so a split never shows here; a move
    that does is either news (a takeover, an earnings gap) or a distribution the feed did not
    adjust for (Corteva's -84%). Telling them apart takes a reader, so this
    only lists them, for the build's notice. Run it on prices already adjusted
    for the configured actions, so those are not listed again.
    """
    if prices.shape[0] < 2:
        return []
    moves = prices.pct_change(fill_method=None).tail(sessions) * 100
    out = []
    for day, row in moves.iterrows():
        for ticker, value in row.dropna().items():
            if value <= -drop_pct or value >= rise_pct:
                split = False
                if splits is not None and ticker in splits.columns and day in splits.index:
                    split = bool(pd.notna(splits.at[day, ticker]))
                if not split:
                    out.append({"ticker": str(ticker), "date": day.strftime("%Y-%m-%d"), "move_pct": round(float(value), 1)})
    return sorted(out, key=lambda m: (m["date"], m["ticker"]))
