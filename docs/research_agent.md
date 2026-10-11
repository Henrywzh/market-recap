# Research agent interface

What an outside research agent (the ChatGPT investment project) can read from
this repository's published site, how to read it, and how to ask for more.

Owners: Claude for this repository's data and feed; Codex for
`alternative-data` and its own feeds; the research agent consumes evidence and
keeps its theses, queue and decision log privately. Nothing here reads or
stores those, and nothing private is published: the site is public, so every
file below is too.

## Files

| URL | What it is |
|---|---|
| `https://market-recap-b5p.pages.dev/artifacts/agent-index.json` | Daily entry point, at most 16 KB: market state in a few numbers, research candidates in a fixed order, the next seven days, every data-quality alert. |
| `https://market-recap-b5p.pages.dev/artifacts/agent-brief.json` | The detail behind it, at most 150 KB: risk budget, market, sectors, names, timing (7 days in full, 30 as one line each), review of the last session's reports, every candidate, the candidate ledger. |
| `https://market-recap-b5p.pages.dev/artifacts/<panel>.json` | The page's own artifacts (`overview`, `risk`, `monitor`, `catalysts`, `earnings`, `events`, ...). Every section of the brief names the one it came from. |
| `.../artifacts/financials/<TICKER>.json` | Ten fiscal years of annual statements from SEC XBRL company facts (31 line items, each with the filing it came from) and ratios. A general template: for banks, gross profit, EBIT, capex and FCF are empty by design, and bank-specific items are not extracted (see gaps). |
| `.../artifacts/valuation/<TICKER>.json` | Ten years of trailing P/E and P/TBV with the company's own percentiles, forty quarters of EPS (reported and operating), Yahoo's month-end forward P/E history. |
| `.../artifacts/events/<TICKER>.json` | The last eight reports (consensus, actual, surprise, price reaction, drift, guidance read from the earnings release where it is numeric), analyst revisions, the options-implied move and setup for the next report, recent filings. |
| `.../artifacts/tickers/<TICKER>.json` | Ten years of daily prices (OHLCV). |

`<TICKER>` is the Yahoo symbol (`BRK-B`). A file that does not exist answers
**404**, never the dashboard page.

## When it updates

Two editions each weekday, dispatched by a Cloudflare Worker: the **close
edition** at 16:20 New York, the **evening edition** at 18:35. Read the evening
one: the close edition leaves news to it. The index states its `edition` and
`as_of`. A missed dispatch is covered by a GitHub schedule later that night.

## How to read it

- `as_of` is the New York session the build describes. Each observation keeps
  its own date: a daily source can be a session behind (FRED's ICE spreads and
  real yield land a day late), and the page and feed say so rather than
  presenting it as the session's.
- Freshness is judged per source by its own publishing schedule (manifest
  `policy`: daily close 7 days, weekly release 16, monthly release 100, ...),
  dated by the period the value describes. `data_quality_alerts` lists every
  source that is stale, unknown or partial, and every validation finding.
- Nothing is recomputed for the feed; values are copied from the artifacts the
  same build published and validated.
- A research candidate is raised by a fixed rule (`agent_feed.RULES`) and
  carries a neutral question, never a verdict. Conditions are tracked against
  the previous published session: `new`, `continuing`, `resolved` only when a
  valid new reading shows it ended, `unknown` when this build had none.
  Events belong to the session; catalysts ahead are `scheduled`.
- The systematic anchor's exposure is a model's suggestion, not a position or
  a risk budget.
- The envelope is `market_recap.agent_feed.v1`, not `alternative-data`'s
  `investment_feed.v1`: both keep provenance, dates and quality per record,
  under their own field names.

## Known gaps

- **Bank KPIs**: net interest income, provisions, non-interest income and
  expense, deposits and loans are in SEC XBRL but not extracted yet; NIM and
  CET1 are not standard XBRL (they need the FR Y-9C) and are not available.
- **Segments and company KPIs** (Services revenue, cloud growth): not extracted.
- **Quarterly statements**: only EPS is quarterly; the rest is annual.
- **Narrative**: no MD&A, risk factors or call transcripts. Guidance given only
  on the call (Apple) is missing from `events`.
- **Reported actuals**: Nasdaq posts a company's EPS hours after the release; a
  report past its date without one is listed as not posted, never counted, and
  asked for again for a week.

## Asking for data

Open an issue in this repository with the **`data-request`** label (template:
*Data request*). Name the field, the companies, the period, and the research
question it serves; a request tied to a live question is done first. Errors in
published data use the same label with "wrong value" in the title, the URL and
the value seen.

Current priority: **US Financials (XLF)**, so bank fields come first.

## Never in the feed

Positions, theses, the research queue or decision log; API keys or tokens;
data whose terms do not allow republication (DRAMeXchange prices among them).
