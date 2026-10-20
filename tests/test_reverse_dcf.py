"""DCF publishes scenario settings without introducing another data source."""
from types import SimpleNamespace

import pandas as pd

from market_recap.config import load_config
from market_recap.panels import dcf
from market_recap.sources import treasury


def test_dcf_passes_configured_reverse_settings(monkeypatch):
    config = load_config()
    records = []
    monkeypatch.setattr(dcf.sec, "fetch_ticker_cik_map", lambda **kwargs: {})
    monkeypatch.setattr(treasury, "fetch_par_yield_curve", lambda: (
        pd.DataFrame([{"date": "2026-10-16", "tenor": config["universe"]["risk_free_tenor"], "yield_pct": 4.0}]), None,
    ))
    monkeypatch.setattr(dcf, "prune_stale", lambda *args: None)
    ctx = SimpleNamespace(
        config=config, as_of="2026-10-16", holdings=pd.DataFrame(),
        closes=pd.DataFrame(), etf_closes=pd.DataFrame(),
        log=SimpleNamespace(add=records.append, fail=lambda *args: None),
    )
    payload = dcf.build(ctx, tickers=[], use_cache=False)
    assert payload["reverse"] == config["dcf"]["reverse"]
    assert payload["as_of"] == "2026-10-16"
    assert payload["available"] == []
    assert payload["reverse"]["terminal_growth_pct"] < payload["reverse"]["wacc_pct"]
    assert records
