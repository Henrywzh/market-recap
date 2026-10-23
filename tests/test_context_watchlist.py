"""The watchlist frame keeps its columns when the sector lookup returns nothing."""

from types import SimpleNamespace

import pandas as pd

from market_recap import context
from market_recap.sources import yahoo


class _Log:
    def add(self, record):
        pass


def test_an_empty_sector_lookup_still_gives_every_column(monkeypatch):
    monkeypatch.setattr(yahoo, "fetch_sectors", lambda symbols: pd.DataFrame())
    ctx = SimpleNamespace(closes=pd.DataFrame({"SKHY": [1.0]}), as_of="2026-10-22", log=_Log())
    frame = context._build_watchlist(ctx, [{"ticker": "skhy", "label": "SK hynix ADR"}], ["SKHY"])
    assert list(frame.columns) == context.WATCHLIST_COLUMNS
    row = next(frame.itertuples())
    # What CATALYSTS reads: present and empty, not an AttributeError.
    assert row.ticker == "SKHY" and row.label == "SK hynix ADR" and row.sector is None and row.name is None
