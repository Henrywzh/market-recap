"""Make a partial rebuild's manifest describe the whole published site.

``refresh --panels X`` writes a manifest listing only the panels it built, but
the artifacts of every other panel are still on disk (restored from the last
published build). Published as is, the manifest would drop those panels from
``panels`` -- the page treats a missing MONITOR as a partial session and
scripts/guard_deploy.py refuses a manifest that omits live panels. So the
previous manifest is merged back in: panels this run did not attempt keep their
entry, their recorded failures and any carried MONITOR; panels it did attempt
take this run's outcome. ``as_of`` and ``generated_at`` are this run's.

Afterwards the whole set is validated, so a rebuilt panel dated to a newer
session than the panels beside it (a panel run on a different day from the last
full build) fails here instead of publishing a page with two "todays".

Usage: merge_manifest.py PREVIOUS_MANIFEST_JSON   (rewrites artifacts/manifest.json)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from market_recap import agent_feed, validate
from market_recap.config import ARTIFACT_DIR
from market_recap.util import write_json


def merge(previous: dict, new: dict) -> dict:
    rebuilt = list(new.get("panels") or [])
    failed = list(new.get("skipped_panels") or [])
    attempted = set(rebuilt) | set(failed)

    panels = [name for name in previous.get("panels") or [] if name not in set(failed)]
    panels += [name for name in rebuilt if name not in panels]

    skipped = (set(previous.get("skipped_panels") or []) - set(rebuilt)) | set(failed)
    errors = {name: reason for name, reason in (previous.get("errors") or {}).items() if name not in attempted}
    errors.update(new.get("errors") or {})

    merged = dict(new)
    merged["panels"] = panels
    merged["skipped_panels"] = sorted(skipped)
    merged["errors"] = errors
    if "monitor" in attempted:
        pass  # this run's monitor_carried (or its absence) already says it
    else:
        if previous.get("monitor_carried"):
            merged["monitor_carried"] = previous["monitor_carried"]
        # The published monitor.json is the previous build's, stamped with its
        # generated_at, not this run's: say which, or the next build reading the
        # ledger sees a manifest and a monitor that disagree and takes it for a
        # deploy caught half-way (it refuses to carry the ledger).
        stamp = previous.get("monitor_generated_at") or previous.get("generated_at")
        if "monitor" in panels and stamp:
            merged["monitor_generated_at"] = stamp
    # The sources, timings and indices above are this run's; say so.
    merged["partial_refresh"] = {"rebuilt": rebuilt, "previous_generated_at": previous.get("generated_at")}
    return merged


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    previous = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    new = json.loads((ARTIFACT_DIR / "manifest.json").read_text(encoding="utf-8"))
    merged = merge(previous, new)
    write_json(ARTIFACT_DIR / "manifest.json", merged)
    report = validate.run()
    for finding in report.get("findings", []):
        if finding["severity"] in ("error", "warning"):
            print(f"{finding['severity']}: [{finding['check']}] {finding['detail']}", file=sys.stderr)
    # The feed was written by the refresh from the partial manifest; rewrite it
    # from the merged one so it describes the page that is published.
    print(json.dumps({"agent_feed": agent_feed.write(validation=report)}))
    print(f"merged manifest: {len(merged['panels'])} panels, {len(merged['partial_refresh']['rebuilt'])} rebuilt")
    return 1 if report.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
