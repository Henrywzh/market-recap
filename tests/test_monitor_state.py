"""Tests for the MONITOR observation-ledger boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_recap.sources import monitor_state
from market_recap.sources.http import FetchError


AS_OF = "2026-09-23"


def _row(
    ticker: str = "AAA",
    *,
    in_universe: bool = True,
    drawdown: float | None = -10.0,
    history: list[list[object]] | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "name": "Example Corp",
        "sector": "Information Technology",
        "in_universe": in_universe,
        "drawdown_pct": drawdown,
        "price_as_of": AS_OF,
        "history": history if history is not None else [["2026-09-22", -12.0], [AS_OF, -10.0]],
        "market_excess_pct": 1.2,
        "sector_excess_pct": 0.7,
        "market_benchmark": "SPX",
        "sector_benchmark": "XLK",
        "rs_improving": True,
        "above_ma": True,
        "pe": 20.0,
        "pe_percentile": 55.0,
        "pe_vs_median": 2.0,
        "fcf_positive": True,
        "revenue_growth_pct": 8.0,
        "filed": "2026-08-01",
        "period_end": "2026-06-30",
        "earnings_date": "2026-10-20",
        "earnings_status": "scheduled",
        "estimate_revision": None,
        "gaps": [],
    }


def _payload(*, rows: list[dict] | None = None, as_of: str = AS_OF) -> dict:
    return {
        "schema_version": 1,
        "as_of": as_of,
        "tracking_started": "2026-09-22",
        "universe": {
            "key": "SPX",
            "label": "S&P 500",
            "members": 1,
            "holdings_as_of": "2026-09-22",
        },
        "settings": {
            "index": "SPX",
            "drawdown_period": "1Y",
            "threshold_pct": 20.0,
            "relative_period": "1M",
            "ma_sessions": 20,
            "earnings_days": 30,
            "drawdown_sessions": 252,
            "relative_sessions": 21,
            # This is deployment plumbing and must not make a prior ledger
            # incompatible with the current analytic settings.
            "published_base_url": "https://old.example.test",
        },
        "rows": rows if rows is not None else [_row()],
        "notices": [],
        "note": "observed prospectively",
    }


def _manifest(
    as_of: str = AS_OF,
    *,
    has_monitor: bool = True,
    monitor_schema_version: int | None = None,
    skipped_panels: list[str] | None = None,
    errors: dict | None = None,
    generated_at: str | None = None,
) -> str:
    manifest = {"as_of": as_of, "panels": ["monitor"] if has_monitor else []}
    if monitor_schema_version is not None:
        manifest["monitor_schema_version"] = monitor_schema_version
    if skipped_panels is not None:
        manifest["skipped_panels"] = skipped_panels
    if errors is not None:
        manifest["errors"] = errors
    if generated_at is not None:
        manifest["generated_at"] = generated_at
    return json.dumps(manifest)


def test_validate_previous_accepts_v1_and_returns_the_same_payload():
    payload = _payload()

    assert monitor_state.validate_previous(payload) is payload


def test_local_absence_is_bootstrap_but_corrupt_json_is_a_failure(tmp_path: Path):
    path = tmp_path / "monitor.json"

    assert monitor_state.load_previous(local_path=path) is None

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        monitor_state.load_previous(local_path=path)


def test_local_artifact_directory_is_supported(tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    path = artifact_dir / "monitor.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    assert monitor_state.load_previous(local_path=artifact_dir) == _payload()


@pytest.mark.parametrize("version", [0, 2, "1"])
def test_old_or_invalid_schema_version_is_rejected(version):
    payload = _payload()
    payload["schema_version"] = version

    with pytest.raises(ValueError, match="schema_version"):
        monitor_state.validate_previous(payload)


@pytest.mark.parametrize(
    "history",
    [
        [["2026-09-22", -12.0], ["2026-09-22", -10.0]],
        [[AS_OF, -10.0], ["2026-09-22", -12.0]],
        [["2026-09-21", -12.0]],
        [["2026-09-24", -12.0]],
        [],
        [["2026-09-22", -12.0]],
        [["2026-09-22", -12.0], [AS_OF, -9.0]],
    ],
)
def test_history_must_be_unique_sorted_and_within_tracking_window(history):
    payload = _payload()
    payload["rows"][0]["history"] = history

    with pytest.raises(ValueError, match="history|observation"):
        monitor_state.validate_previous(payload)


@pytest.mark.parametrize("drawdown", [1.0, -100.1, float("nan"), float("inf")])
def test_drawdowns_are_finite_null_or_negative_percentages(drawdown):
    payload = _payload()
    payload["rows"][0]["drawdown_pct"] = drawdown

    with pytest.raises(ValueError, match="drawdown|finite"):
        monitor_state.validate_previous(payload)


def test_price_as_of_is_a_quote_date_not_a_numeric_price():
    payload = _payload()
    payload["rows"][0]["price_as_of"] = 100.0

    with pytest.raises(ValueError, match="price_as_of"):
        monitor_state.validate_previous(payload)


def test_duplicate_ticker_identities_are_rejected_case_insensitively():
    payload = _payload(rows=[_row(), _row("aaa")])
    payload["rows"][1]["in_universe"] = True

    with pytest.raises(ValueError, match="duplicate ticker identity"):
        monitor_state.validate_previous(payload)


def test_universe_list_form_still_checks_exact_membership():
    payload = _payload()
    payload["universe"]["members"] = ["AAA"]

    assert monitor_state.validate_previous(payload) is payload

    payload["rows"][0]["in_universe"] = False
    for field in monitor_state._LATEST_METRICS:
        payload["rows"][0][field] = None
    with pytest.raises(ValueError, match="current universe"):
        monitor_state.validate_previous(payload)


def test_removed_member_is_retained_only_with_null_latest_metrics():
    removed = _row(
        "OLD",
        in_universe=False,
        drawdown=None,
        history=[["2026-09-22", -30.0], [AS_OF, None]],
    )
    for field in (
        "price_as_of",
        "market_excess_pct",
        "sector_excess_pct",
        "market_benchmark",
        "sector_benchmark",
        "rs_improving",
        "above_ma",
        "pe",
        "pe_percentile",
        "pe_vs_median",
        "fcf_positive",
        "revenue_growth_pct",
        "filed",
        "period_end",
        "earnings_date",
        "earnings_status",
        "estimate_revision",
    ):
        removed[field] = None
    payload = _payload(rows=[_row(), removed])

    assert monitor_state.validate_previous(payload) is payload

    payload["rows"][1]["pe"] = 17.0
    with pytest.raises(ValueError, match="removed symbols"):
        monitor_state.validate_previous(payload)


def test_published_manifest_without_monitor_is_explicit_bootstrap(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    def fake_get_text(url: str, **_kwargs) -> str:
        calls.append(url)
        return _manifest(has_monitor=False)

    monkeypatch.setattr(monitor_state, "get_text", fake_get_text)
    # The remote manifest is authoritative; a corrupt local file is ignored.
    local_path = tmp_path / "monitor.json"
    local_path.write_text("not json", encoding="utf-8")

    assert monitor_state.load_previous(
        local_path=local_path,
        published_base_url="https://example.test",
    ) is None
    assert calls == ["https://example.test/artifacts/manifest.json"]


@pytest.mark.parametrize(
    "manifest",
    [
        _manifest(has_monitor=False, monitor_schema_version=1),
        _manifest(has_monitor=False, skipped_panels=["monitor"]),
        _manifest(has_monitor=False, errors={"monitor": "failed"}),
    ],
)
def test_partial_new_manifest_without_monitor_is_a_failure(manifest, monkeypatch):
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: manifest)

    with pytest.raises(ValueError, match="monitor"):
        monitor_state.load_previous(
            local_path=Path("unused.json"),
            published_base_url="https://example.test",
        )


def test_published_monitor_is_read_without_cache_and_manifest_is_rechecked(monkeypatch):
    payload = _payload()
    stamp = "2026-09-23T18:31:22Z"
    payload["generated_at"] = stamp
    responses = iter([
        _manifest(monitor_schema_version=1, generated_at=stamp),
        json.dumps(payload),
        _manifest(monitor_schema_version=1, generated_at=stamp),
    ])
    calls: list[str] = []
    options: list[dict] = []

    def fake_get_text(url: str, **kwargs) -> str:
        calls.append(url)
        options.append(kwargs)
        return next(responses)

    monkeypatch.setattr(monitor_state, "get_text", fake_get_text)

    assert monitor_state.load_previous(
        local_path=Path("unused.json"),
        published_base_url="https://example.test/",
    ) == payload
    assert calls == [
        "https://example.test/artifacts/manifest.json",
        "https://example.test/artifacts/monitor.json",
        "https://example.test/artifacts/manifest.json",
    ]
    assert options == [
        {"timeout": 20.0, "retries": 1},
        {"timeout": 20.0, "retries": 1},
        {"timeout": 20.0, "retries": 1},
    ]


def test_published_advertised_but_html_monitor_is_a_failure(monkeypatch):
    responses = iter([_manifest(), "<!doctype html><html>SPA fallback</html>"])
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(responses))

    with pytest.raises(ValueError, match="HTML|JSON"):
        monitor_state.load_previous(
            local_path=Path("unused.json"),
            published_base_url="https://example.test",
        )


def test_published_advertised_but_missing_monitor_is_a_failure(monkeypatch):
    calls = 0

    def fake_get_text(url: str, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _manifest()
        raise FetchError(f"{url}: not found", not_found=True)

    monkeypatch.setattr(monitor_state, "get_text", fake_get_text)

    with pytest.raises(FetchError):
        monitor_state.load_previous(
            local_path=Path("unused.json"),
            published_base_url="https://example.test",
        )


def test_published_manifest_race_retries_then_accepts_stable_pair(monkeypatch):
    payload = _payload()
    first_manifest = _manifest(AS_OF)
    drifted_manifest = _manifest("2026-09-22")
    responses = iter([
        first_manifest,
        json.dumps(payload),
        drifted_manifest,
        first_manifest,
        json.dumps(payload),
        first_manifest,
    ])
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(responses))

    assert monitor_state.load_previous(
        local_path=Path("unused.json"),
        published_base_url="https://example.test",
    ) == payload


def test_published_manifest_race_is_bounded_and_raises(monkeypatch):
    payload = _payload()
    responses: list[str] = []
    for _ in range(monitor_state.PUBLISHED_READ_ATTEMPTS):
        responses.extend([_manifest(AS_OF), json.dumps(payload), _manifest("2026-09-22")])
    stream = iter(responses)
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(stream))

    with pytest.raises(ValueError, match="raced"):
        monitor_state.load_previous(
            local_path=Path("unused.json"),
            published_base_url="https://example.test",
        )


def test_published_generated_at_race_is_bounded_and_raises(monkeypatch):
    payload = _payload()
    payload["generated_at"] = "build-a"
    responses: list[str] = []
    for _ in range(monitor_state.PUBLISHED_READ_ATTEMPTS):
        responses.extend([
            _manifest(monitor_schema_version=1, generated_at="build-a"),
            json.dumps(payload),
            _manifest(monitor_schema_version=1, generated_at="build-b"),
        ])
    stream = iter(responses)
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(stream))

    with pytest.raises(ValueError, match="generated_at|raced"):
        monitor_state.load_previous(
            local_path=Path("unused.json"),
            published_base_url="https://example.test",
        )


def test_nonhistorical_setting_changes_do_not_invalidate_drawdown_history(monkeypatch):
    payload = _payload()
    monkeypatch.setattr(
        monitor_state.dashboard_config,
        "load_config",
        lambda: {
            "monitor": {
                "index": "SPX",
                "drawdown_period": "1Y",
                "threshold_pct": 25.0,
                "relative_period": "3M",
                "ma_sessions": 50,
                "earnings_days": 45,
                "published_base_url": "https://a.example",
            }
        },
    )

    assert monitor_state.validate_previous(payload) is payload


@pytest.mark.parametrize("key, value", [("index", "NDX"), ("drawdown_period", "2Y")])
def test_index_and_drawdown_window_changes_invalidate_history(monkeypatch, key, value):
    configured = {
        "index": "SPX",
        "drawdown_period": "1Y",
        "threshold_pct": 20.0,
        "relative_period": "1M",
        "ma_sessions": 20,
        "earnings_days": 30,
    }
    configured[key] = value
    monkeypatch.setattr(monitor_state.dashboard_config, "load_config", lambda: {"monitor": configured})

    with pytest.raises(ValueError, match=key):
        monitor_state.validate_previous(_payload())


def test_nested_config_settings_are_supported():
    payload = _payload()
    flat = payload["settings"]
    payload["settings"] = {
        "config": {key: value for key, value in flat.items() if key != "published_base_url"},
        "published_base_url": "https://another.example",
    }

    assert monitor_state.validate_previous(payload) is payload


def test_published_manifest_as_of_must_match_monitor(monkeypatch):
    payload = _payload()
    responses: list[str] = []
    for _ in range(monitor_state.PUBLISHED_READ_ATTEMPTS):
        responses.extend([_manifest("2026-09-22"), json.dumps(payload), _manifest("2026-09-22")])
    stream = iter(responses)
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(stream))

    with pytest.raises(ValueError, match="raced|as_of"):
        monitor_state.load_previous(
            local_path=Path("unused.json"),
            published_base_url="https://example.test",
        )


def _carried_manifest(as_of: str = "2026-09-24", *, state_as_of: str = AS_OF,
                      state_generated_at: str | None = "old-build", since: str = "2026-09-24") -> str:
    return json.dumps({
        "as_of": as_of, "panels": ["monitor"], "monitor_schema_version": 1, "generated_at": "new-build",
        "monitor_carried": {"as_of": state_as_of, "generated_at": state_generated_at,
                            "since": since, "reason": "RuntimeError: x"},
    })


def test_a_carried_ledger_is_read_back_under_its_own_dates(monkeypatch):
    payload = _payload()
    payload["generated_at"] = "old-build"
    responses = iter([_carried_manifest(), json.dumps(payload), _carried_manifest()])
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(responses))
    assert monitor_state.load_previous(
        local_path=Path("unused.json"), published_base_url="https://example.test",
    ) == payload


def test_a_carried_ledger_must_match_the_carried_dates(monkeypatch):
    payload = _payload()
    payload["generated_at"] = "some-other-build"
    responses: list[str] = []
    for _ in range(monitor_state.PUBLISHED_READ_ATTEMPTS):
        responses.extend([_carried_manifest(), json.dumps(payload), _carried_manifest()])
    stream = iter(responses)
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(stream))
    with pytest.raises(ValueError, match="raced"):
        monitor_state.load_previous(local_path=Path("unused.json"), published_base_url="https://example.test")


def test_carry_returns_the_live_text_even_when_this_code_rejects_it(monkeypatch):
    payload = _payload()
    payload["schema_version"] = 99  # a ledger this code no longer accepts
    payload["generated_at"] = "stamp"
    text = json.dumps(payload)
    manifest = _manifest(monitor_schema_version=1, generated_at="stamp")
    responses = iter([manifest, text, manifest])
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(responses))
    carried, record = monitor_state.carry_published("https://example.test", today="2026-09-24", reason="why")
    assert carried == text
    assert record == {"as_of": AS_OF, "generated_at": "stamp", "since": "2026-09-24", "reason": "why"}


def test_consecutive_carries_keep_the_first_missed_session(monkeypatch):
    payload = _payload()
    payload["generated_at"] = "old-build"
    manifest = _carried_manifest(since="2026-09-24")
    responses = iter([manifest, json.dumps(payload), manifest])
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: next(responses))
    _, record = monitor_state.carry_published("https://example.test", today="2026-09-25", reason="again")
    assert record["since"] == "2026-09-24" and record["as_of"] == AS_OF


def test_carry_refuses_a_manifest_that_lost_monitor(monkeypatch):
    monkeypatch.setattr(monitor_state, "get_text",
                        lambda _url, **_kwargs: _manifest(has_monitor=False, monitor_schema_version=1))
    with pytest.raises(ValueError, match="monitor"):
        monitor_state.carry_published("https://example.test", today="2026-09-24", reason="x")


def test_carried_record_cannot_postdate_the_manifest(monkeypatch):
    bad = _carried_manifest(as_of="2026-09-22", state_as_of="2026-09-23")
    monkeypatch.setattr(monitor_state, "get_text", lambda _url, **_kwargs: bad)
    with pytest.raises(ValueError, match="monitor_carried"):
        monitor_state.load_previous(local_path=Path("unused.json"), published_base_url="https://example.test")
