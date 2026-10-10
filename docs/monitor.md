# MONITOR

MONITOR is a daily research queue over the configured S&P 500 basket plus
the watchlist's explicit non-members. It finds names that fell, keeps the
evidence on each side, and reports what changed since the previous build.
It has no score, no "mis-kill" label and no buy signal.

## What enters the queue

Either of two facts, both from exact exchange sessions:

- **Drawdown:** the adjusted close is at least `threshold_pct` (20) below
  its 1Y high. The page's threshold box re-derives this from the stored
  history without a rebuild.
- **Lagging peers:** the 1M return trails the median 1M return of the
  company's sector peers by `peer_excess_pp` (10 pp). Peers are the other
  index members in the sector, equally weighted, **the company excluded**. A
  cap-weighted sector ETF is mostly its largest members, so it is shown
  beside the peers as a benchmark, not used as the peer basket.

Entry is deliberately early: a name that is still falling is queued so it
can be understood, and the page alerts on substantive changes afterwards
(stabilisation, evidence turning) rather than waiting for a rebound.

Each queued name is labelled **company** (lagging its peers), **sector-wide**
(its sector is weak as a whole and the name is not lagging within it) or
**drawdown** (neither). A sector is weak as a whole when its ETF trails the market and its
median member trails the median of all members, both by `sector_event_pp`
(3 pp) over 1M: like against like, because when a few mega-caps carry the
index every equal-weight median trails it. The
SECTORS view shows breadth (share of members down, share past the
threshold) and internal repair (share above the 20-session average now
against five sessions ago). Sector-wide entries are listed once, under
their sector event.

## Price state × evidence state

**Price:** `stabilising` only when relative strength against peers improved
(the stock / peer-basket ratio rose over the latest 1M) **and** the close is
above its 20-session average; `weak` when either check fails; unknown
otherwise. Two complementary checks, not a pattern library. It is a state: the
session it turns is the weak → stabilising change, and a name that keeps
gaining on its peers stays stabilising. (Until 2026-10 the ratio also had to
have fallen over the 1M before, which sent a name back to `weak` the session
after it stabilised. The build after a rule change lists no price transitions
and says so in the notices, because the new rule re-labels names that did not
move.)

**Evidence** is listed for and against, never netted:

- FY1 consensus EPS change over 30 days (Yahoo earningsTrend). ≥ 2% down is
  against, ≥ 2% up or within ±2% is for. Down-revisers at least twice the
  up-revisers (and at least 3) is against.
- Revenue growth and free cash flow from the latest filing (VALUATION).
- The last reported quarter against consensus within 100 days (CATALYSTS).

`deteriorating` if anything is against; `steady` if nothing is against and
the FY1 estimate is live; `unknown` otherwise. A name with no estimate can
therefore never read as steady.

**Stale vs stable.** An estimate nobody revised in 30 days that did not move
is `stale`; fewer than `min_analysts` (3) is `thin`. Both are flagged and
neither counts as steady. Yahoo's trend stays on one fiscal period (after
Microsoft's FY26 report its FY27 "90 days ago" was an FY27 number, 19.37,
not FY26's 17.28), so the fiscal-year roll-over is not read as a revision.
The fiscal year end is shown with every figure.

The four boxes of price × evidence are filters, not a ranking.

## Candidate history

Each row keeps, across builds: the drawdown history; `first_seen` (date,
reasons, and whether it was a baseline already present when tracking
began); a `state_log` that gains a line only when queue membership, price
state or evidence state changes (an unknown day keeps the last known state,
so a data gap is never a transition); and the last reported quarter. The
outcome since first seen (adjusted return, and the peers' median over the
same dates) is recomputed each build.

Manual decisions live in `config/monitor_notes.toml`: `watch` (its price and
evidence changes are listed under TODAY even outside the queue) or
`exclude` (hidden from TODAY and QUEUE, kept under ALL with the reason),
with the date, the reason and later the outcome. Versioned with the repo so
they survive devices and caches. The browser FOLLOW list remains a quick,
browser-local shortlist; followed names' transitions also appear in TODAY.

## TODAY

The default view: sector events, then names that entered, stabilised, had
evidence turn against them, reported, failed to stabilise, or left the
queue since the previous build, each with the reason in words. The first
build is a baseline and lists no changes.

## Measurement contract

- The high is the maximum split- and dividend-adjusted close across the
  latest 252 exchange sessions, including the current close. This is an
  adjusted-close drawdown, not an intraday-high drawdown.
- Missing sessions are not compressed or forward-filled. An incomplete
  lookback or missing current close leaves drawdown unknown. Shorter-window
  checks can still be available for the same company.
- Relative performance compares the company's 1M return with the market
  proxy, its sector ETF and its peer median, in percentage points. It is not
  a fitted factor-model residual.
- Relative-strength improvement means the latest 1M stock/peer-basket ratio
  return is positive after a nonpositive preceding 1M ratio return.
- Above-MA is a level check against the configured 20-session average, not
  a claim that a breakout just happened.
- Valuation and financial readings reuse the same-session VALUATION output;
  earnings reuse the same-session CATALYSTS output. Optional data unavailable
  on this build stay unknown. The financial period and filing date remain
  visible. A vendor earnings date is not company-confirmed.
- Missing estimates do not mean unchanged forecasts. Yes/No labels describe
  individual facts; neither Yes nor a greater count of Yes answers implies a
  better investment.

All windows, thresholds and the index live in config/dashboard.toml. Windows
such as 1M and 1Y resolve through the shared PERIOD_TRADING_DAYS definitions.

## Observations and persistence

The monitor artifact retains daily observed drawdowns for all scanned names,
so the reader can adjust the threshold without rewriting historical data.
Tracking begins with the first monitor build. Baseline candidates are labelled
as first observed, not newly crossing a threshold. No historical membership
or historical financial knowledge is inferred from today's universe.
Missing observations do not assert an exit. Rerunning a session replaces that
session's observation; older builds cannot overwrite a newer ledger.

Local builds continue artifacts/monitor.json. The cloud refresh sets
MONITOR_PUBLISHED_STATE=1 and reads the configured published site's manifest
and monitor artifact. A manifest from before MONITOR existed permits the
initial baseline; a missing, corrupt, inconsistent or unreadable ledger after
introduction fails the build. It must never silently start over. The workflow
archives the monitor artifact for 90 days, in addition to its published copy.
Failed/unpublished cloud builds do not advance the published history.

Removed index members remain identifiable in the ledger with unavailable
current readings. They are not silently represented as current constituents.
The Follow list is independent of automatic qualification and is saved only
in the current browser/site origin. It survives a rebound above the threshold;
export/import provides an explicit backup and transfer mechanism. Clearing
browser storage clears follows unless the reader has exported a backup.

## Reading the page

Use TODAY for what changed, QUEUE (with the 2×2 filter) for the current
candidates, SECTORS for breadth and repair, and FOLLOWING for manually
selected names. Search and sector controls narrow the
view without changing the entry rule. Details expose dates, benchmarks,
missing-data explanations and links to the existing company panels.

The first live session has no prior monitor observation to compare against.
This is expected, not an empty-alert failure. Observation history is prospective
and based on the universe present on each build; it is not a survivorship-free
historical backtest or a claim about predictive performance.

## Not in v1

Russell 3000 coverage, options, point-in-time estimate history before the
first build, and any measurement of whether the queue predicts returns.
Those wait for enough prospective history to observe.
