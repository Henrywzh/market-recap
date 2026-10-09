"""The par curve is downloaded once a year-file, not once per panel."""

from datetime import date

from market_recap import cache
from market_recap.sources import treasury as T

XML = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry><content><m:properties>
    <d:NEW_DATE>2026-10-07T00:00:00</d:NEW_DATE><d:BC_2YEAR>4.80</d:BC_2YEAR><d:BC_10YEAR>5.29</d:BC_10YEAR>
  </m:properties></content></entry>
</feed>"""


def test_each_year_is_fetched_once_and_cached_by_how_final_it_is(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    T._curve.cache_clear()
    asked, kinds = [], {}
    monkeypatch.setattr(T, "get_bytes", lambda url, timeout: asked.append(url) or XML)
    real = cache.fetch_bytes
    monkeypatch.setattr(cache, "fetch_bytes", lambda ns, name, fetch, **kw: kinds.setdefault(name, kw["kind"]) and real(ns, name, fetch, **kw))
    for _ in range(4):                                    # four panels
        frame, _ = T.fetch_par_yield_curve()
    assert len(asked) == 2
    assert set(frame["tenor"]) == {"2Y", "10Y"}
    T._curve.cache_clear()
    T.fetch_par_yield_curve()                             # a new build: read from the cache
    assert len(asked) == 2
    today = date.today().year
    assert kinds == {f"par-{today - 1}": "reference_data", f"par-{today}": "daily_file"}
    T._curve.cache_clear()
    T.fetch_par_yield_curve([today - 3])
    assert kinds[f"par-{today - 3}"] == "archive"
