"""Holdings names arrive in capitals; the dashboard shows them as issuers write them."""

import pandas as pd
import pytest

from market_recap.util import company_name


@pytest.mark.parametrize("raw, expected", [
    ("JPMORGAN CHASE + CO", "JPMorgan Chase & Co"),
    ("MCDONALD'S CORP", "McDonald's Corp"),
    ("AT&T INC", "AT&T Inc"),
    ("APPLE INC", "Apple Inc"),
    ("S&P GLOBAL INC", "S&P Global Inc"),
    ("3M CO", "3M Co"),
    ("UNITEDHEALTH GROUP INC", "UnitedHealth Group Inc"),
    ("ABBVIE INC", "AbbVie Inc"),
    ("  NVIDIA   CORP  ", "NVIDIA Corp"),
    ("IBM", "IBM"),
])
def test_capitals_become_issuer_names(raw, expected):
    assert company_name(raw) == expected


def test_mixed_case_is_left_alone_apart_from_whitespace():
    assert company_name("Alphabet Inc Class A") == "Alphabet Inc Class A"
    assert company_name("  Alphabet Inc Class A ") == "Alphabet Inc Class A"


@pytest.mark.parametrize("raw", [None, "", "   ", float("nan"), pd.NA])
def test_missing_or_empty_is_blank(raw):
    assert company_name(raw) == ""
