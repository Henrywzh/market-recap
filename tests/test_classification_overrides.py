import pandas as pd

from market_recap.config import load_config
from market_recap.context import apply_overrides


def test_an_override_replaces_the_wikipedia_label_and_says_so():
    labelled = pd.DataFrame({
        "yahoo_symbol": ["PG", "CL"], "sector": ["Consumer Staples"] * 2,
        "sub_sector": ["Personal Care Products", "Household Products"], "classification_source": ["wikipedia_gics"] * 2,
    })
    out = apply_overrides(labelled, [{"ticker": "pg", "sub_sector": "Household Products"}])
    assert out["sub_sector"].tolist() == ["Household Products", "Household Products"]
    assert out["sector"].tolist() == ["Consumer Staples"] * 2
    assert out["classification_source"].tolist() == ["config_override", "wikipedia_gics"]
    assert labelled.loc[0, "sub_sector"] == "Personal Care Products"


def test_every_configured_override_states_why_and_when():
    for o in load_config()["universe"].get("classification_overrides") or []:
        assert o.get("ticker") and o.get("reason") and o.get("checked")
