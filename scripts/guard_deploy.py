"""Refuse to publish a build dated earlier than what the site already shows.

Validation checks a build against its own contract; it cannot know that the
page is already a session ahead. The first cloud run proved the gap: a cache
from other library versions produced a strict-clean build one session older
than the live page, and the deploy moved the site backwards. Equal is fine (a
rerun); only older is refused.

It also refuses a manifest that does not account for every panel the live one
lists. A local ``refresh --panels X`` writes a manifest naming X alone; once
published, the nightly MONITOR reads "monitor is missing from panels" from it
and fails closed, and the site stops updating. A panel the build tried and
lost is in ``skipped_panels`` and is allowed: the page shows that gap.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

from market_recap.config import USER_AGENT

BUILT = Path(__file__).resolve().parents[1] / "dist" / "artifacts" / "manifest.json"
TIMEOUT_SECONDS = 20


def main(site_url: str) -> int:
    manifest = json.loads(BUILT.read_text())
    built = manifest["as_of"]
    request = urllib.request.Request(
        f"{site_url}/artifacts/manifest.json", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            published = json.load(response)
            live = published["as_of"]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            # Fail closed: a guard that allows whatever it cannot check is not
            # a guard. (Its first version did exactly that on a 403.)
            print(f"guard: cannot read the live manifest (HTTP {exc.code}); not deploying", file=sys.stderr)
            return 1
        print(f"guard: no live manifest yet; allowing {built}")
        return 0
    if built < live:
        print(f"guard: refusing to deploy as_of {built}; the live site already shows {live}", file=sys.stderr)
        return 1
    covered = set(manifest.get("panels") or []) | set(manifest.get("skipped_panels") or [])
    absent = sorted(set(published.get("panels") or []) - covered)
    if absent:
        print(f"guard: refusing a manifest that omits live panels ({', '.join(absent)}); "
              "a partial rebuild's manifest must not be published", file=sys.stderr)
        return 1
    print(f"guard: as_of {built} (live {live})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
