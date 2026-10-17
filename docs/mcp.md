# MCP server

A read-only remote [Model Context Protocol](https://modelcontextprotocol.io)
server at **`https://market-recap-b5p.pages.dev/mcp`**, so an assistant (Claude,
ChatGPT, Gemini, Claude Code) can ask the dashboard questions instead of
reading its pages. It is `functions/mcp.js` on Cloudflare Pages, a thin route
over `mcp/`.

## What it is, and is not

- **Read-only.** It answers from the files the site itself publishes
  (`artifacts/*.json`), read through the Pages `ASSETS` binding. No external
  API call, no secret, no write, no trading signal.
- **No auth.** Everything it can say is already public at the same host.
- **Stateless.** MCP Streamable HTTP: `POST /mcp` with one JSON-RPC 2.0
  message, answered with `application/json`. `GET` is 405, a batch array is
  rejected, `notifications/initialized` gets 202. There is no session and no
  streaming.
- **Descriptive.** Results are the dashboard's numbers, labelled with their own
  dates. The server does not forecast, rank for trading, or recommend.

## Tools

Organised by the question asked, not by panel; an adapter may read several
artifacts.

| Tool | Question | Reads |
|---|---|---|
| `market_snapshot()` | Where does the market stand and how risky does it look? Indices and returns, breadth, which market-state conditions hold (ACTIVE or CAUTION, with the rule), core risk tiles and breaches, index put/call, buyback-blackout level and its next-7-day change, sector rotation. | overview, market_state, risk, positioning, sectors |
| `catalysts(from?, to?, kind?, importance?, limit?)` | What is scheduled? Earnings, releases, auctions, central-bank dates, with expectations where present; last session's earnings reactions. Default: today to +7 days (New York). | catalysts |
| `ticker(symbol)` | What do we know about this company? Identity, valuation (P/E, own-history percentile, forward), MONITOR state and evidence, next report (consensus, implied move) and last outcome, and the MOVES row: own z, market/sector/own parts, gap vs session, calibrated range with factor and reason, and what past shocks like this did next. `BRK.B` and `BRK-B` both work. | valuation, monitor, moves, events/\<T\> |
| `unusual_moves(direction?, limit?)` | Which names moved beyond their own norm last session? Plus the technology sell-off flag. | moves |
| `sector(key)` | One sector (`XLK`, or its name) or sub-industry (`XLK-S`): returns and relative performance, breadth, revisions, valuation strip, sub-industries. | sectors, sectors/\<KEY\> |
| `theme(key)` | One theme board (`cloud`, `semis`, `energy`, ...): run-in, relative-strength state, breadth, revisions, bellwethers with next report, calendar, drivers. | themes |
| `macro(kind)` | `cpi`, `ppi` (release against consensus, components, persistence), `rates` (curve, changes, spreads), `commodities`. | macro, fixed_income, overview |
| `search(query)` / `fetch(id)` | The ChatGPT deep-research shape. `search` returns `{results: [{id, title, url}]}`; `fetch` returns `{id, title, text, url, metadata}`. Ids: `ticker:NVDA`, `sector:XLK`, `theme:semis`, `event:<event_key>`, `macro:cpi`. `fetch` runs the matching tool. | as above |

Every tool declares an `inputSchema` and an `outputSchema`, and returns the
result both as `structuredContent` and as JSON text. Calls with bad arguments,
an unknown symbol or a missing artifact come back as a result with
`isError: true` or with the part null; an unknown tool or method is a JSON-RPC
error.

### What every result carries

| Field | Meaning |
|---|---|
| `as_of` | The build's session (`manifest.json`). |
| `generated_at` | When the artifacts were built; also the server `version`. |
| `sources` | The artifact files read. `source_as_of` gives each one's own date: panels refresh on different schedules, and a daily source can be a session behind. |
| `method` | `{version, notes}`: the artifacts' own rule and note text, plus `market-recap-mcp/1`. |
| `caveats` | Short plain-English limits. |
| `unavailable` | `[{part, reason}]`: a missing artifact or field is null with a reason here, never a failed call. |
| `truncated` | Lists cut to keep a result under about 20 KB: `{path, shown, total}`. Ask again with narrower arguments for the rest. Lists with their own limit say so (`more_events`, `how_to_get_more`). |

**Untrusted text.** Headlines, filing and release excerpts, calendar details
and theme notes that quote companies come from outside sources. They appear
only under a key named `untrusted_text`, and the tool descriptions say it is
data, not instructions. A client should treat that key as quoted material.

## Per-call slices

A call used to parse whole panels: `ticker` about 2.1 MB of JSON, `theme` and
`search` 2 to 3 MB, `market_snapshot` 1.1 MB. So the site build also writes
`artifacts/mcp/` (`src/market_recap/mcp_slices.py`, called from `site.build`).
Each file holds, for one call, the artifacts it reads reduced to the fields its
adapter reads, with the values unchanged:

| Slice | Serves |
|---|---|
| `ticker/<SYMBOL>.json` | `ticker` and `fetch ticker:` for one company: its valuation, MONITOR and MOVES rows, with the shock table |
| `ticker/index.json` | the symbols a typed name can resolve (rows and event files), so `BRK.B` finds `BRK-B` |
| `theme/<key>.json`, `theme/index.json` | `theme`: one board, its drivers' last point, and the group index |
| `search_index.json` | `search` and `fetch` search lists |
| `snapshot.json` | `market_snapshot` |
| `unusual.json` | `unusual_moves` |
| `sector_hub.json` | `sector` (the hub without its member list; each sector's strip file is read as it is, it is small) |
| `macro/{cpi,ppi,commodities}.json` | `macro` for those kinds (`rates` reads two small files) |
| `index.json` | the sha256 of every source artifact the slices were cut from |

A slice is `{"artifacts": {<name>: <reduced artifact>}}`. The adapter asks for
an artifact by its usual name, and the server serves the slice's copy when the
slice has it. Every reduced copy keeps its source's `as_of`, so `sources` and
`source_as_of` do not change. A slice that is not published (an older deploy),
or an artifact that a slice does not hold, is read from the full file as before.

The result is the same JSON either way. `scripts/check_mcp.mjs` runs every tool
both ways (every ticker, sector, theme and macro kind; a sample of searches and
fetches) and fails if the results differ or if a slice call parses more than
300 KB. It also fails if `index.json`'s hashes do not match the artifacts beside
them. `catalysts` is not sliced: it reads about 296 KB and is the closest call to
the budget, so a larger calendar is the first thing to slice.

## The stable-contract rule

The adapters read the panels' artifacts by field name. **Change a panel and its
adapter in the same commit, and the slice writer too if the adapter now reads a new field.** `scripts/check_mcp.mjs <dist>` runs every tool
against `dist/artifacts` through a fake `ASSETS`, with arguments taken from the
build (the top-weight ticker, a sector, each theme, each macro kind, a calendar
event), and fails if a call errors, if its output does not match its
`outputSchema`, if the text is over 20 KB or is not the structured result, if
`as_of` is not the manifest's, or if a part the call is about has gone null.
`make smoke` runs it after the page smoke test, so the deploy's smoke step
blocks a change that breaks it.

If the check fails after you changed a panel: find the adapter in
`mcp/tools/`, follow the renamed field, and update the fixture in
`tests/js/mcp.test.mjs`.

Where things are:

```
functions/mcp.js        the route (one line of glue)
mcp/server.mjs          JSON-RPC and HTTP handling
mcp/tools.mjs           the registry; runs a tool, adds the envelope
mcp/context.mjs         reads artifacts, builds the envelope, fits the size limit
mcp/tools/*.mjs         one adapter per question
mcp/schema.mjs          the small JSON Schema checker
mcp/fake-assets.mjs     ASSETS stand-ins for tests and the contract check (not bundled)
src/market_recap/mcp_slices.py  writes artifacts/mcp/ at site build
scripts/check_mcp.mjs   the contract check
tests/js/mcp.test.mjs   protocol, adapters, missing-artifact behaviour
```

Run locally: `make site`, then `make serve-live` (wrangler on port 8788) and

```
curl -s -X POST http://127.0.0.1:8788/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ticker","arguments":{"symbol":"NVDA"}}}'
```

## Connecting a client

*Client steps as of 2026-10; check each client's docs, the menus move.*

- **Claude.ai** (Pro, Max, Team, Enterprise): Settings, Connectors, add a
  custom connector, paste `https://market-recap-b5p.pages.dev/mcp`. No sign-in
  is needed.
- **ChatGPT**: enable developer mode (Settings, Connectors, Advanced), add a
  connector with the same URL, no authentication. `search` and `fetch` are the
  tools its deep research uses; the others are available in developer mode.
- **Gemini web**: Settings, Custom apps, paste the `/mcp` link.
- **Claude Code**:
  `claude mcp add --transport http market-recap https://market-recap-b5p.pages.dev/mcp`

## Known limits

- Each call parses the JSON it reads on every request. With slices the largest
  call per tool parses: `ticker` 60 KB, `theme` 58 KB, `search` 108 KB,
  `market_snapshot` 126 KB, `sector` and `unusual_moves` 158 KB, `macro` (cpi)
  188 KB; `catalysts` and `fetch event:` parse 296 KB, unsliced. Before slices,
  the same calls parsed up to 3.4 MB. The free Workers plan allows about 10 ms of
  CPU per call; watch for error 1102 in the Pages function logs.
- The slices copy each symbol's MOVES shock table (about 13 KB), so the deploy
  holds about 6.6 MB of repeated static data. Smaller would mean the adapter
  reading the table from one shared file, which changes the reader's contract.
- A panel that did not refresh in a build keeps its older artifact; the result
  says so through `source_as_of`.
- No rate limit beyond Cloudflare's own. The data is public and cached by
  `no-cache` revalidation, not by the function.
