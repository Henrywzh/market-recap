"""A green evening job must not suppress the fallback while old prices are live."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from market_recap import context, refresh_guard, validate
from market_recap.compute.catalysts import latest_completed_session
from market_recap.sources import yahoo


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("UTC"))


@pytest.mark.parametrize("stamp,expected", [
    ("2026-10-08T00:13:35", "2026-10-07"),  # next UTC day, still NY evening
    ("2026-10-08T14:00:00", "2026-10-07"),  # intraday isn't a close
    ("2026-10-08T20:35:00", "2026-10-08"),  # EDT close
    ("2026-12-08T21:35:00", "2026-12-08"),  # EST close
    ("2026-09-07T23:00:00", "2026-09-04"),  # Labor Day
    ("2026-10-11T23:00:00", "2026-10-09"),  # Sunday
    ("2026-11-27T18:14:00", "2026-11-25"),  # early close, not settled
    ("2026-11-27T18:15:00", "2026-11-27"),  # early close settled
])
def test_expected_session_uses_market_time_and_the_existing_calendar(stamp, expected):
    assert latest_completed_session(utc(stamp)).isoformat() == expected


def evening(**changes):
    return {"edition": "evening", "as_of": "2026-10-07",
            "generated_at": "2026-10-08T00:13:35Z", "errors": {}, **changes}


@pytest.mark.parametrize("edition", ["close", "evening"])
def test_old_session_blocks_even_a_self_consistent_strict_edition(edition):
    findings = validate._check_current_edition(evening(edition=edition, as_of="2026-10-06"))
    assert len(findings) == 1 and findings[0].severity == "error"
    assert "2026-10-07" in findings[0].detail
    assert not validate._check_current_edition(evening(edition=edition))


def test_edition_check_ignores_manual_history_but_rejects_invalid_build_time():
    assert not validate._check_current_edition({"as_of": "2024-01-01"})
    assert validate._check_current_edition(evening(generated_at="bad"))
    assert validate._check_current_edition(evening(generated_at="2026-10-08T00:13:35"))


def test_current_published_evening_is_required_before_skipping():
    now = utc("2026-10-08T02:59:49")
    assert refresh_guard.current_evening(evening(), now=now)
    for changes in [
        {"as_of": "2026-10-06"}, {"edition": "close"}, {"edition": None},
        {"errors": {"markets": "failed"}}, {"generated_at": "bad"},
        {"generated_at": "2026-10-07T12:00:00Z"},
        {"generated_at": "2026-10-08T03:00:00Z"},
    ]:
        assert not refresh_guard.current_evening(evening(**changes), now=now)


def test_stale_edition_is_not_deployable_in_the_real_validator(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(validate, "ARTIFACT_DIR", tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps(evening(as_of="2026-10-06", panels=[])))
    report = validate.run()
    assert not report["ok"] and not report["deployable"]
    assert any(f["check"] == "edition_session" for f in report["findings"])


def test_no_complete_price_row_is_not_a_completed_session():
    frame = pd.DataFrame({"A": [1.0], "B": [None]}, index=pd.to_datetime(["2026-10-07"]))
    assert context.completed_sessions(frame, now=utc("2026-10-08T00:00:00")).empty


def test_a_recently_written_cache_of_old_prices_is_still_stale(monkeypatch, tmp_path):
    now = utc("2026-10-08T02:00:00")
    monkeypatch.setattr(yahoo.cache, "is_fresh", lambda *a, **k: True)
    monkeypatch.setattr(yahoo.cache, "modified", lambda path: now)
    frame = pd.DataFrame({"A": [1.0]}, index=pd.to_datetime(["2026-10-06"]))
    monkeypatch.setattr(pd, "read_parquet", lambda path: frame)
    assert yahoo._read(tmp_path / "closes.parquet", now=now).empty
    frame.index = pd.to_datetime(["2026-10-07"])
    assert not yahoo._read(tmp_path / "closes.parquet", now=now).empty


def test_yahoo_retries_history_that_lacks_the_required_close(monkeypatch):
    monkeypatch.setattr(yahoo, "latest_completed_session", lambda: date(2026, 10, 7))
    monkeypatch.setattr(yahoo.time, "sleep", lambda *a: None)
    old = pd.DataFrame({"A": [10.0]}, index=pd.to_datetime(["2026-10-06"]))
    fresh = pd.DataFrame({"A": [11.0]}, index=pd.to_datetime(["2026-10-07"]))
    calls = []

    def download(chunk, period):
        calls.append(chunk)
        frame = old if len(calls) == 1 else fresh
        return {"closes": frame, **{kind: frame for kind in yahoo.OHLCV_REQUIRED}}

    monkeypatch.setattr(yahoo, "_download_chunk", download)
    frame = yahoo.fetch_closes(["A"], use_cache=False, retries=1, need_ohlcv=True)
    assert calls == [["A"], ["A"]]
    assert frame.loc["2026-10-07", "A"] == 11.0
    assert frame.loc["2026-10-06", "A"] == 10.0


def test_yahoo_keeps_missing_latest_values_missing_after_retries(monkeypatch):
    monkeypatch.setattr(yahoo, "latest_completed_session", lambda: date(2026, 10, 7))
    monkeypatch.setattr(yahoo.time, "sleep", lambda *a: None)
    old = pd.DataFrame({"A": [10.0]}, index=pd.to_datetime(["2026-10-06"]))
    monkeypatch.setattr(yahoo, "_download_chunk", lambda *a: {
        "closes": old, **{kind: pd.DataFrame() for kind in yahoo.OHLCV_REQUIRED}})
    frame = yahoo.fetch_closes(["A"], use_cache=False, retries=1)
    assert pd.Timestamp("2026-10-07") not in frame.index


def test_fallback_runs_when_live_manifest_cannot_be_verified(monkeypatch, capsys):
    from market_recap.sources.http import FetchError
    monkeypatch.setattr("sys.argv", ["refresh_guard", "--successful-evenings", "1"])
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    def fail(*a, **k):
        raise FetchError("unavailable")

    monkeypatch.setattr(refresh_guard.http, "get_text", fail)
    assert refresh_guard.main() == 0
    assert "run=true" in capsys.readouterr().out
