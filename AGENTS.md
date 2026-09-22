# Agent notes

Read `README.md` first; it holds the data contract and the design rules.

Keep these invariants:

- `config/dashboard.toml` is the single source of truth for the universe,
  labels and series ids. A builder that hard-codes a ticker is a bug.
- Fetches go through `sources/http.py`, which identifies the client honestly.
  Do not add a browser User-Agent: FRED rejects requests that claim to be a
  browser from a Python TLS stack.
- Panels must not invent values. Missing input stays `None` all the way to the
  page, where it renders as an em dash.
- Keep period definitions in `config.PERIOD_TRADING_DAYS`. Do not measure the
  same window two different ways in two panels.
- The brand block in `config/dashboard.toml` names *your* tool. Do not set it
  to a firm you are not.
