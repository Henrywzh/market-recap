"""INDICES breadth: the S&P 500's frozen own-member past, continued live."""

import json

import numpy as np
import pandas as pd

from market_recap.config import SPX_PIT_BREADTH_PATH
from market_recap.panels import overview as O


def _closes(n=320):
    idx = pd.bdate_range("2026-01-01", periods=n)
    rng = np.random.default_rng(0)
    return pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, 6)), axis=0)), index=idx, columns=list("ABCDEF"))


def test_frozen_sessions_come_first_and_live_continues_after_them():
    closes = _closes()
    through = closes.index[250].date().isoformat()
    frozen = {"dates": ["2021-01-04", through], "through": through,
              "above_50d": [10.0, 20.0], "above_200d": [30.0, 40.0], "coverage": [85.0, 99.0]}
    out = O.breadth_history(closes, frozen=frozen)
    assert out["dates"][:2] == ["2021-01-04", through]
    assert out["dates"][2] > through and out["dates"] == sorted(out["dates"])
    assert out["dates"][-1] == closes.index[-1].date().isoformat()
    assert out["coverage"][:2] == [85.0, 99.0] and out["coverage"][2] is None
    assert out["own_members_through"] == through
    assert len(out["above_50d"]) == len(out["dates"]) == len(out["above_200d"]) == len(out["coverage"])


def test_without_a_frozen_past_it_is_the_last_year_on_todays_members():
    out = O.breadth_history(_closes(600))
    assert len(out["dates"]) == O.HIGH_WINDOW and "coverage" not in out


def test_the_frozen_file_is_derived_values_only_and_covers_five_years():
    data = json.loads(SPX_PIT_BREADTH_PATH.read_text())
    assert set(data) >= {"dates", "above_50d", "above_200d", "coverage", "through", "source", "method"}
    assert data["dates"][0] <= "2021-11-30" and data["through"] == data["dates"][-1]
    assert len(data["dates"]) == len(data["above_50d"]) == len(data["above_200d"]) == len(data["coverage"])
    assert all(70 <= c <= 100 for c in data["coverage"])
    assert not {"members", "tickers", "prices", "closes"} & set(data)
