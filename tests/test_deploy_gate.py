"""A build whose only fault is a carried MONITOR ledger may still publish."""

import json

import pytest

from market_recap import validate


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "ARTIFACT_DIR", tmp_path)

    def write(manifest: dict, **panels: dict) -> None:
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        for name, payload in panels.items():
            (tmp_path / f"{name}.json").write_text(json.dumps(payload))

    return write


def _manifest(**extra) -> dict:
    return {
        "as_of": "2026-09-25",
        "panels": ["monitor"],
        "indices": [{"key": "SPX", "members": 503, "priced": 503}],
        "sources": [],
        "errors": {},
        **extra,
    }


CARRIED = {"as_of": "2026-09-24", "generated_at": "old", "since": "2026-09-25", "reason": "RuntimeError: x"}


def test_carried_monitor_alone_is_deployable_but_still_a_warning(artifacts):
    # The carried ledger is older and not even valid under this code: neither blocks.
    artifacts(_manifest(monitor_carried=CARRIED), monitor={"as_of": "2026-09-24", "schema_version": 99})
    report = validate.run()
    assert report["deployable"] is True
    assert report["warnings"] >= 1
    checks = {(f["severity"], f["check"]) for f in report["findings"]}
    assert ("warning", "monitor_carried") in checks
    assert not any(f["check"] in ("as_of", "monitor") for f in report["findings"] if f["severity"] == "error")


def test_any_other_failure_still_blocks_the_deploy(artifacts):
    artifacts(_manifest(monitor_carried=CARRIED, errors={"valuation": "boom"}),
              monitor={"as_of": "2026-09-24", "schema_version": 1})
    assert validate.run()["deployable"] is False


def test_a_failed_monitor_that_was_not_carried_blocks_the_deploy(artifacts):
    artifacts(_manifest(panels=[], errors={"monitor": "boom"}))
    assert validate.run()["deployable"] is False


def test_no_manifest_is_not_deployable(artifacts):
    assert not validate.run().get("deployable")
