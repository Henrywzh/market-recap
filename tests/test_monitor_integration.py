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
                          filled_sessions={}, session_check=None, adjustments=[], price_jumps=[], diagnostics={})
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

    # No test reaches the live site. By default the published ledger cannot be
    # carried either; the carry tests replace this.
    def no_carry(*args, **kwargs):
        raise RuntimeError("live ledger unreachable in tests")

    monkeypatch.setattr(build, "carry_published", no_carry)
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
    # The published ledger can be neither read nor carried: nothing is reset.
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


def test_failed_monitor_carries_the_published_ledger_verbatim(pipeline, monkeypatch):
    path, ctx, _ = pipeline
    monkeypatch.setenv("MONITOR_PUBLISHED_STATE", "1")
    live = '{"as_of": "2026-09-22", "generated_at": "prev", "rows": []}\n'
    seen = {}

    def carry(base_url, *, today, reason):
        seen.update(today=today, reason=reason)
        return live, {"as_of": "2026-09-22", "generated_at": "prev", "since": today, "reason": reason}

    def broken(ctx, **kw):
        raise RuntimeError("schema tightened")

    monkeypatch.setattr(build, "carry_published", carry)
    monkeypatch.setattr(build, "PANELS", {"monitor": broken})
    manifest = build.run(prune_cache=False)
    assert (path / "monitor.json").read_text() == live
    assert "monitor" in manifest["panels"]
    assert "monitor" not in manifest["errors"] and manifest["skipped_panels"] == []
    assert manifest["monitor_carried"]["since"] == ctx.as_of
    assert "schema tightened" in seen["reason"]


def test_monitor_that_can_neither_build_nor_carry_is_a_failure(pipeline, monkeypatch):
    path, _, _ = pipeline
    monkeypatch.setenv("MONITOR_PUBLISHED_STATE", "1")

    def carry(base_url, **kw):
        raise RuntimeError("live ledger unreadable")

    def broken(ctx, **kw):
        raise RuntimeError("build failed")

    monkeypatch.setattr(build, "carry_published", carry)
    monkeypatch.setattr(build, "PANELS", {"monitor": broken})
    manifest = build.run(prune_cache=False)
    assert "monitor" in manifest["errors"] and "monitor_carry" in manifest["errors"]
    assert "monitor_carried" not in manifest
    assert not (path / "monitor.json").exists()


def test_local_monitor_failure_is_not_carried(pipeline, monkeypatch):
    _, _, _ = pipeline
    monkeypatch.setattr(build, "carry_published", lambda *a, **k: pytest.fail("carried a local build"))
    monkeypatch.setattr(build, "PANELS", {"monitor": lambda ctx, **kw: (_ for _ in ()).throw(RuntimeError("x"))})
    manifest = build.run(prune_cache=False)
    assert "monitor" in manifest["errors"]


def test_the_manifest_says_how_long_each_part_of_the_build_took(pipeline, monkeypatch):
    _, ctx, _ = pipeline

    def slow(ctx):
        import time
        time.sleep(0.12)
        ctx.diagnostics["valuation"] = {"seconds": {"fetch": 0.1}, "requests": {"asked": 3}}
        return {"as_of": ctx.as_of}

    def broken(ctx):
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(build, "PANELS", {"valuation": slow, "markets": broken})
    manifest = build.run(prune_cache=False)
    timings = manifest["timings"]
    assert set(timings["panels"]) == {"valuation", "markets"}      # a failed panel is timed too
    assert timings["panels"]["valuation"] >= 0.1
    assert timings["context"] >= 0 and "sec_check" in timings
    # A panel's own account of its run reaches the manifest as written.
    assert manifest["diagnostics"]["valuation"]["requests"] == {"asked": 3}


def test_frame_values_reads_a_date_exactly_as_series_value_does():
    import numpy as np
    import pandas as pd
    from market_recap.compute import monitor as M

    index = pd.to_datetime(["2026-10-05", "2026-10-06", "2026-10-06", "2026-10-07"])
    frame = pd.DataFrame({
        "A": [1.0, 2.0, 3.0, 4.0],          # a duplicated date: the last print
        "B": [1.0, 5.0, np.nan, 4.0],       # ... the last numeric one
        "C": [1.0, np.inf, np.inf, 4.0],    # not finite: no value
        "D": ["x", "7", "y", 4.0],          # text coerced, as series_value does
    }, index=index)
    for day in ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"):
        fast = M.frame_values(frame, day)
        slow = {c: M.series_value(frame, c, day) for c in frame.columns}
        assert fast == {c: v for c, v in slow.items() if v is not None}, day
    twice = pd.DataFrame([[1.0, 2.0]], columns=["A", "A"], index=index[:1])
    assert M.frame_values(twice, "2026-10-05") == {}           # a column named twice is no column


def test_a_clean_close_column_is_taken_as_it_is():
    import numpy as np
    import pandas as pd
    from market_recap.compute import monitor as M

    index = pd.date_range("2026-01-02", periods=6, freq="B")
    clean = pd.Series([1.0, np.nan, 3.0, 4.0, np.nan, 6.0], index=index, name="AAPL")
    fast = M._numeric_series(clean)
    slow = M._numeric_series(clean.astype(object))           # the general path
    pd.testing.assert_series_equal(fast, slow, check_dtype=False)
    shuffled = clean.iloc[[3, 0, 5, 1, 4, 2]]                 # unsorted: the general path still sorts
    pd.testing.assert_series_equal(M._numeric_series(shuffled), slow, check_dtype=False, check_freq=False)
