import json

import numpy as np
import pandas as pd

from market_recap.panels import technicals


def test_bars_since_bars_start_with_split_adjusted_prices_and_integer_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(technicals, "BARS_ARTIFACT_DIR", tmp_path)
    dates = pd.bdate_range(pd.Timestamp(technicals.BARS_START) - pd.offsets.BDay(3), periods=8)
    prices = pd.DataFrame({"AAA": np.linspace(10, 17, 8), "PENNY": np.linspace(0.5, 0.57, 8)}, index=dates)
    ohlcv = {kind: prices * factor for kind, factor in (("open", 1.0), ("high", 1.01), ("low", 0.99))}
    ohlcv["volume"] = pd.DataFrame({"AAA": [1e6] * 7 + [np.nan], "PENNY": [5e5] * 8}, index=dates)
    assert technicals.bake_bars("AAA", prices, ohlcv)
    out = json.loads((tmp_path / "AAA.json").read_text())
    assert out["dates"][0] >= technicals.BARS_START and len(out["dates"]) == 5
    assert out["volume"][:4] == [1000000] * 4 and out["volume"][-1] is None
    assert out["close"][0] == round(prices["AAA"].loc[technicals.BARS_START:].iloc[0], 2)
    assert technicals.bake_bars("PENNY", prices, ohlcv)
    penny = json.loads((tmp_path / "PENNY.json").read_text())
    assert penny["close"][0] == round(prices["PENNY"].loc[technicals.BARS_START:].iloc[0], 4)
    assert not technicals.bake_bars("MISSING", prices, ohlcv)
