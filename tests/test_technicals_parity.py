"""The browser computes every technical indicator; pandas is the reference.

The TECHNICALS tab's maths lives in ``web/js/technicals-math.js`` so the
reader's choice of windows needs no rebuild. These tests run that module under
node on a random walk and hold it to the pandas definitions it replaced:
sample standard deviation, ``ewm(adjust=False)``, trailing windows.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

MODULE = Path(__file__).resolve().parents[1] / "web" / "js" / "technicals-math.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _run(expression: str, values: list[float]) -> dict:
    script = (
        f"import * as T from {json.dumps(MODULE.as_uri())};\n"
        f"const values = {json.dumps(values)};\n"
        f"process.stdout.write(JSON.stringify({expression}));\n"
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def walk() -> pd.Series:
    rng = np.random.default_rng(7)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, 600))))


def _close(js: list, reference: pd.Series) -> None:
    got = pd.Series([np.nan if v is None else v for v in js], dtype=float)
    pd.testing.assert_series_equal(got, reference.reset_index(drop=True).astype(float), check_names=False, rtol=1e-9, atol=1e-9)


def test_moving_average_std_and_zscore_match_pandas(walk):
    out = _run("{sma: T.sma(values, 50), std: T.rollingStd(values, 50), z: T.zscore(values, 200)}", walk.tolist())
    _close(out["sma"], walk.rolling(50, min_periods=50).mean())
    _close(out["std"], walk.rolling(50, min_periods=50).std())
    mean, sigma = walk.rolling(200, min_periods=200).mean(), walk.rolling(200, min_periods=200).std()
    _close(out["z"], (walk - mean) / sigma)


def test_macd_matches_pandas_ewm(walk):
    out = _run("T.macd(values, {fast: 8, slow: 17, signal: 9})", walk.tolist())
    line = walk.ewm(span=8, adjust=False).mean() - walk.ewm(span=17, adjust=False).mean()
    signal = line.ewm(span=9, adjust=False).mean()
    _close(out["macd"], line)
    _close(out["signal"], signal)
    _close(out["histogram"], line - signal)


def test_forward_returns_match_a_pandas_grouping(walk):
    rows = _run("T.forwardReturnByBand(values, 200, 40)", walk.tolist())
    mean, sigma = walk.rolling(200, min_periods=200).mean(), walk.rolling(200, min_periods=200).std()
    frame = pd.DataFrame({"z": (walk - mean) / sigma, "fwd": (walk.shift(-40) / walk - 1) * 100}).dropna()
    assert sum(r["count"] for r in rows) == len(frame)
    edges = [-np.inf, -2.0, -1.5, -0.5, 0.5, 1.5, 2.0, np.inf]
    for row, low, high in zip(rows, edges, edges[1:]):
        bucket = frame[(frame["z"] >= low) & (frame["z"] < high)]["fwd"]
        assert row["count"] == len(bucket)
        if len(bucket):
            assert row["mean"] == pytest.approx(bucket.mean())
            assert row["median"] == pytest.approx(bucket.median())
            assert row["hitRate"] == pytest.approx((bucket > 0).mean() * 100)
