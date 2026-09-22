"""Development server for the static site.

Python's stock ``http.server`` lets the browser cache ES modules, so an edit to
a tab module keeps rendering the previous build until the cache is cleared by
hand -- which looks exactly like the edit not having been written. This server
answers with ``no-store`` so a reload always picks up what is on disk.
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # quieter dev output
        if "GET /artifacts" in (fmt % args):
            return
        super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the dashboard for local development.")
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()

    handler = partial(NoCacheHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"market-recap dev server: http://localhost:{args.port}/web/index.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
