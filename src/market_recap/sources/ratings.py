"""Analyst rating and price-target changes, from Yahoo's upgrade/downgrade history.

Read per name for the ticker page's evidence list: dates, firm, action and
grades as Yahoo records them. Listed, not scored; a maintained rating with a
new target is a target change, not a rating change.
"""

from __future__ import annotations

import contextlib
import io
import json

import pandas as pd

from .. import cache

NAMESPACE = "ratings"
HOME_URL = "https://finance.yahoo.com"


def _fetch(symbol: str) -> str:
    import yfinance as yf

    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer), contextlib.redirect_stdout(buffer):
        frame = yf.Ticker(symbol).upgrades_downgrades
    if frame is None or frame.empty:
        return "[]"
    frame = frame.reset_index()
    frame = frame.rename(columns={frame.columns[0]: "date"})
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame.to_json(orient="records")


def fetch_changes(symbol: str, *, use_cache: bool = True) -> list[dict]:
    text = cache.fetch_text(NAMESPACE, symbol, lambda: _fetch(symbol), kind="daily_file", suffix=".json",
                            use_cache=use_cache)
    return json.loads(text)
