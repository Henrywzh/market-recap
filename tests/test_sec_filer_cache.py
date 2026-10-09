"""A parsed filer is reused only while everything it was built from holds."""

import json
import os

from market_recap import cache
from market_recap.sources import sec


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(sec, "_checked", {})
    monkeypatch.setattr(sec, "_backfilled", {})
    monkeypatch.setattr(sec, "_unprocessed", {})
    monkeypatch.setattr(sec, "_get", lambda url, timeout: json.dumps({"entityName": "Example", "facts": {}}))
    parses = []
    real = sec.annual_statements
    monkeypatch.setattr(sec, "annual_statements", lambda facts: parses.append(1) or real(facts))
    sec._filer.cache_clear()
    return parses


def test_both_call_forms_share_one_parse(monkeypatch, tmp_path):
    parses = _setup(monkeypatch, tmp_path)
    sec.filer(320193)
    sec.filer(320193, True)
    assert len(parses) == 1


def test_a_kept_filer_is_reused_until_what_it_read_changes(monkeypatch, tmp_path):
    parses = _setup(monkeypatch, tmp_path)
    first = sec.filer(320193)
    sec._filer.cache_clear()
    assert sec.filer(320193) == first and len(parses) == 1   # the next build: read, not parsed

    facts = cache.path_for(f"{sec.NAMESPACE}/facts", "CIK0000320193", ".json" + cache.GZIP_SUFFIX)
    os.utime(facts, ns=(facts.stat().st_mtime_ns + 10**9,) * 2)
    sec._filer.cache_clear()
    sec.filer(320193)
    assert len(parses) == 2                                   # the document changed

    sec._filer.cache_clear()
    sec._checked[320193] = {"latest": None, "refetched": True}
    sec.filer(320193)
    assert len(parses) == 3                                   # a newer filing is due

    sec._filer.cache_clear()
    monkeypatch.setattr(sec, "_code_version", lambda: "changed")
    sec.filer(320193)
    assert len(parses) == 4                                   # the parser changed


def test_what_a_parse_recorded_about_backfills_is_replayed(monkeypatch, tmp_path):
    parses = _setup(monkeypatch, tmp_path)
    real = sec._parse_filer

    def parse_and_backfill(cik, use_cache):
        sec._backfilled[cik] = "0000320193-26-000009"
        return real(cik, use_cache)
    monkeypatch.setattr(sec, "_parse_filer", parse_and_backfill)
    sec.filer(320193)
    sec._backfilled.clear()
    sec._filer.cache_clear()
    sec.filer(320193)
    assert len(parses) == 1
    assert sec._backfilled == {320193: "0000320193-26-000009"}
