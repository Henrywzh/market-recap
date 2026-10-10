"""OVERVIEW's own readings of the other panels."""


def test_bond_and_equity_volatility_are_read_from_risks_own_tiles():
    from market_recap.panels.overview import bond_equity_vol

    def tile(key, value, pct, dates, values):
        return {"key": key, "value": value, "pct_1y": pct, "date": dates[-1], "threshold": 130 if key == "move" else 30,
                "history": {"dates": dates, "values": values}}
    dates = ["2026-09-18", "2026-09-25", "2026-10-02", "2026-10-09"]
    risk = {"sections": [
        {"tiles": [tile("vix", 15.0, 17, dates, [20.0, 20.0, 20.0, 15.0])]},
        {"tiles": [tile("move", 99.0, 94, dates, [80.0, 90.0, 100.0, 99.0])]},
    ]}
    out = bond_equity_vol(risk)
    assert out["ratio"] == 6.6 and out["ratio_pct"] == 100          # 4.0, 4.5, 5.0, 6.6: the highest
    assert out["reading"] == "rates"                                 # MOVE high for its year, VIX low
    assert out["ratio_since"] == "2026-09-18"
    risk["sections"][0]["tiles"][0]["pct_1y"] = 90
    assert bond_equity_vol(risk)["reading"] == "both"
    risk["sections"][0]["tiles"][0]["pct_1y"] = 80
    risk["sections"][1]["tiles"][0]["pct_1y"] = 50
    assert bond_equity_vol(risk)["reading"] == "in_line"
    assert bond_equity_vol(None) is None
