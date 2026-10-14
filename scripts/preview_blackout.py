"""Attach calendar differences to the existing local blackout curve; no fetches.

Preserves every level and artifact date. Does not make this reconstructed
curve point-in-time, refresh earnings dates or update the parent manifest.
"""

import json

from market_recap.compute.blackout import calendar_momentum
from market_recap.config import ARTIFACT_DIR, load_config
from market_recap.util import write_json


def main():
    path = ARTIFACT_DIR / "positioning.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    b = payload["blackout"]
    b["momentum"] = calendar_momentum(b["dates"], b["share_pct"], b["as_of"],
                                     load_config()["positioning"]["blackout_change_calendar_days"])
    write_json(path, payload)
    print(json.dumps({"as_of": b["as_of"], "now_pct": b["now_pct"], "windows": [
        {k: v for k, v in w.items() if not isinstance(v, list)} for w in b["momentum"]["windows"]]}, indent=2))


if __name__ == "__main__":
    main()
