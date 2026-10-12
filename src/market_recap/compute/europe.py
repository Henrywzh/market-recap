"""European coverage: pure helpers for the EUROPE panel.

Everything here is arithmetic on prices already fetched. A return in dollars
is the local return compounded with the currency's move against the dollar; a
price quoted in pence (London) is converted to pounds before it is, and the
returns of the local series are untouched by that.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

# Yahoo's suffix -> currency of the quote. London quotes in pence (GBp).
SUFFIX_CURRENCY = {
    "L": "GBp", "PA": "EUR", "DE": "EUR", "AS": "EUR", "MI": "EUR", "MC": "EUR", "BR": "EUR", "HE": "EUR",
    "IR": "EUR", "LS": "EUR", "VI": "EUR", "SW": "CHF", "ST": "SEK", "CO": "DKK", "OL": "NOK",
}


def currency_of(symbol: str, override: Mapping[str, str] | None = None) -> str | None:
    """The currency a symbol quotes in: a configured override, else its
    exchange suffix; None for an index or a symbol with neither."""
    if override and symbol in override:
        return override[symbol]
    if "." not in symbol or symbol.startswith("^"):
        return None
    return SUFFIX_CURRENCY.get(symbol.rsplit(".", 1)[1].upper())


def broad_sector(label: str | None, mapping: Mapping[str, str], *, default: str = "Other") -> str:
    """A source's industry label (any case) mapped to one of the broad sectors."""
    return mapping.get((label or "").strip().lower(), default)


def in_dollars(local: pd.Series, fx_per_unit: pd.Series, *, pence: bool = False) -> pd.Series:
    """A local-currency series in dollars: the series times the dollar value of
    one unit of its currency (one pound for pence, divided by a hundred), on the
    days both exist, the currency carried over holidays."""
    rate = fx_per_unit.reindex(local.index.union(fx_per_unit.index)).sort_index().ffill().reindex(local.index)
    return local * rate / (100.0 if pence else 1.0)


def relative_to(series: pd.Series, benchmark: pd.Series) -> pd.Series:
    """The series over the benchmark on their common days, rebased to 100 at the first."""
    both = pd.concat([series.rename("s"), benchmark.rename("b")], axis=1).dropna()
    if both.empty:
        return pd.Series(dtype=float)
    ratio = both["s"] / both["b"]
    return 100 * ratio / ratio.iloc[0]
