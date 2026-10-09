"""Archive today's public DRAMeXchange homepage spot tables on this machine.

History and contract pages are member-only and are not requested. The archive
is gitignored and is not read by the dashboard: the site's terms forbid
republication.
"""

from __future__ import annotations

from datetime import date

from market_recap.sources import dramexchange


def main() -> int:
    html = dramexchange.fetch_homepage()
    path = dramexchange.archive(html, date.today())
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path}")
    print(f"tables {len(payload['tables'])}")
    for table in payload["tables"]:
        print(f"{table['section']}: {len(table['rows'])} rows, updated {table.get('updated') or 'unknown'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
