"""Decide whether the unattended run may publish the build on disk.

``refresh --strict`` fails on any error or warning, and a failed run used to
publish nothing. That is right for a wrong number -- but when the only finding
is a MONITOR ledger carried forward unchanged (build._carry_monitor), holding
back every other tab just freezes the site, night after night if the cause
persists. The gate lets that one case through; the workflow still fails the
run afterwards so the owner is told.

Writes ``deployable=true|false`` to $GITHUB_OUTPUT when set; always exits 0
so the workflow, not this script, decides what a "no" means.
"""

from __future__ import annotations

import os
import sys

from market_recap import validate


def main() -> int:
    report = validate.run()
    deployable = bool(report.get("deployable"))
    for finding in report.get("findings", []):
        if finding["severity"] in ("error", "warning"):
            print(f"{finding['severity']}: [{finding['check']}] {finding['detail']}", file=sys.stderr)
    print(f"gate: {'deployable' if deployable else 'not deployable'}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"deployable={'true' if deployable else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
