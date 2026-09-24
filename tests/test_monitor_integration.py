"""The observation ledger must consume this build, not a stale successful one."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from market_recap import build, config
from market_recap.util import BuildLog


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    cfg = config.load_config()
    ctx = SimpleNamespace(config=cfg, as_of="2026-09-23", holdings_as_of="2026-09-23",
                          log=BuildLog(), indices=[], closes=pd.DataFrame(),
                          filled_sessions={}, session_check=None)
    monkeypatch.setattr(build, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(build, "ensure_dirs", lambda: None)
    monkeypatch.setattr(build, "load_config", lambda: cfg)
    monkeypatch.setattr(build, "build_context", lambda **kw: ctx)
    monkeypatch.setattr(build.sec, "filing_check", lambda: {"checked": 0})
    monkeypatch.setattr(build.site, "build", lambda: {})
    monkeypatch.setattr(build, "validate_previous", lambda payload: payload)
    monkeypatch.delenv("MONITOR_PUBLISHED_STATE", raising=False)
    calls = []
    monkeypatch.setattr(build, "load_previous", lambda **kw: calls.append(kw) or None)
    return tmp_path, ctx, calls


def test_monitor_runs_after_selected_dependencies_even_when_requested_first(pipeline, monkeypatch):
    _, ctx, _ = pipeline
    seen = []
    valuation = {"as_of": ctx.as_of, "rows": [{"ticker": "TEST"}]}

    def monitor(ctx, **kw):
        seen.append(kw)
        return {"as_of": ctx.as_of}

    monkeypatch.setattr(build, "PANELS", {"monitor": monitor, "valuation": lambda ctx: valuation})
    manifest = build.run(panels=["monitor", "valuation"], prune_cache=False)
    assert manifest["panels"] == ["valuation", "monitor"]
    assert seen[0]["valuation"] is valuation


def test_failed_dependency_is_not_replaced_with_old_same_date_artifact(pipeline, monkeypatch):
    path, ctx, _ = pipeline
    (path / "valuation.json").write_text(json.dumps({"as_of": ctx.as_of, "old": True}))
    seen = []

    def broken(ctx):
        raise RuntimeError("upstream failure")

    def monitor(ctx, **kw):
        seen.append(kw)
        return {"as_of": ctx.as_of}

    monkeypatch.setattr(build, "PANELS", {"valuation": broken, "monitor": monitor})
    manifest = build.run(prune_cache=False)
    assert seen[0]["valuation"] is None
    assert "valuation" in manifest["errors"]


def test_partial_build_uses_only_matching_session_optional_artifacts(pipeline, monkeypatch):
    path, ctx, _ = pipeline
    (path / "valuation.json").write_text(json.dumps({"as_of": "2026-09-22"}))
    (path / "catalysts.json").write_text(json.dumps({"as_of": ctx.as_of, "events": []}))
    seen = []

    def monitor(ctx, **kw):
        seen.append(kw)
        return {"as_of": ctx.as_of}

    monkeypatch.setattr(build, "PANELS", {"monitor": monitor})
    build.run(prune_cache=False)
    assert seen[0]["valuation"] is None
    assert seen[0]["catalysts"]["as_of"] == ctx.as_of


def test_cloud_build_uses_published_state_and_failure_blocks_monitor(pipeline, monkeypatch):
    path, ctx, _ = pipeline
    monkeypatch.setenv("MONITOR_PUBLISHED_STATE", "1")
    called = []

    def broken_restore(**kw):
        called.append(kw)
        raise ValueError("published ledger is corrupt")

    monkeypatch.setattr(build, "load_previous", broken_restore)
    monkeypatch.setattr(build, "PANELS", {"monitor": lambda ctx, **kw: pytest.fail("must not reset")})
    manifest = build.run(prune_cache=False)
    assert called[0]["published_base_url"] == ctx.config["monitor"]["published_base_url"]
    assert manifest["skipped_panels"] == ["monitor"]
    assert "corrupt" in manifest["errors"]["monitor"]
    assert not (path / "monitor.json").exists()


def test_invalid_new_monitor_payload_does_not_overwrite_previous_ledger(pipeline, monkeypatch):
    path, ctx, _ = pipeline
    previous_bytes = '{"saved":"previous observations"}'
    (path / "monitor.json").write_text(previous_bytes)

    def reject(payload):
        raise ValueError("new ledger does not match its observation history")

    monkeypatch.setattr(build, "validate_previous", reject)
    monkeypatch.setattr(build, "PANELS", {"monitor": lambda ctx, **kw: {"as_of": ctx.as_of}})
    manifest = build.run(prune_cache=False)
    assert manifest["skipped_panels"] == ["monitor"]
    assert (path / "monitor.json").read_text() == previous_bytes
    assert not (path / "monitor.pending").exists()
