"""Attach index P/C to the existing local positioning artifact; no fetches."""

import json

from market_recap.config import ARTIFACT_DIR, load_config
from market_recap.panels.index_put_call import build_component
from market_recap.util import write_json


def main():
    path = ARTIFACT_DIR / "positioning.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["index_put_call"] = build_component(payload["as_of"], load_config()["positioning"]["index_put_call"])
    write_json(path, payload)
    for row in payload["index_put_call"]["series"]:
        print(row["label"], row["status"], row["coverage"])


if __name__ == "__main__":
    main()
