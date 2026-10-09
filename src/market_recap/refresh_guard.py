"""Skip the delayed fallback only when a current evening edition is live.

A successful Actions run can be deploy=false, or (before the edition-session
check) a stale build. A green badge alone is not proof the recap is published.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os

from .compute.catalysts import latest_completed_session
from .config import load_config
from .sources import http

EVENING_LOOKBACK = timedelta(hours=10)


def current_evening(manifest: dict, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    try:
        generated = datetime.fromisoformat(manifest["generated_at"].replace("Z", "+00:00"))
        if generated.tzinfo is None:
            return False
        return (manifest.get("edition") == "evening"
                and manifest.get("as_of") == latest_completed_session(now).isoformat()
                and not manifest.get("errors")
                and timedelta(0) <= now - generated <= EVENING_LOOKBACK)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--successful-evenings", type=int, required=True)
    args = parser.parse_args()
    skip = False
    if args.successful_evenings > 0:
        url = load_config()["monitor"]["published_base_url"].rstrip("/") + "/artifacts/manifest.json"
        try:
            manifest = json.loads(http.get_text(url, timeout=20, retries=0))
            skip = current_evening(manifest)
            print(f"fallback: live edition={manifest.get('edition')} as_of={manifest.get('as_of')}")
        except (http.FetchError, ValueError, TypeError, AttributeError) as exc:
            # If the live page cannot be verified, try the refresh rather than
            # freezing it on an unrelated successful workflow.
            print(f"fallback: cannot verify a current published evening edition: {exc}")
    output = f"run={'false' if skip else 'true'}"
    print(f"fallback: {'current evening edition is published; skipping' if skip else 'refresh required'}")
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(output + "\n")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
