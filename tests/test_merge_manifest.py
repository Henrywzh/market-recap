"""A partial rebuild's manifest must still list the panels it did not rebuild."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("merge_manifest", Path(__file__).parents[1] / "scripts" / "merge_manifest.py")
merge_manifest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge_manifest)


def test_unattempted_panels_survive_and_rebuilt_ones_take_the_new_outcome():
    previous = {"generated_at": "t0", "panels": ["markets", "monitor", "risk"], "skipped_panels": ["themes"],
                "errors": {"themes": "boom"}, "monitor_carried": {"since": "2026-10-01"}}
    new = {"generated_at": "t1", "as_of": "2026-10-02", "panels": ["risk"], "skipped_panels": [], "errors": {}}
    merged = merge_manifest.merge(previous, new)
    assert merged["panels"] == ["markets", "monitor", "risk"]
    assert merged["skipped_panels"] == ["themes"] and merged["errors"] == {"themes": "boom"}
    assert merged["monitor_carried"] == {"since": "2026-10-01"}
    assert merged["as_of"] == "2026-10-02" and merged["generated_at"] == "t1"


def test_a_panel_that_failed_this_run_is_listed_as_skipped_with_its_error():
    previous = {"panels": ["markets", "risk"], "skipped_panels": [], "errors": {}}
    new = {"panels": [], "skipped_panels": ["risk"], "errors": {"risk": "down"}}
    merged = merge_manifest.merge(previous, new)
    assert merged["panels"] == ["markets"] and merged["skipped_panels"] == ["risk"] and merged["errors"] == {"risk": "down"}


def test_a_rebuilt_monitor_replaces_the_carried_marker():
    previous = {"panels": ["monitor"], "monitor_carried": {"since": "x"}}
    merged = merge_manifest.merge(previous, {"panels": ["monitor"], "skipped_panels": [], "errors": {}})
    assert "monitor_carried" not in merged


def test_a_monitor_not_rebuilt_keeps_the_stamp_of_the_build_it_came_from():
    previous = {"generated_at": "t0", "panels": ["monitor", "today"], "skipped_panels": [], "errors": {}}
    merged = merge_manifest.merge(previous, {"generated_at": "t1", "panels": ["today"], "skipped_panels": [], "errors": {}})
    assert merged["monitor_generated_at"] == "t0" and merged["generated_at"] == "t1"
    # A second partial refresh still points at the build that made the monitor.
    again = merge_manifest.merge(merged, {"generated_at": "t2", "panels": ["credit"], "skipped_panels": [], "errors": {}})
    assert again["monitor_generated_at"] == "t0"
    # A rebuilt monitor carries this run's stamp, so no separate one is kept.
    rebuilt = merge_manifest.merge(again, {"generated_at": "t3", "panels": ["monitor"], "skipped_panels": [], "errors": {}})
    assert "monitor_generated_at" not in rebuilt
