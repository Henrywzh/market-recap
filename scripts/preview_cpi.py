"""Refresh CPI only for a local preview; leave other data/session dates alone.

Run with the project Python, then `make site`. This is not a full refresh and
does not update the manifest or publish anything.
"""

import json
from types import SimpleNamespace

from market_recap.config import ARTIFACT_DIR, load_config
from market_recap.panels import cpi
from market_recap.compute.inflation_releases import attach
from market_recap.util import BuildLog, write_json


def main():
    path = ARTIFACT_DIR / "macro.json"
    original = path.read_text(encoding="utf-8")
    payload = json.loads(original)
    log = BuildLog()
    payload = attach({**payload, 'cpi': cpi.build(SimpleNamespace(config=load_config(), log=log))}, payload)
    if path.read_text(encoding='utf-8') != original:
        raise RuntimeError('Macro artifact changed during preview; retry without overwriting it')
    # Atomic replacement, without changing prices, PCE, as_of or the manifest.
    pending = path.with_suffix(".pending")
    write_json(pending, payload)
    pending.replace(path)
    result = payload["cpi"]
    print(json.dumps({"retained_macro_as_of": payload.get("as_of"),
                      "cpi_status": result["status"], "cpi_month": result.get("month"),
                      "failed_sources": result.get("failed_sources", {}),
                      "reason": result.get("reason")}))


if __name__ == "__main__":
    main()
