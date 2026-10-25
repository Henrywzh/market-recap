# market-recap

Live: **https://market-recap-b5p.pages.dev**

A post-market recap dashboard for the US equity market, built entirely on
free, attributable data sources and published as a static site.

There is no API key and no paid data feed. A Python build step fetches the
day's sources, writes JSON artifacts, and a static page renders them. The one
piece of server code is the live strip's quote function (below); everything
else is the static build.

## What it shows

The views are grouped by the question they answer
(`docs/information_architecture.md`; the grouping itself is `web/js/routes.js`):

| Group | Views |
|---|---|
| **MARKET** | **Today** (the default view, `#overview`) · Indices · Heat maps · Europe (FTSE 100 and 250, STOXX Europe 600, EURO STOXX 50, DAX, CAC 40, AEX, IBEX 35, FTSE MIB, SMI; the iShares STOXX Europe 600 supersector funds) |
| **SECTORS** | **Sectors**: one hub, market → the 11 GICS sectors → their sub-industries → their names, every sector and sub-industry page opens on its charts (the basket against the S&P 500 over a switchable window, sub-industry bars, the VALUATION section (the same one THEMES, TICKER, K-SHAPE and SIZE & STYLE draw: trailing P/E against its own ten years, forward P/E, growth expected, revenue growth and operating margin, each beside the S&P 500's or the parent sector's; revenue growth and margins by fiscal year; the P/E premium against its own history and what moved the ratio), the valuation path, a sub-industry map and a names chart), with the tables, reports ahead and the industry data of the THEMES group mapped to it folded beneath; the rotation graph, industry scorecard and index/sector P/E sit under the sector table · **Themes** · **Relative value**, one menu entry with a switch between **K-shape** and **Size & style** (cap against equal weight, large against small, value against growth (IWD/IWF and Fama-French HML), staples and low volatility against the market) · **AI chain** (the AI supply chain's companies, links and report dates) |
| **RISK** | **Risk** · Rates & macro · **Priced path** · Positioning |
| **NAMES** | Monitor · **Ticker** · Screener (every company's multiples in one table) · Europe names (FTSE 100 and EURO STOXX 50 members, luxury, UK financials) · Cross-listing |
| **CALENDAR** | Calendar · Earnings · Scenarios (what past data releases did to rates and stocks) |
| **TOOLS** | Technicals · Move Check · Trade Desk · ETF X-Ray · DCF |

The screener keeps its old hash, `#valuation` (and `#valuation/MSFT`, which filters the table to that name). `#rotation` opens SECTORS.

**UI trial (2026-10-14).** SECTORS now defaults to **Rotation & sectors**,
rotation first, then the sectors' valuation and earnings growth against the
S&P 500 (the table, each group's P/E against its own ten years, the valuation
path and what you would need to believe); **Industries** holds the industry
scorecard and links groups to their combined sector/sub-industry pages.
INDICES opens with a comparison row per index (drawdown from the high,
advance/decline), then one selectable recap universe (contract order, SPX
first), not two repeated sections. Its common market-state history is folded and
shows absolute means/probabilities alongside differences and uncertainty.
RSP/SPY and IWM/SPY state thresholds are price-ratio changes in **%**, not
arithmetic return gaps in pp; no numeric signal or threshold changed.
The overnight/intraday decomposition described below now lives in a lazy
research fold on **Trade Desk → Overnight**, not INDICES. EUROPE opens on
equal-size performance tiles with period, currency and relative-return
switches; exact tables/history are folded. P/C smoothing and date-range
controls are separate; range statistics use only the selected dates.
MONITOR accepts a same-date cached artifact after a partial build, labels
that reuse, and rejects a stale date or an explicit builder failure.

Local preview helpers use existing cache only and preserve artifact/session
dates: `scripts/preview_index_put_call.py`, `scripts/preview_market_state.py`
and `scripts/preview_overnight.py`; then `make site`. They do not perform a
full refresh or make a mixed-date local preview current. The buyback curve
is not a point-in-time history or observed flow; the exploratory cached-data
audit and its limitations are documented in `docs/blackout_audit.md`.

The trial UI is dark-only. The theme selector and light palette are removed;
old `mr-theme` preferences are retired without clearing monitor/watchlist data.

**Reverse DCF trial (2026-10-20).** TOOLS → DCF opens a conditional operating
scenario map, using the full valuation universe and existing annual statements;
BUILD YOUR OWN retains the manual forward model. Growth × sustainable operating
margin cells compare model EV with an editable published EV proxy, not share-price
upside. WACC, net reinvestment, tax and terminal assumptions remain explicit user
scenarios, never calibrated forecasts. Unsupported business types and missing
critical facts show a reason instead of invented inputs. Historical input sessions
retain their dates. See [the model contract](docs/reverse_dcf.md).
Assumption-source labels and company annual-history references now accompany
the controls. Three chart sections show history against a separate hypothetical
path, growth / required-margin curves under WACC scenarios, and EV sensitivity
to discount / reinvestment choices; terminal dependence and numeric source folds
remain explicit. These add context, not calibrated forecasts or probability bands.
Required margins are colored relative to the company's recent reported range;
the same section shows dated Yahoo FY revenue estimates and dated GICS-industry
actual margins where peer coverage is adequate. These are context references,
not an automatic cheap/expensive call or long-term forecast.
The default reading order is now **company history → price requirements →
sensitivity**. History and the required-margin frontier are expanded initially;
the assumption editor, sensitivity chart and EV audit details remain folded.
Headline requirements remain conditional scenarios; see
[the evidence definitions and limitations](docs/reverse_dcf.md).
The headline leads with **required operating margin** beside the selected
scenario margin. The implied enterprise discount rate and Treasury comparison
remain in audit details, not as an equity-return estimate. One bar sets the
required margin against the company's own range and its peers. Growth opens on
analysts' FY revenue growth (else the reported CAGR), labelled and editable.
The frontier shades **reference ranges** (near-term analyst growth low–high ×
historical margin range), not jointly validated long-term outcomes.
FY revenue consensus now uses low–high bands and mean dots on a shared growth
scale across fiscal years, with a zero-growth reference and analyst counts.
Missing / inconsistent bands are withheld, never imputed. Dispersion is not a
confidence interval. This is presentation only, not a prediction-model change.

**Valuation evidence trial (2026-10-24).** SCREENER and TICKER → VALUATION add
an A/B same-basis multiple comparison, with separate growth, capital-return,
cash-conversion and leverage context. Missing, future-dated, different-period or
non-comparable inputs withhold directional labels. GICS/size peer suggestions
are not validated business-model matches. Multiples' within-sector rank colors
are descriptive blue/amber; historical P/E is folded below business history to
reduce anchoring. No fair multiple, goodwill value or buy/sell score is estimated;
no financial model formulas change. See [the comparison contract](docs/valuation_comparison.md).
Forward P/E is the default comparison measure; operating/adjusted trailing P/E,
reported trailing P/E and book multiples remain explicit alternatives. The
selected measure explains its earnings base, including banks' ex-gains basis;
different adjusted earnings bases do not receive directional evidence labels.

**CPI view (2026-10-15).** RATES & MACRO opens on **Treasury rates**, with
**CPI & macro** and **PPI · AI prices** as the other views. The latest official BLS headline/core
MoM SA and YoY NSA prints sit against retrospective calendar consensus,
followed by official food/energy/core contributions, a 6M/1Y/2Y component
heatmap (raw MoM or prior-only percentile), weights and historical reference
bands, and core 3M/6M annualized, sticky, median and trimmed-mean measures.
Each heatmap row now keeps an always-visible weight percentage and blue
0–100% bar, independently of inflation colors. The existing PCE and commodities remain below. Each source keeps its own date;
missing or delayed measures remain gaps/pending. No research prediction model
or release-window live service is included. See [the CPI contract](docs/cpi.md).

The adjacent **PPI · AI prices** view adds official headline/core release
prints against retrospective consensus, five separately dated AI-related
industry PPI histories matching alternative-data's observation targets
(semis/electronic components, communications equipment, switchgear,
electronic computers, storage), and final-demand group weights/change detail.
The industry series are broad **NSA** price indexes, not an AI-only demand
index. No custom weighted proxy, headline industry weights, forecasts or
inferred contributions are manufactured. FRED lag stays pending with the last
actual month. See [the PPI contract](docs/ppi.md); `scripts/preview_ppi.py`
refreshes only this local section without moving other artifact dates.

PPI also shows four **SA** final-demand groups' 3M/6M compounded annualized
momentum, independently dated from the release and the NSA industries. CPI
and PPI retain an observed-release ledger inside `macro.json`: changed parsed
BLS/calendar values append a version, never replace an earlier one. This starts
with what this build actually observed, not reconstructed first prints or
pre-release consensus. Prior-month revisions are compared only with an earlier
observation captured before the new publication. Normal CI restores the published
ledger (and refuses to reset it on restore failure); the existing run archive
also saves `macro.json`. No new schedule or prediction model is introduced.

MARKET STATE shows only active conditions in a compact ACTIVE / CAUTION grid,
with bold names, each artifact's exact rule visible, and a shared term glossary;
clicking a condition opens the full seven-state historical comparison and
scrolls it into view, and clicking again closes it.
Inactive conditions and detailed outcome explanations remain folded. CAUTION is
a muted red accent, not a forecast. It requires an adverse outcome's
finite 95% interval to exclude zero; it is not a forecast, independent vote,
or multiple-testing-adjusted signal. Rebound and drawdown can both be stronger.
BUYBACK BLACKOUT shows the estimated blackout share as of its own date, the
default window's calendar-day change, the next scheduled change and the peak
ahead; projected dates stay dashed and separate. The artifact's momentum keeps
the velocity and acceleration for analysis, not as page charts.
`scripts/preview_blackout.py` rebuilds those momentum fields from the existing
local artifact only; research limits remain in `docs/blackout_audit.md`.

**Today** (`#overview`, the landing page; `today.json` from the `today` panel) is what
matters for the next session, not the market's levels (those are on INDICES and HEAT MAPS).
Under the live strip: JUST OUT (the last session's releases with their prints, and who
reported, with the EPS against consensus and the move); COMING UP (the next three NYSE
sessions in full -- high and medium macro releases, the Fed, auctions, options expiries,
earnings above `[today] earnings_min_weight` of the S&P 500 or on the watchlist with the
options-implied move where the build has one, and the themes' data due -- then high
importance only for two weeks); and UNUSUAL NOW: MOVES (names beyond their own volatility:
during the session computed live from the heat-map and sector-fund quotes and each name's
sigma and betas in `moves.json`, marked LIVE · PROVISIONAL; otherwise the build's close),
STATES (market states that started or ended, RISK matrix cells that changed state, an index
put/call at an extreme of its own history -- descriptions, not warnings, until a channel is
validated) and EVENTS (names new to the MONITOR queue, recent
catalyst-log entries, earnings reactions beyond two of the name's own sigma), OVERSOLD (indices and
sector funds in `[today.oversold_watch]` whose RSI(6) closed below 30 or 20, with the run of
closes; a description, not a rebound call -- quantamental-lab `docs/rsi6_below20_v1.md`); long-running
states share one "Ongoing" line. TESTED marks an item backed by a research table in the build.
Each build keeps a compact history of what TODAY listed (read back from the published copy),
so what it flagged can be checked later. The same lists are the MCP tool `today`. OVERVIEW's
cards that existed nowhere else (breadth with new highs and lows, what moved the S&P 500,
SPY/QQQ/IWM/RSP performance, bond against equity volatility) are on INDICES under SESSION.

**Ticker** (`#ticker/AAPL`) is one company on one page, reached from any
ticker link. A summary strip says each thing once: the close against a year
ago and its high, the month against its sector peers, the valuation against
its own ten years (P/E; P/TBV with ROTCE for a bank), the 90-day revision to
next year's EPS, the next report with its implied move, and MONITOR's state,
with short neutral tags where a pattern is plain. Under it, four sub-tabs, each
built when first opened and kept in the hash (`#ticker/NVDA/VALUATION`; REPORTS
is the default and left out, and the old RECENT and REPORT links open it). REPORTS: what's new --
the REPORT CARD of a report traded in the last ten sessions (`reported_sessions`): EPS and revenue against the consensus and the analysts' low–high range recorded before it (Yahoo's reported figures when Nasdaq has not posted), the guide the release gave against the street's number for that period, the estimates since, the move against the straddle and the drift after it; the evidence for and against (MONITOR's,
plus insider buying from Form 4, short interest and rating changes for focus
names), recent 8-Ks and the industry data since the last report -- then the next
report: the event card, a timeline of its own events and what is ahead
(peers' reports, macro dates, its themes' data releases, announced and
hand-kept company events), the last eight reports and the estimate
revisions folded, and the options' implied move and term structure. PRICE:
price and trend, WHAT MOVED IT and its AI-chain links. VALUATION: the VALUATION block (the same section as on every page: what the company pays and expects against its sector, its business by fiscal year, and its trailing P/E against its own ten years, with an operating / reported switch and the other basis dashed), then EARNINGS & FORWARD P/E (TTM EPS by filing date with its year-over-year growth as bars, Yahoo's own forward P/E history, and the P/E statistics table and method folded -- drawn from the same build as the SCREENER), and valuation against the
sector median (a bank against its sub-industry, on bank measures). WHAT
MOVED IT on PRICE is every report and large move with what happened that session,
headlines included. FINANCIALS: FUNDAMENTAL TRENDS, six charts (revenue and growth, gross / operating / net margins, net income and EPS, free cash flow and its margin, ROE and ROIC, cash against debt) by year, quarter or trailing four quarters, with tooltips in step. Quarters come from the 10-Qs; a fourth quarter is the year less nine months, a cash-flow quarter one year-to-date figure less the one before (same tag on both sides), and each says so; a quarter's revenue far off the scale of the quarters around it is left blank. Then the filed statements. Each section is drawn by
the panel that owns it, so nothing is computed twice. Views that take a
ticker read it after a slash (`#dcf/MSFT`, `#technicals/NVDA`); hashes from
before the regrouping (`#financials`, `#fixed-income`, `#macro`, `?ticker=`)
still land on the right view.

**Trade Desk** (`#trade/SPY`) is for US stocks and index ETFs held overnight
to weeks. SETUPS & SIZE: a price chart on traded (split-adjusted, not
dividend-adjusted) closes with the 20/50/200-day averages and the prior
20-session and 52-week closing extremes; a price ladder of every level above
and below the close; ATR, 20-day dollar volume, the latest opening gap and,
with a same-session option snapshot, the ATM-straddle range; and a sizing
calculator capped by stop risk, position size and a share of dollar volume
(the spread is an assumption you enter). TRADE PLAN: your entry, stop, target, horizon
and costs give each outcome after costs (target, stop, and the horizon ending
with neither hit, kept separate), reward to risk, the success rate needed to
break even, the expected value from weights you enter, and a grid of where it
turns negative; nothing is filled in from history. The plan and a later review
(fills, whether the plan was followed, the result in R, judgement and execution
kept apart) download as JSON or copy as Markdown; nothing is sent anywhere.
Charts: the plan on the year's volume by price (loss and gain zones shaded) and
the three outcomes in R. JOURNAL reads several review files at once in the
browser: the running total in R, R per trade, and mean R by whether the plan
was followed and whether the thesis held. OVERNIGHT: ES/NQ, Asia and Europe,
and pre/post-market prints for the top 30 S&P 500 weights plus the
watchlist, polled only while that tab is visible. SCORECARD: forward returns
after the anchor's states (daily since 1993), Fear & Greed extremes and the
trend proxy, against any day -- descriptive and in-sample. Buyback blackout
and insider buying are on RISK → POSITIONING. Index-specific put/call volume
ratios are also there: SPX + SPXW reuse RISK's Cboe daily cache, separately
from Fear & Greed's Total P/C. NDX is an authorized-import adapter, disabled
until public display permission is recorded; it is never replaced by QQQ, and
while disabled it appears only as one dim line in the method fold. The page
computes the latest value, median and percentile for the selected range.
The source contract and missing-session rules are in `docs/index_put_call.md`.

The panels, as each is built:

| Tab | Contents |
|---|---|
| **MONITOR** | Research queue over the S&P 500 and the watchlist. A name enters at a 20% drawdown from its 1Y high or when it trails its sector peers (company excluded) by 10 pp over 1M. **TODAY** lists what changed since the previous build (entered, stabilising, evidence turned, reported, left), with weak-as-a-whole sectors grouped as one event; **QUEUE** has a price-state × evidence-state 2×2; evidence for and against (FY1 EPS revisions from Yahoo, revenue, FCF, last quarter vs consensus) is listed, never scored; candidate history persists between builds, and watch/exclude reasons live in `config/monitor_notes.toml`. See [the monitor contract](docs/monitor.md). Financials rows also carry P/TBV against the company's own ten years (ROTCE beside it in the detail); elsewhere tangible book is not what a company earns on, so it is left out. |
| **SECTORS → SECTORS** (`sectors.json`) | The hub: the 11 GICS sectors, their sub-industries (as the SPY holdings file names them) and the S&P 500 members, built from this session's HEAT MAPS, INDUSTRIES, ROTATION, VALUATION, MONITOR and THEMES (nothing fetched). Each sector and sub-industry: returns over 1D to 1Y cap-weighted from members' published weights and against the S&P 500, the fund's own return, the rotation quadrant, the share above the 200-day average, median drawdown, FY1 EPS revisions, the aggregate forward P/E and the trailing P/E's percentile against its own ten years (P/TBV for Financials); the hub's first page sets the 11 sectors side by side against the S&P 500 on forward P/E, P/E percentile, consensus EPS growth this and next fiscal year, TTM revenue growth and 90-day revisions, sortable by any column; the VALUATION section beneath the page's top strip, the valuation path, INDUSTRIES' evidence flags, best and worst names; each page's history (`artifacts/sectors/<KEY>.json`: the basket against the S&P 500 and rebased, the weekly P/E with its ten-year band, and its `outlook`: forward P/E and growth; its `history`: revenue growth and gross and operating margin by fiscal year) is what its charts draw (the fund is no longer charted); its members with returns, distance from the high, revisions, multiples, next report and MONITOR state; and, where `[sectors]` maps one, that THEMES group's cards. Keys are the SPDR fund (`#sectors/XLP`) and fund-initials for a sub-industry (`#sectors/XLP-SDNB`) |
| **SECTORS → INDUSTRIES** | Every sub-industry (three names or more) and sector as the **median member**, so a few large names do not speak for it: 1M / 3M / 6M return, the share of names down over the month, drawdown from the one-year high, the share above the 200-session average, the FY1 EPS revision over 30 and 90 days (from MONITOR; read only for names with positive EPS), and the forward P/E with its percentile against the company's own ten years (from VALUATION; not shown for REITs, whose multiple is not P/E). Tags are evidence, not a verdict -- SOLD OFF, EST CUT / EST HELD, P/E LOW -- and appear only where a reading crosses a threshold in `[industries]` of `config/dashboard.toml`; a sub-industry of fewer than five names is thin and is left off this table (its page is under SECTORS). A group opens to its names. It runs after MONITOR in the build and names an input that did not build rather than borrow another session's. See [how to tell an oversold group from a deserved fall](docs/sectors/selloff-screen.md) |
| **MARKETS** | A **live strip** and **intraday index charts** (see below), then the recap: **MARKET STATE** (`market_state.json`: the equal-weight and small-cap funds against the market over 3M, the share of the 11 sector funds above their 200- and 50-day lines, the distance from the one-year high and the VIX, each with a year of history, and for seven named rules (narrow leadership, few sectors above the 200-day line, VIX above 25 ...) whether it holds today, its days and separate episodes since 2009, and what the market did over the next 3M against the other days -- return, worst fall, chance of a 5%+ fall -- with a 95% range from a moving-block bootstrap; a range through zero is marked not detected. Fund prices only, no survivorship; see docs/todo.md item 11), **OVERNIGHT VS INTRADAY** (drawn on TOOLS → TRADE DESK, in the closed "Historical research" fold; `overnight.json`: SPY, QQQ and IWM since inception, each session split into the move from the previous close to the open and from the open to the close -- the growth of each leg held alone, each leg's return by window and calendar year, the last ten sessions; the dividend sits in the overnight leg; a description of where the return was made, not a strategy, since the twice-daily trading costs are not counted), a **comparison** row per index (drawdown from the high with sessions since it, advance/decline), a price + net-breadth + movers block for **each index**, a **watchlist** of names no index holds, sector performance / weight / **contribution**, sectors rebased to 100, % of each sector above its moving averages, SMA200 slope by sector |
| **CALENDAR → CALENDAR** | Things to watch, in two lanes. **Macro & broad index**: BLS, BEA and Census releases at the time each agency publishes, FOMC decisions / press conferences / minutes and Board speeches from the Fed's calendar, announced Treasury coupon auctions, rule-based events (monthly options expiry, and quad witching as the largest expiry with index futures; each with its SPX settlement rule, since SPX AM settles on the opening prints; S&P rebalance; VIX expiry; jobless claims; ISM; EIA crude inventories), an expiry within three sessions of a SPY or QQQ move beyond two of its own recent sigmas flagged AFTER A LARGE MOVE (`expiry_*` in `[catalysts]`, descriptive, not a signal), market structure (month and quarter end, MSCI quarterly reviews, the Nasdaq-100 annual reconstitution, market holidays and 1:00 p.m. closes), federal tax payment dates, the Fed's loan-officer surveys, and hand-kept events from the config (`[[catalysts.manual]]`), each with a `certainty` (official_schedule, announced, expected, deadline, projection), its source and the day it was last `checked`: central-bank decisions abroad (ECB, BoJ, BoE, BoC, SNB), the Russell reconstitution, Treasury's refunding, OPEC+, summits, elections, and deadlines that can move (government funding, tariff dates, the US-China truce, the debt-limit projection), which are listed `deadline_horizon_days` ahead. Census is read from its default calendar and this year's own page, since the default moves to next year's schedule in the autumn. Every event carries a **category** (macro data, monetary policy, fiscal & Treasury, market structure, politics & policy, geopolitics, commodities & industry, corporate) and **channels** (the RISK matrix rows it hits: equities, treasuries, credit, volatility, cross-asset, macro), from its type unless its config entry sets its own, with a filter for each; a RISK cell's drill-down lists the next events for its row. **Importance** says how it was set: a release SCENARIOS measures (`measure`) is high when its release days move the 2-year yield or SPY (scaled by its own volatility) at least 1.4x an ordinary day's, medium from 1.15x, low below (`importance_ratio`; CPI 1.54x, payrolls 1.69x and FOMC 1.59x high, PCE, PPI and claims low); earnings by index weight; anything else by hand, and the row says which. A measured release also shows what it has done (SCENARIOS): its release days' average 2-year yield and SPY move against other days, the move per standard deviation of surprise, and, when rates are driving stocks as now, the stock response in such markets; an effect under |t| 2 is named as not detectable rather than given a number. Earnings rows add the name's average move over its last eight reports and, for names in the options snapshot, the implied move (ATM straddle to the first expiry after the report, which prices the whole period, not the report alone) — each with the previous print from FRED and the period it covers. **Single name**: earnings of every S&P 500 / Nasdaq-100 member and watchlist name with before-open / after-close timing, consensus EPS, estimates and index weight. An earnings report's importance is the company's weight in the S&P 500 or Nasdaq-100, or, if higher, its share of the market cap of its THEMES group's bellwethers (`earnings_theme_*` in `[catalysts]`: TSM is in no index and is the second-largest semiconductor company). A **last session** block shows what was released and who reported, with EPS vs. consensus and the day's move. Beneath it, **unscheduled catalysts** (`catalyst_log.json`): a hand-kept log in `[catalyst_log]` of dated events no calendar announces (a leak, a competitor's announcement, a supply report), each with its source and the names the coverage tied to it; for each, the names' price since the close before the event, how far consensus EPS and revenue have moved since the nightly snapshot at that close (this quarter, this year, next year), the analysts' 7- and 30-day up and down counts, and a sentence for the pair (prices down and estimates flat, estimates cut, and so on). The exposed lists are judgments, the estimates are Yahoo's averages and lag analysts by days to weeks, and the snapshots begin 2026-10-01: an event before that has prices only Times in New York and the reader's own zone; every event says how its date is known. Under the three-week strip, the share of S&P 500 weight reporting each session, by GICS sector (`heatmap` in `catalysts.json`) | High-importance releases (FOMC, CPI, payrolls, GDP) are listed 45 days out. After a release the last-session block shows the actual against the survey point (TradingView).
| **CALENDAR → EARNINGS** | S&P 500 earnings in three blocks. **FactSet Earnings Insight** figures read from its articles (growth, beat rates, forward P/E vs its 10-year average, the quarter's and year's EPS revision against FactSet's typical one; history from 2014). A **daily bottom-up revision tracker** built from every member's consensus trend (current quarter, this year and next, 7–90 days, by sector, with the names that moved it). The **reporting season** from Nasdaq's calendar: reported, beat rate, surprise, growth against year-ago EPS captured before each report; a company past its report date whose actual Nasdaq has not posted yet is listed as not posted, never counted, and asked for again on each build for a week |
| **SECTORS → THEMES** | Nine groups of names that trade together (cloud & AI capex, semiconductors & memory, energy, banks, consumer, housing, cruise lines, defense primes, consumer staples), each with a proxy (an ETF, or an equal-weight basket) and its run-in against the S&P 500, its bellwethers' next reports (scheduled, or projected from their own rhythm) with how far the proxy moved on their past reports, and a six-week calendar of those reports, the macro releases that bear on it and its own data's due dates. The page opens on a theme's OVERVIEW; VALUATION and DATA are sub-tabs, and DATA shows one group of industry-data cards at a time, picked by a chip (CLOUD: spending, suppliers, Ramp; SEMIS: Taiwan & Korea, memory prices, AI usage; plus release days; `#themes/SEMIS.DATA.AI-USAGE`, and a link to one card opens the chip that holds it). CLOUD adds hyperscaler capex from 10-Q/10-K XBRL, three Taiwanese AI-server makers' monthly revenue and the Ramp AI Index; SEMIS adds TSMC and Nanya monthly revenue, OpenRouter tokens and estimated revenue by model author (authors drawn by default: OpenAI, Anthropic, DeepSeek, Google; the rest on the legend; log or raw scale, 1M to 1Y ranges, a 7-day average or a monthly annualised run-rate of OpenRouter-routed revenue), Korean IC exports and the memory, DRAM and flash lines inside them, BLS semiconductor producer and import price indexes, ADATA's monthly memory note and UK retail memory/CPU prices read from PCPartPicker's trend charts. SEMIS also adds Ramp Tokenomics (weekly token volume and spend by model maker or model, shares of the reported sample, observed effective token prices for OpenAI and Anthropic; a MONTHLY ARR mode spreads each week over its seven days and annualises a month's mean day (a run-rate of the Ramp sample, hollow markers for partial months); Ramp's Token Spend Management sample, not Ramp's total AI spend nor any provider's revenue or ARR). ENERGY adds EIA's weekly crude, gasoline, distillate and gas inventories against the same week of the last five years, refinery utilization and production, WTI/Brent/Henry Hub, the 3-2-1 crack and the pump price; HOUSING adds the 30-year mortgage rate, starts, permits, new home sales, months' supply and Case-Shiller; BANKS adds H.8 loans and deposits, the 2s10s and 3m10y curve, the high-yield spread, call-report delinquency rates and the loan officer survey; CONSUMER adds retail sales, real spending and the saving rate, consumer credit, Michigan sentiment and jobless claims (all from FRED, each dated by when its publisher releases it). Each group with at least two bellwethers that have filings has the VALUATION section, its bellwethers' cap-weighted P/E, forward P/E, growth and margins set against the S&P 500; a line under it names the bellwethers it is built from and any left out, and a group with too few says why. CRUISE (an equal-weight basket of CCL, RCL, NCLH) and DEFENSE (an equal-weight basket of LMT, RTX, NOC, GD, LHX, HII) have the status board, run-in, report calendar and macro dates but no data blocks of their own yet. STAPLES (XLP; WMT, COST, PG, KO, PM, PEP) has the same, and what moves its names is the 10-year yield, the dollar (UUP), VIX and sugar futures (SB=F), each name's correlation and beta with them over the last year, and a KO vs PEP card (a theme's `pairs`: the ratio of the two names' closes, each one's return by window and the gap, their daily correlation). A RELEASE DAYS card for each of the four shows how its ETF moved beyond the S&P 500 on the session of each past release of the series that bear on it (payrolls, core CPI, retail sales, claims, starts, new home sales, EIA crude stocks): the size of the move against any other day, and how often it rose after a print above or below the published forecast (TradingView's economic calendar, back to 2016), or its own trend where no forecast covers most releases. Each of the four also shows what moves the names: each bellwether's correlation and beta with oil, gas and the crack, the 10-year yield, the curve, the high-yield spread or gasoline futures, over the last year, and its series feed the stock cards' since-the-last-report table |
| **EUROPE** (`europe.json`) | **Indices**: ten European indices in local currency and in dollars (the local return compounded with the currency's move against the dollar), 52-week drawdown, 50- and 200-day lines, the indices in dollars beside SPY over three years, GBP/EUR/CHF against the dollar, and the 19 iShares STOXX Europe 600 supersector funds against the STOXX 600 fund (the Europe analogue of the SPDR sector funds). **Names**: the FTSE 100 and EURO STOXX 50 members (Wikipedia's current tables; London symbols get `.L`), a luxury group (Hermes, LVMH, Richemont, Ferrari, Cucinelli, Moncler, Kering, Burberry, Swatch) and the FTSE 100's financials, each with price, returns on the name's own trading days, distance from the 52-week high, Yahoo's own forward and trailing P/E, consensus EPS growth this fiscal year (not meaningful past ±200%), and a sector summary; sortable. Prices from Yahoo (a London price is in pence). There is no European filing history here: ESEF filings are annual only, from 2021, and not for Germany or Switzerland, so multiples have no past; the `snapshots` job (`europe`) records Yahoo's multiples and consensus each evening so that a history exists from the day it started (`europe/YYYY/YYYY-MM-DD.csv.gz` on the snapshots branch) |
| **SECTORS → K-SHAPE** (`kshape.json`) | A high-income leg against a low-income leg, within an industry (cruise: Viking against the mass-market lines; airlines: Delta and United against Southwest; homebuilders: Toll against D.R. Horton and Lennar; casinos; cards and lending), and all pairs together. The legs are named by hand in `[kshape]` of `config/dashboard.toml`; the squeezed middle is left out. For each pair: the ratio of the legs' equal-weight price indexes with where today's ratio sits among its own weeks (=1 at the window's start); the valuation block (below); and a table of names with forward P/E (the valuation tab's, or the same blend from consensus for a name outside it), where its trailing P/E sits in its own ten years, consensus EPS growth this fiscal year and revenue growth. A name with no filings history (Viking, listed 2024) has prices and a consensus multiple only. Shows the divergence and what has been paid for it; no leg is called right. The valuation block sets each leg's pay and expectations beside the other's, its business by fiscal year, and splits the leg ratio into a ratio of multiples and a ratio of earnings, each leg being an equal-weight basket of its names' P/E and earnings; a name with no filings history is listed as left out. A closed DETAIL fold holds each leg's price index and returns, each leg's median trailing P/E (from VALUATION's filings-based history, only weeks where at least half the names had a meaningful one) and the ratio, and the median year-on-year growth of trailing EPS. Needs this session's VALUATION for the P/E and EPS history; without it, prices only |
| **SECTORS → SIZE & STYLE** (`sizek.json`) | The large, cap-weighted arm against the equal-weight or smaller arm of much the same market: S&P 500 SPY against RSP, Nasdaq-100 QQQ against QQEW, S&P 500 against the Russell 2000 and the S&P MidCap 400, FTSE 100 against FTSE 250 (price indexes, pounds). Pairs are named in `[sizek]` of `config/dashboard.toml`. For each: the price ratio since both traded (=1 at the window's start) with where today's ratio sits among its own weeks and its distance from its high and low, then the valuation block (what each arm pays and expects, its business by fiscal year, its P/E against its own history and what moved the ratio); in a closed DETAIL fold, each arm's path, the rolling one-year return gap with how often and how long the large arm led, returns by window and by calendar year. Adjusted closes for the funds. Where a pair names a basket for each arm, the arms are also measured on earnings: each is rebuilt from its names' SEC filings and closes, as the VALUATION tab builds an index (S&P 500 and Nasdaq-100 members, cap-weighted or equal weight; S&P 500 members of a sector; or a fund's own holding weights, looked through to the names, with the share of the fund that has a filings history shown), so the gap splits into a ratio of P/E and a ratio of earnings, and the cards say which arm led and whether the multiple or the earnings did more of it. Pairs outside the filings universe (small and mid caps, the UK, Fama-French portfolios) are prices only, and say why. It also carries style pairs: value against growth (IWD/IWF), consumer staples against the market (XLP/SPY) and low volatility against the market (USMV/SPY), and Kenneth French's value factor (HML: the cheapest 30% of US stocks by book-to-market against the dearest 30%) and its large-company half, from his data library's daily 2x3 portfolios (monthly, about a month behind) |
| **CALENDAR → SCENARIOS** (`scenarios.json`) | What each data release has done to rates and stocks, measured over its past releases with the count shown, never forecast. For each configured line (core CPI, CPI, PPI, core PCE, payrolls, unemployment, hourly earnings, claims, JOLTs, retail sales, ISM manufacturing): releases above / in line with / below TradingView's forecast (a miss of more than 0.7 robust standard deviations of its own surprises, or any miss for a line published to one decimal), the 2-year and 10-year yield, SPY, IWM and KRE and sector moves on those days with standard errors, the response per standard deviation by era and when rates drive the market, and whether the sector ordering found before 2022 held after it (a permutation test: the sectors are not independent samples). Beside them: the 60-session correlation of SPY with the 10-year yield's change (negative: rates drive stocks), FOMC days against other days, the next release with its forecast, each line's release-day size (2-year yield and SPY in its own volatility) against other days, and how the stock reaction to a hawkish surprise and to the 2-year yield's move differs between rates-driven and growth-driven markets (HC1 t, a permutation p for the difference, and a fit before 2022 scored after it). No nowcast of sectors from the day's moves: tested out of sample it explained little beyond energy (see docs/todo.md, item 10). A class or era with too few releases shows its count and no figure; most effects on stocks are not detectable at these sample sizes and the panel says so. FRED's yields lag the close by a day: a session after its last reading has no yield move, not a zero one Sources: TradingView's economic calendar (release days, forecasts and actuals, from 2016), FRED DGS10 / DGS2, Yahoo daily closes |
| **CALENDAR → SCENARIO WATCH** (`watch.json`) | Two layers, and no opinion probabilities. **Scheduled** (automatic): each SCENARIOS release and the FOMC decision in the next `event_days` (14), with the consensus, Kalshi's price of a print above / in line with / below it (read off the strike ladder PRICED keeps; for a line published to one decimal, any miss of the tick), what the 2-year yield and SPY did on past releases in each branch (SCENARIOS' means, dim under \|t\| 2), and which branch the latest release landed in. **Conditions** (written by hand in `[[watch.scenarios]]`, checked at each build): named scenarios with observable triggers (a level, or an N-session % or bp change, of a Yahoo, FRED or ratio series; `match` all or any; an optional `kill`), each `triggered`, `near` (every needed trigger met or past its near line) or `quiet`, then `expired` with whether it triggered by its `horizon`, or `killed`. A threshold is fixed when the scenario is `added`: a moved one is a new scenario. How often the trigger fired over ten years is shown as context, not a forecast. TODAY lists triggered scenarios and any that changed state under SCENARIO WATCH | Yahoo daily closes for the trigger series, this session's SCENARIOS and PRICED |
| **MOVES** (`moves.json`, shown on HEAT MAPS and each ticker page) | Every covered stock's last session in its own terms: the return in units of its own 60-session σ, split by its market (SPY) and sector-fund betas (252 sessions) into market, sector and own parts with the own part's σ; close→open gap and open→close session; volume against its 20-session median; whether it reported (from CALENDAR); above or below its 200-day average; and the next 5 sessions' range from its own past moves scaled to today's EWMA volatility (filtered historical simulation, mean removed). For a shock (own part beyond ±2σ) the row also carries tags known at its close (report, gap-led, repeat, VIX high, stock and market against their 200-day averages), the range scaled by one cause-based factor (`[moves] range_factors`, from the research's calibration of the band; the raw band is kept as `range_raw`), and the card adds a table of what such shocks did over the next 1, 5 and 20 sessions (own part from the next open; mean, median, positive share, n, 95% interval) from the frozen `config/move_states_v1.json` (promoted conditions only; written by `scripts/export_move_states_table.py` in the quantamental-lab research worktree). Every estimate uses only the sessions before the one measured. HEAT MAPS lists names whose own part passed ±2σ and can colour the treemap by it (OWN σ); the ticker page shows its row under RECENT. On a session where XLK's own part against SPY is at or below -2σ while SPY's own is above -2σ (technology-only sell-off, quantamental-lab research v6: 78 such days since 2015), HEAT MAPS shows a banner above the unusual moves with the technology names in the hardest-hit fifth, each tagged high sector beta, fall made during the session (not a gap) and reported or not, and the descriptive history after such days (n and interval); no banner on other days. Descriptive, not a signal |
| **HEAT MAPS** | Index treemap with an S&P 500 / Nasdaq 100 / Dow Jones switch, each sized by its own fund's **issuer-published weight** (SPY, QNDX, DIA; the Dow is price-weighted, so its tiles follow share prices) and coloured by return (LIVE colours all three; the Dow's names are all S&P 500 members); US ETF treemap sized by AUM and coloured by estimated net flow |
| **RATES & MACRO → FIXED INCOME** | Published par yield curve vs. 1 week / 1 month / start of year, level and bps change by tenor, 10Y−2Y and 10Y−3M spreads; under the table, MOVE (Treasury option volatility) as RISK shows it, with ten years of weekly closes |
| **RATES & MACRO → CPI & MACRO** | Official CPI prints vs calendar consensus; BLS weights/effects and non-overlapping contribution waterfall; component history/percentiles; core, sticky and robust inflation persistence; commodity proxies and the existing PCE/income/spending heat table. No forecast model; updates with the normal build |
| **TECHNICALS** | Any A/B relative-strength ratio, as daily candles where both names have daily bars (since 2020: the body is the exact ratio of the opens and closes, the faint wick the widest the day could have been, as the two highs come at different times) or as the close line, with its moving averages, a ±1.5σ band around the longest one, how far the ratio sits from it in σ, and MACD, over any range from 1M to MAX; the ticker boxes suggest symbols as you type (those starting with the text, then names with a word starting with it, the larger index weights first); single-ticker price as candles (the last ~520 sessions, split- not dividend-adjusted, with a volume pane and, on by default, a VOL PROFILE beside them: volume by price for the sessions on screen, estimated from daily bars, its 70% value area, most-traded price, thin bins, the two heaviest nodes and the thin gap between them (HVN, LVN) and the window's high and low, with the window named above the chart and re-read on zoom; a range past the ~520 candles uses the daily bars since 2020, so 5Y has candles and the profile; a dashed level and its price follow the pointer; where trading was heavy, not a support or target) or a line, range buttons 1M–MAX and a log scale, removable MA chips and a stat strip (price, day, 52-week high and low, relative volume, each MA, distance to the 200-day), with **your own MA periods, slope window and period**, a ±1.5σ band, z-score regime, SMA slope, an RSI chart (Wilder, default 6, editable) with lines at 30 (oversold) and 20 (deeply oversold), and forward return by z-score band. Every indicator is computed in the browser from the baked close history, by one module tested against pandas |
| **MOVE CHECK** (`#movecheck/QQQ`) | How rare a move is in the name's own history: any ticker with a baked close history, today's move over 1, 5 or 20 sessions (or one typed in), the share of past days or windows that went further, its percentile, how often a year and the last time, over all history, five years and one year; the move in today's 20-session volatility; a histogram; and the past episodes beyond it (days within five sessions merged) with what followed over 1, 5 and 20 sessions and the worst drawdown, set against ALL DAYS in the same window (the baseline: median and share up on any day) with the difference, a 90% bootstrap interval over the independent episodes (none under 5, called wide under 20), the years they span, and the same figures for the earlier and later half of the window (a consistency check, not out-of-sample validation); an OVERNIGHT GAPS card (open against the prior close, daily bars since 2020: percentiles, the share beyond 2%, the largest gaps and where the latest sits); charts of what followed (episodes' 10th–90th, 25th–75th and median against all days', with the median's interval) and of each episode's +20 return over time, a histogram of the gaps; and links to the same name's ticker page, TECHNICALS and TRADE DESK. TODAY lists an index or sector fund (the RSI watch list) whose 1- or 5-session move was matched on at most 5% of its past days. A description of the past, not a signal |
| **ETF X-RAY** | Every fund on the ETF heat map looked through to its holdings, from the **issuer's own file** (State Street, iShares and Invesco daily, Vanguard monthly): concentration (top-10 weight, effective N), sector and country weights against SPY, the top 25 holdings with each one's contribution to the day, overlap with every other fund, and a **valuation look-through** (P/E, P/B, ROE, FCF and dividend yield, growth, margin) aggregated like an index and joined to the VALUATION rows, with the share of the fund it covers. Bond funds show duration, yield to maturity, coupon and maturity buckets. Funds with no usable holdings file (the commodity funds) are listed with the reason, never proxied |
| **CROSS-LISTING** | A US line against its home-market line at the depositary ratio, with the diagnostics that say whether the series measures a dislocation or a session gap |
| **NAMES → SCREENER** (`#valuation`) | Every S&P 500 / Nasdaq-100 member on one sortable table: P/E, EV/EBITDA, EV/Sales, P/B, FCF / dividend / shareholder yield, ROE, ROIC, gross profitability, margins, growth, accruals, leverage, interest cover, Piotroski F-score and margin stability — trailing twelve months from each company's own 10-Qs, market cap from the close. Valuation × quality scatter, sector medians, and colour by rank within sector; a row opens the company's TICKER page on its VALUATION tab, which has the **P/E against the company's own ten years**: price ÷ TTM EPS as it was filed at the time, on operating earnings (stake gains, divestitures and one-off tax items taken out) or as reported, with its median, percentile band and where today sits. Debt for EV is the latest quarter's long-term and current lines (notes and loans included); where a balance sheet files them under the company's own tags, which SEC's company facts leave out, the debt note's carrying amount, the debt by instrument, or the last quarter that tagged it (within a year) stands in, and the row says which (`debt_basis`) |
| **CREDIT** (`credit.json`; TICKER → VALUATION and THEMES → CLOUD → Financing) | Equity-implied default risk for every non-financial name VALUATION covers: the distance to default (Bharath and Shumway's naive form) from the share price times the shares filed, the debt due within a year plus half the long-term debt as filed in the latest 10-Q/10-K (each value from its filing date; debt filed with leases, by instrument or as one total is read too, the largest reading counting), a year of the share's volatility and the 1-year Treasury yield; the model's one-year probability, where today sits in the name's last five years, and a flag when the debt counted is a sliver of the filer's liabilities. A path is cut where counted debt jumps tenfold at one filing (the earlier filings held it under tags not read). TICKER shows the name's reading and its monthly path; THEMES CLOUD shows the AI borrowers (`[credit.watch]`: CRWV, NBIS, ORCL, META, MSFT, AMZN, GOOGL) on one log-scale weekly chart. A description, not a warning: in quantamental-lab (docs/credit_proxy_v1.md) its monthly changes track BAA − 10Y (correlation about −0.7, 2017–2026) but do not lead it, and new borrowing counts only once filed; it is not a CDS or bond price. Banks and insurers are left out |
| **RISK → RISK** (`risk.json`) | Opens on a matrix: six rows (equities, treasuries, credit, volatility, cross-asset, macro) by three columns (structure: positioning, liquidity, options and flows; technical: trend, volatility, drawdown, how fast spreads move; valuation: how thin the compensation for each risk is). VALUATION reads each premium (`scale = "valuation"`) against its whole history since 1960, or its own start: the equity risk premium as Shiller's excess CAPE yield, each session from his latest month (source: Robert J. Shiller, "Irrational Exuberance" data, shillerdata.com; `sources/shiller.py`), with Aswath Damodaran's monthly implied ERP beside it (pages.stern.nyu.edu/~adamodar; `sources/damodaran.py`); the 10-year term premium (Kim and Wright, Federal Reserve Board, via FRED THREEFYTP10); BAA − 10Y read as compensation, so tight is rich; and VIX − realised. Its words are cheap / fair / rich (thinner than 75% of the history) / very rich (90%), drawn as an outline and counted on their own line: a description of the cushion, not of timing (quantamental-lab docs/erp_history_v1.md). Each cell has one lead series (`[risk.matrix]`) read on the scale its cell names. `bands`: fixed lines in the lead's own unit, for levels with a meaning in any decade (VIX 25/35, VIX/VIX3M 1.0/1.2, VVIX 120/140, MOVE 100/120, SPX drawdown −5/−10%, VIX − realised 0/−5, HYG/IEF −2/−5%, BAA − 10Y 250/300bp and its 20-day change 10/25bp, NFCI 0/0.5), set from where each stood in past S&P 500 drawdowns (MOVE: IEF's drawdowns) or from a line with its own meaning (quantamental-lab docs/risk_matrix_bands_v1.md). `percentile` (the dollar's 3-month change, net liquidity, the real yield's 3-month change): the percentile in its own last ten years, elevated from the 75th, stressed from the 95th. `none`: shown, not coloured (copper/oil, which failed out of sample, is now a member of macro × technical beside NFCI). Grey: no reading or a stale lead. Each cell shows the lead's value, its lines (or percentile), its one-month direction and an evidence label (all descriptions for now); cells are never averaged or scored, and a click opens the cell's series with their history. Cross-asset × technical is the stock–bond correlation (63 sessions, S&P 500 returns against the 10-year's; bands 0 / +0.3, the level the 2022 and early-2025 drawdowns reached); treasuries × structure is demand at Treasury's nominal coupon auctions (each auction's bid-to-cover and dealer takedown against its own maturity's previous 12, averaged over the last 6; Treasury publishes no when-issued yield, so the tail itself is not computed; quantamental-lab docs/stock_bond_auctions_v1.md). Placeholders name what comes next: stocks against credit, EPS revision breadth and the OFR stress index. Below: Fear & Greed and all series by group. The systematic anchor's exposure is no longer shown here, on TODAY or in the agent feed (its copper/oil gate failed out of sample in quantamental-lab); the anchor artifact is still built for the lab and the trade desk's scorecard |
| **FINANCIALS** | Ten fiscal years of income statement, balance sheet and cash flow for every S&P 500 and Nasdaq-100 member, with key ratios, each column's period end and last filing date, restatements applied and pre-split years put on today's share basis |
| **BY BUSINESS** (on a company's FINANCIALS view) | Revenue by operating segment, product / service and region, with segment profit and margin, by quarter (about five years) and year (up to fifteen), from each company's own 10-K / 10-Q XBRL; each period from the newest filing that breaks it down, subtotals left out, unallocated corporate profit shown as its own line |
| **VALUATION → DCF** | SEC-filled 5-year history, your 5-year forecast, WACC, terminal value, equity bridge and a WACC × exit-multiple sensitivity grid |

## Data sources

Every one of these is free and requires no account.

| Source | Used for | Notes |
|---|---|---|
| **SSGA daily holdings** (`holdings-daily-us-en-<fund>.xlsx`) | S&P 500 and Nasdaq-100 constituents, official index weights, share counts | The issuer's own published basket with an explicit as-of date |
| **SSGA NAV / premium history** (`navhist-...`, `pdhist-...`) | Net flow and premium for State Street funds | Daily NAV, shares outstanding and premium back to 2003 |
| **BlackRock fund download** | Net flow and ETF X-RAY holdings for iShares funds | The workbook's `Historical` sheet carries NAV and shares outstanding back to inception; fund ids resolve through the iShares product screener |
| **Vanguard fund API** (`/vmf/api/<ticker>/{profile,price,characteristic,portfolio-holding}`) | Premium to NAV, whether an ETF is one share class of a larger fund, that share class's month-end net assets (tile size), and monthly stock holdings for ETF X-RAY | No shares-outstanding history, so no flow series; holdings published weeks after month end, with no sector or country |
| **Wikipedia** — List of S&P 500 companies | GICS sector and sub-industry | Current descriptive labels, cached weekly |
| **Yahoo Finance** via `yfinance` | Daily closes for constituents, ETFs and indices; ETF AUM and shares outstanding; commodity futures | Unofficial wrapper around a mutable service |
| **US Treasury** daily par yield curve XML | The yield curve | Official publication; "latest published" is not always today |
| **FRED** `fredgraph.csv` | PCE, core PCE, trimmed-mean PCE, personal income and spending | Keyless CSV export; current vintage, not point-in-time |
| **BLS / BEA** iCalendar feeds, **Census** indicator calendar, **Federal Reserve** calendar JSON, **Treasury** fiscaldata upcoming auctions | CATALYSTS macro lane | Each agency's own schedule with its release time; Treasury lists auctions only once announced, about a week ahead |
| **Invesco** holdings API (`dng-api.invesco.com/.../shareclasses/<CUSIP>/holdings/fund`) | ETF X-RAY holdings for QQQ and RSP | Unofficial JSON behind invesco.com; asked by ticker it answers for QQQ only, so funds are named by CUSIP. No shares-outstanding history, so still no flow |
| **FactSet Insight** Earnings Insight articles (`insight.factset.com/topic/earnings`) | CATALYSTS → EARNINGS FactSet block | Figures parsed from article text (parser shared with alternative-data's `factset_earnings_data`); history before the first build is the committed seed `data/reference/factset_earnings_insight.csv`. Weekly at best; numbers only, credited and linked |
| **Nasdaq** earnings calendar (`api.nasdaq.com/api/calendar/earnings`) | CATALYSTS single-name lane | Unofficial JSON behind nasdaq.com; timing, consensus EPS and, for past dates, reported EPS. Not marked company-confirmed |
| **SEC** XBRL company facts | FINANCIALS, VALUATION & QUALITY and the DCF | Annual and quarterly 10-K/10-Q figures with their filing dates, plus the cover-page share count; one parse per filer feeds all three tabs |
| **SEC** filing XBRL archives (`-xbrl.zip`) | BY BUSINESS | The dimensioned facts company facts leaves out (segments, products, regions); every other 10-K and the last twelve 10-Qs per company, cached per accession, filled within a per-build budget |
| **MOPS** (`mops.twse.com.tw/mops/api/t05st10_ifrs`) | THEMES: TSMC, Nanya, Quanta, Wiwynn, Wistron monthly revenue | The TWSE's disclosure system; published by the 10th. No publication date in the answer, so the date first seen here is kept |
| **Korea Customs Service** trade statistics (`tradedata.go.kr`) | THEMES: Korean IC (HS 8542) exports, plus memories (HS 854232) and the DRAM, flash, multi-chip and MCO lines inside it | Confirmed monthly figures, mid-month; certificate verification on. The breakout is export value, and value per kilogram of customs weight. It is not a spot price |
| **ADATA Industrial** Memory & Flash Market Watch | THEMES: monthly DRAM / NAND note | A module maker's read, quoted; its charts are images and are not read |
| **PCPartPicker** UK price trends (`uk.pcpartpicker.com/trends/price/{memory,cpu}/`) | THEMES: retail memory-kit and CPU prices | Read from the chart images' pixels (the page has no numbers); only ratios are reported, with the source linked. Its Cloudflare refuses cloud servers (HTTP 403) and is not worked around: the nightly build reads the committed ratios in data/feeds/pcpartpicker.json and does not ask the site. scripts/refresh_pcpartpicker.py refreshes that file from a home connection |
| **DART** (FSS electronic disclosure, public search `dsab007/detailSearch.ax`) | THEMES and AI CHAIN: Samsung Electronics and SK hynix results dates (the preliminary results first) | Their "영업(잠정)실적" fair disclosures, corrections dropped; no key needed |
| **Korea MOTIE** monthly trade release (`motir.go.kr`, PDF attachment) | THEMES: 1st-of-month semiconductor and total exports | Read with `pdftotext` (poppler, installed by the workflow); the site is slow, so only the last 13 releases are read, each cached once |
| **SEC EDGAR** earnings releases (8-K Item 2.02, Exhibit 99.1) | THEMES: NVIDIA Data Center revenue and outlook; capex guidance quoted from the releases | Segment revenue is not in XBRL company facts; matched text is quoted as written. Older submissions pages are read when a heavy filer's recent block (one year for the big banks) holds fewer than eight earnings releases; TSMC and ASML results come from their 6-K filings |
| **EIA** weekly history pages (`eia.gov/dnav/pet/hist`, `/dnav/ng/hist`) | THEMES: weekly crude, gasoline, distillate and gas inventories, refinery utilization, crude production | Keyless HTML tables, petroleum back to 1982, gas storage to 2010; current vintage. The 5-year average is the same week of the five years before |
| **Yahoo** front-month futures (CL, BZ, NG, RB, HO) | THEMES: oil, gas and the 3-2-1 crack | Cached apart from the members' prices |
| **Yahoo** fundamentals-timeseries (`/ws/fundamentals-timeseries/v1/finance/timeseries/<symbol>`, types `monthly`, `quarterly`, `annualForwardPeRatio`) | VALUATION: each company's own forward P/E at every month end back about fifteen months, and at its last four fiscal year ends | Unofficial and undocumented, like the other Yahoo feeds. One series per request (several together come back truncated). Point in time, but on a fiscal-year EPS, not the next twelve months: see "Yahoo's forward P/E history" |
| **Yahoo** market cap (quoteSummary `price`) | VALUATION: the market cap of a company whose filings count shares only class by class (Berkshire, Hershey, Ares), so P/E, EV and yields exist for it | Labelled on the row's share basis; such a row stays out of the index and sector P/E aggregates, as its per-share EPS may be in another class's shares |
| **FRED** BLS semiconductor prices (PCU334413334413, PCU3344133344131, IZ3344, IR21320) | THEMES: US producer and import price indexes for semiconductors | Public domain, keyless CSV, current vintage. BLS indexes of its own product basket, not DRAM or NAND spot quotes. Ids live in config/dashboard.toml |
| **FRED** housing series (MORTGAGE30US, HOUST, HOUST1F, PERMIT, HSN1F, MSACSR, CSUSHPINSA), GASREGW, DGS10 | THEMES: housing data, the pump price, rate sensitivity | Current vintage, keyless CSV |
| **Finnhub** company news (`FINNHUB_API_KEY`) | TICKER: headlines on large-move days and company events announced ahead (investor days, product events, FDA dates) | Free tier: about a year of news, 60 requests a minute; a budget per build, settled days kept a year; without the key, moves are explained from filings, ratings, peers and data only |
| **EDGAR filing index pages** | Earnings releases' acceptance time (Eastern), for the eight reports measured | The submissions JSON stamp ran twice the Eastern offset late in October 2026; fetched once per filing and kept |
| **ALFRED** (FRED's vintage archive, `FRED_API_KEY`) | THEMES: the day each FRED observation was first published and its first print (with the year-earlier figure as then known), for the release-day studies and the stock cards' since-the-last-report table, which marks a figure revised since | Free key; GitHub secret in CI, alternative-data's `.config` locally; without it, release lags are approximated |
| **FRED** bank and consumer series (TOTLL, DPSACBW027SBOG, T10Y2Y, T10Y3M, BAMLH0A0HYM2, DRALACBS, DRCCLACBS, DRCRELEXFACBS, DRTSCILM; RSAFS, RSFSXMV, PCEC96, PSAVERT, TOTALSL, UMCSENT, ICSA, CCSA) | THEMES: banks and consumer data, curve/credit sensitivity, stock-card drivers | Current vintage, keyless CSV; release dates approximated from each publisher's schedule (ICE BofA OAS: last three years only; Michigan sentiment a month behind) |
| **Yahoo** earnings archive (the visualization API `get_earnings_dates` reads) and quoteSummary `earnings` / `calendarEvents` | AI CHAIN: every report of 67 companies in seven markets, with its time of day and EPS surprise, and the next date | The archive stopped taking rows in mid-2025 (kept a year at a time); the last four quarters come from quoteSummary. The reports of July–September 2025 are missing for a company outside SEC filing and stay missing |
| **EDGAR full-text search** (`efts.sec.gov/LATEST/search-index`) | AI CHAIN: the sentence of each company's 10-K / 20-F / 40-F that names the other end of a link | Run by hand (`scripts/chain_evidence.py`) when the graph changes; the result is committed as `config/ai_chain_evidence.json` |
| **alternative-data** (github.com/Henrywzh/alternative-data) normalized files | THEMES: OpenRouter daily tokens and estimated revenue; Ramp AI Index; Ramp Tokenomics (weekly token volume and spend by model, daily effective token prices; Ramp's Token Spend Management sample, refreshed Monday and Thursday upstream) | Read from the public repo, with the commit that last touched each file |

### Two things worth knowing about the feeds

DRAMeXchange spot and contract prices are not on this site. Its terms forbid republication, and contract history sits behind the member login. scripts/refresh_dramexchange.py archives the public homepage on this machine only, under data/private/dramexchange/, which is gitignored and is not read by the build.

The public alternatives have explicit reuse guidance: [BLS copyright information](https://www.bls.gov/opub/copyright-information.htm) places its published data in the public domain and requests source attribution. Korea Customs' [product-level trade-statistics dataset](https://www.data.go.kr/data/15101609/openapi.do) lists unrestricted permission (이용허락범위 제한 없음), and its [public-data policy](https://www.customs.go.kr/cvnci/cm/cntnts/cntntsView.do?mi=7613&cntntsId=2611) permits reuse including commercial purposes, excluding protected third-party information. The dashboard identifies both publishers and links to their data; export value per kilogram is a customs unit value, not a memory spot quote.


**Identify yourself honestly.** FRED's edge accepts curl's own identifier
instantly and stalls the identical request when it carries a Chrome
User-Agent, because the claim contradicts the TLS fingerprint. `sources/http.py`
sends `market-recap/0.1 (research; ...)` and every feed accepts it.

**Yahoo drops symbols.** A single batch request for the S&P 500 returns 503
columns on one run and 497 on the next, and a second full sweep within a few
minutes comes back half empty. `sources/yahoo.py` re-requests what is missing
in smaller batches under a time budget and caches the day's closes, so a
rebuild costs seconds. Whatever is still missing is reported as a coverage
gap, never back-filled.

## Install and run

```bash
make install
make refresh
make serve        # static build only; make serve-live adds the quote function
```

`make refresh` is the whole pipeline: fetch, build, **validate**, prune. It
exits non-zero if anything would put a wrong number on the page, so it is also
what the nightly job runs. `make help` lists the rest.

Rebuild a single tab while iterating:

```bash
python -m market_recap.cli refresh --panels markets --skip-sec
```

### Running it on a schedule

The nightly job is a GitHub Actions workflow,
[`.github/workflows/refresh.yml`](.github/workflows/refresh.yml): it tests,
refreshes with `--strict`, and deploys only if that passed.
It runs on GitHub's machines, so it does not depend on a laptop being awake —
the launchd job this replaced missed its first night because the lid was shut.

```bash
make status    # last five runs, and the as_of the live site is showing
make run-now   # trigger it now (gh workflow run refresh.yml)
```

Two feeds are not fetched from GitHub's machines. PCPartPicker refuses cloud IPs, so a local job runs scripts/refresh_pcpartpicker.py each morning and commits data/feeds/pcpartpicker.json; the nightly build only reads that file. DRAMeXchange's terms forbid putting its prices on this site, so scripts/refresh_dramexchange.py archives the public homepage under data/private/ and never commits it.

A failed scheduled run emails the repo owner. `workflow_dispatch` takes a
`deploy` input, so a run can build and validate without publishing, and a
`mode` input, so a small fix does not pay for a full rebuild (GitHub bills each
run's minutes, rounded up per job; the workflow is one job):

| `mode` | What runs |
|---|---|
| `full` (default; scheduled runs and the Worker's dispatches) | Everything: fetch, `--strict` build, test, site, smoke test, deploy. |
| `site` | No refresh. Restores the last published `artifacts/`, then test, site, smoke test, deploy. For a change to `web/` or `functions/`. |
| `panels` | Restores the same artifacts, runs `refresh --strict --keep-cache --panels <panels>` (the `panels` input, space-separated) on top, merges the manifest, then the same test, site, smoke test, deploy. |

Every full or panels run that deploys saves `artifacts/` to the Actions cache
(free, unlike `upload-artifact`) under `published-artifacts-<run id>`; site and
panels restore the newest. With nothing cached they fail with "run mode=full
once". A panels run rewrites `manifest.json` with only the panels it built, so
`scripts/merge_manifest.py` puts the other panels (and their recorded errors
and any carried MONITOR) back and validates the whole set: a rebuilt panel
dated to a different session than the cached ones fails there rather than
publishing a page with two "todays". `as_of`, `generated_at`, sources and
timings are those of the panels run. Site and panels runs are titled by their
mode, so the fallback schedule never counts one as an evening edition.

Two editions a weekday, started on time by a Cloudflare cron Worker
([`workers/dispatch`](workers/dispatch), `make deploy-dispatch`), which calls
the workflow's `workflow_dispatch` with an `edition` input:

| New York | Edition | What it has |
|---|---|---|
| 16:20 | `close` | The session's closes and everything built from them: returns, heat maps, sectors, technicals, risk, valuation, earnings cards. Up about half an hour after the bell. Yahoo's prices cached before 16:15 are stale after it, so the closes are fetched; every other daily file is still last evening's (the 18:30 rollover has not passed), so nothing else is downloaded again. Not published unless it covers the session that just closed. |
| 18:35 | `evening` | Everything, after the 18:30 rollover: the evening publishers' files (Treasury's par curve, fund NAVs and flows, Cboe's put/call, late earnings figures) are fetched again. |

The header says when the page is the close edition. Both fire within the
minute; GitHub's own schedule (23:47 UTC) started two to three hours late
every night, so it stays only as the fallback and skips itself when an
evening edition passed in the last ten hours **and the live manifest confirms
that evening edition covers the latest completed NYSE session**. A successful
dry run or an old published session does not suppress the fallback. The Worker fires at both
daylight-saving candidates (20:20/21:20 and 22:35/23:35 UTC) and keeps the
ones that are 16:20 and 18:35 in New York.

The Worker needs one secret: a fine-grained GitHub token for this repository
only, with Actions read and write, set with
`cd workers/dispatch && ../../node_modules/.bin/wrangler secret put GITHUB_TOKEN`.
Without it the Worker logs that nothing was dispatched and the late GitHub
schedule is all there is.

The run uses `--strict`, so a warning fails it. Nobody reads the output of an
unattended job, and a job that exits 0 on a degraded build is how a stale page
stays up for a week.

The job installs from `requirements.lock`, not from `pyproject.toml`'s ranges.
The first cloud run resolved pandas 3 and yfinance 1 — both newer majors than
anything this was tested on — and failed. `make lock` re-resolves the lock on
purpose; upgrading is then a commit that was tested, not something a clean
machine does on its own one night.

Three checks protect the published session:

- **An edition must cover the latest completed NYSE session.** Strict
  validation compares its `as_of` with the build timestamp in New York,
  including holidays and early closes. Yesterday's internally consistent
  build is not today's evening edition. Price caches are checked by their
  observation date as well as their file timestamp, and missing latest
  closes are retried without inventing them.

- **Daily files expire at the session rollover, not after 24 hours.** Prices
  and issuer files count as fresh only if fetched after the latest weekday
  18:30 New York. With a plain 24-hour lifetime, a run starting a few minutes
  earlier than the night before reuses yesterday's closes and publishes a page
  one session behind that passes every check.
- **A deploy never moves the site backwards.** `scripts/guard_deploy.py`
  refuses a build whose `as_of` is older than the live page's, and refuses
  when it cannot read the live page — a guard that allows what it cannot check
  is not one.

`data/cache` is carried between runs with `actions/cache`. It is not state:
source-derived readings rebuild from the publishers, so an evicted cache costs one
slow run and more requests to them, never a wrong number. MONITOR's observation
ledger is different: cloud refreshes restore the last published monitor artifact,
and refuse to reset it if restoration fails. The workflow also archives that
artifact for recovery. Manual follows live in the reader's browser and can be
exported/imported. The cache key
includes `requirements.lock`'s hash: files written by other library versions
are not reused.

### Where the time goes

The manifest's `timings.panels` and the build log say how long each panel took, and
`MARKET_RECAP_PROFILE_DIR=profile make refresh` writes each panel's hottest
functions to `profile/<panel>.txt`. `.github/workflows/profile-build.yml` runs the
nightly job's refresh on a branch, with the same cache and secrets and nothing
published, and uploads both: measure there before optimising, because the cost
was nowhere a reading of the code suggested. The first profile (1,823 s with
cProfile) found EVENTS alone at 1,111 s -- the same earnings releases parsed
again every build and Finnhub's rate limit waited out after the work instead of
beside it -- and Treasury's curve downloaded eight times. After fixing those and
a handful of smaller ones (the split-factor lookup, the SEC filer cache keyed two
ways, MONITOR re-normalising every peer's prices) the same profile took 990 s.
What is left is mostly waiting: Finnhub's 400 requests a build at 60 a minute
(`news_budget`, `event_news_budget`) and the Korean ministry's slow server.

### Deploying

```bash
make deploy        # refresh, validate, then publish to Cloudflare Pages
make deploy-only   # publish what is already built
```

`make serve` and `make deploy` look at the same directory. The site is
assembled into `dist/` — `index.html` at the root with `artifacts/` beside it
— and that is the tree both serve and deploy read. Serving `/web/index.html`
locally while production served `/` would mean the deploy step rewrote asset
paths, and a path rewrite is the kind of build-time magic that works until the
day it silently does not, on the copy nobody runs locally.

The Pages project is `market-recap`. Creating it needed
`wrangler pages project create market-recap --production-branch main --force`,
because current wrangler delegates Pages commands to Workers and reads this
`wrangler.toml` as a Workers config with no entry point. `--force` is needed
only once, for the create; deploys run against Pages directly.

Credentials for the nightly job are two repository secrets,
`CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. The token needs one
permission: **Account → Cloudflare Pages → Edit**. The account ID is required
because a Pages-only token cannot list accounts for wrangler to pick from.

wrangler is pinned in `package.json` rather than invoked through `npx
wrangler@latest`: a nightly job should not resolve a new major version over
the network overnight and find out what changed.

Deployment is by direct upload rather than Pages' git integration. The
artifacts are rebuilt every session and are not in git, so a git-triggered
build would check out a repository whose `artifacts/` is ignored and publish
an empty dashboard. Locally, authentication is `wrangler login` once; the nightly job uses the
secrets above and deploys only after `--strict` validation passes, because putting the bad page
in front of people and then telling a log file about it is not a deploy
strategy.

### Validation

`make validate` re-checks the artifacts on disk without refetching:

| Check | What it catches |
|---|---|
| `period_label` | a table offering a window nothing defines |
| `as_of` | one tab dated to a different session than the rest of the page |
| `coverage` | index members that never got a price |
| `preset` | a relative-strength preset naming a ticker no panel baked |
| `ratio_provenance` | a cross-listing ratio with no cited filing |
| `flow_attribution` | a fund with flow but no named provider |
| `freshness` | a source past its own staleness window |

These are not hypothetical. Every one of them has fired on this repository.

`make smoke` then opens every view of the built site -- plus the largest
names, a share class typed as `BRK.B`, a fund, an index and each theme -- in
headless Chrome (the installed one, through `playwright-core`), and fails on a
page that throws, logs an error, asks for a file the build lacks, renders
nothing, or prints `NaN` / `undefined`. The nightly job runs it after the build
and publishes nothing when it fails. `make test` runs pyflakes before the
Python and JavaScript tests.

## Layout

```
config/dashboard.toml      the contract: indices, universe, windows, thresholds
src/market_recap/
  config.py                paths, definitions (a trading year), cache policy
  cache.py                 one on-disk cache for every feed, with pruning
  sources/                 one module per publisher
  compute/                 returns, breadth, filed-statement ratios — one definition each
  panels/                  one module per tab -> one JSON artifact
  context.py               constituents + prices, fetched once per build
  build.py                 orchestrator, writes manifest.json
  validate.py              checks the artifacts against the contract
  snapshots/               recorded option chains and market pricing (not read by the page yet)
functions/                 Cloudflare Pages functions: api/quotes.js (live prices), mcp.js (the MCP route)
mcp/                       the MCP server's modules and tool adapters (docs/mcp.md)
web/                       static site (ES modules, ECharts from CDN)
  js/technicals-math.js    every technical indicator; tested against pandas from tests/
artifacts/                 generated JSON the site reads
data/cache/                raw snapshots and parsed frames, pruned each build
data/snapshots/            checkout of the `snapshots` branch (recorded history)
```

## Recorded snapshots

Some history cannot be downloaded later for free, so
`.github/workflows/snapshots.yml` records it from the day it runs and
commits each run to the orphan `snapshots` branch (data only):

- **Option chains**, once a session from 15:10 New York (GitHub starts
  scheduled runs hours late, so the window runs to midnight: options stop
  trading at 16:00 and a later run records the closing quotes; a zero bid is
  unusable). About 50-90 underlyings (`[snapshots.options]`: index, sector
  and macro ETFs, the largest index weights, the watchlist, every name
  reporting within three days, and up to 15 MONITOR candidates).
  Per expiry, ATM IV, 25-delta put and call IV, the ATM straddle and open
  interest, all solved from bid/ask mids under Black-76 against the
  parity-implied forward, never Yahoo's last-trade IV. Contracts within 25%
  of spot are kept raw.
- **Market pricing**, four times a weekday: fed funds and SOFR futures,
  every open Kalshi market in the configured series, Polymarket's Fed
  markets. Inputs only; probabilities are derived from them later.
- **Consensus EPS**, each weekday evening: Yahoo's estimates (this and next
  quarter and fiscal year) for every company VALUATION values. Free sources
  publish only today's consensus, so this is the only way a forward P/E gets
  a history: each company's and each index's and sector's forward P/E is
  drawn from the recorded days, starting 2026-10-01. Until a year is
  recorded it is compared across companies and with FactSet's index figure,
  not with its own past.

Forward P/E is price over next-twelve-months consensus EPS (this fiscal
year's and next year's estimates, weighted by how much of each the coming
twelve months covers). Yahoo's estimates are on the analysts' basis --
adjusted EPS for most companies -- so a forward multiple is not the same
measure as the trailing one on filed EPS. The S&P 500's own forward P/E,
with its 5- and 10-year averages, comes from FactSet: the blog's articles in
season and the weekly Earnings Insight PDF every Friday (its text, via
pdftotext; the sector page is an image and is not read).

**Financials, divided.** The build splits Financials into diversified banks,
regional banks, investment banks and brokers, asset managers, insurers,
payments and consumer finance, and exchanges (`[[valuation.subgroups]]` in
`config/dashboard.toml` -- a GICS sub-industry, the S&P 500 labels on
Wikipedia, belongs to one group, never a ticker), each aggregated exactly as a
sector is. The sector chart on SECTORS compares only the indices and the
eleven sectors; the bank groups' P/E and P / TBV bands appear on their
sub-industry pages (`[sectors] sub_industry_valuation`).

**P / tangible book and ROTCE.** VALUATION adds both as columns (so the
scatter can set one against the other), and the bank groups show P / TBV as a
total on their sub-industry pages. A sector has none: too little of most
sectors' cap has a positive tangible book (Visa, Mastercard, Home Depot and
Procter & Gamble have none after buybacks and acquired goodwill). Tangible book is shareholders' equity less
preferred stock, goodwill and other intangibles, as filed in the latest 10-Q;
ROTCE is TTM net income to common holders over the average of tangible book
now and a year ago. A company that tags neither goodwill nor intangibles has no
tangible book; an untagged preferred is taken as none and the row says so. Not
adjusted for deferred tax or servicing rights, so a bank's own tangible book per
share can differ. P / TBV has ten years too: the bank sub-industry pages and a
percentile column draw it, each quarter's tangible book per share built
only from the balance sheet filed by that day, on today's share basis over the
quarter's diluted count (a little above the period-end count for a company
that buys back stock). ROTCE has no history yet.

**Valuation path and a forward P/E's missing past.** MARKET → SECTORS adds,
for each index and sector, its multiple at four points on the same analyst
basis -- last fiscal year's actual, this fiscal year, the next twelve months
and next fiscal year -- with the earnings growth each step carries, counted
over the same companies at every stage; and a grid of the price change implied
by moving the forward P/E and revising NTM EPS (`[valuation.scenario]` sets the
axes). The grid is price = multiple x EPS on today's multiple, not a forecast.
A sector's next-twelve-months P/E has no past before 2026-10-01: the earningsTrend
module Yahoo serves gives only today's consensus, so that measure cannot be
back-filled (Yahoo's own per-company history is on another basis, below).
FactSet's sector page might supply averages and history, and `probe-factset.yml`
(manual) measures whether its numbers can be read and how far back the PDFs go,
before any reader is written.

**Yahoo's forward P/E history.** Separately from earningsTrend, Yahoo's
fundamentals-timeseries service keeps a forward P/E for each company at every
month end (about fifteen), at its fiscal quarter ends (which add points the
monthly series lacks) and at its last four fiscal year ends. `sources/forward_pe_history.py`
reads it, `compute/valuation.py` shapes it, and the P/E history on the ticker
page draws it beside, never in place of, the recorded NTM multiple. Measured on
the 512 companies of the universe (2026-10-09):

- **Coverage.** 507 have a history (the other five, CRWV, ERIE, L, NBIS and
  RKLB, are named in the build's `fiscal_forward` report); 483 have twelve or
  more monthly points. 186 lack July 2026 and 18 lack April and May 2025: Yahoo's
  gaps, listed per company on the page, not bridged. None is negative.
- **Point in time.** The EPS behind a point (close / P/E) rises through the year
  as estimates were revised (Goldman: 44.3 in June 2025, 52.3, 55.5, 58.9, 64.6
  in August 2026), so a point is what the market was told that day; it is not
  today's consensus applied backwards.
- **Not a twelve-month multiple.** The EPS is a fiscal year's consensus that
  moves to the next year three months before the year ends. At that month the
  implied EPS jumps by a median of +12.4% (94% of those 497 observations by more
  than 3%), against 0.0% in the 5,811 others; moving the assumed roll to 1, 2, 4 or 5
  months before year end shows no jump at all. So each point looks 4 to 15
  months ahead, the line steps down at the roll, and the page marks that month.
  `FY_ROLL_MONTHS` is a rule read off this data, not published by Yahoo. It
  follows that the series is not the page's NTM multiple (a different horizon
  and, through the year, a different level), and the two are not drawn as one line.
- **How to compare.** A point against the same month a year earlier (same
  horizon), or the fiscal year ends, which are always exactly twelve months
  ahead. Four year ends and fifteen months are not a ten-year history; the
  percentiles above still come from the filed trailing P/E.
- **One series per request.** Asked for monthly, quarterly and annual in a
  single call, Yahoo answers with only the last four monthly points. The source
  makes three requests per company (1,536 in about 80 seconds; weekly-cached) and
  VALIDATION warns when fewer than 80% of companies have twelve monthly points.
- **Extremes are kept.** Boeing's 3,333x and Warner Bros. Discovery's 5,000x are
  a near-zero EPS, a growth stock's 120x is real, and the multiple alone cannot
  tell them apart. Nothing is removed: the table shows the figure, the report names
  the companies above `EXTREME_FORWARD_PE` (100x), and the chart's axis stops at
  2.5 times the 75th percentile.

The audit behind these figures was a one-off run. To repeat it, call
`forward_pe_history.fetch_series` for the universe, or read the `fiscal_forward`
report in `valuation.json` after a build.

`make snapshot-options` and `make snapshot-expectations` write the same files
under `data/snapshots/` locally. The plan they serve is
`docs/information_architecture.md`.

## Live intraday prices

Three things on the page change on their own during the session, each labelled live with
its age: the **strip** at the top of MARKETS and TODAY (SPX, NDX, RUT, Dow,
VIX, the 5Y/10Y/30Y yields, the dollar index, WTI and gold, then a row of
names to watch: `[live] strip` and `strip_names`), the **intraday index
charts** on INDICES (five-minute closes against the previous close), and the
**S&P 500 heat map's LIVE window** (each tile coloured by today's move so far).
Prices are Yahoo's spark (indices, VIX, the dollar, futures, stocks, and
Cboe's Treasury yield indexes ^FVX/^TNX/^TYX for the strip's yields; Yahoo has
no 2-year). Each price shows its source and age; one older
than `stale_after_seconds` during the session is marked STALE, and one that
did not arrive is a dash, never a number from elsewhere. Everything else on
the page is the nightly build's close; LIVE is the heat map's default only
while the session is open.

In pre-market (04:00–09:30 ET) and after hours (16:00–20:00 ET) the heat map's
**LIVE** window shows extended-hours moves instead: each name's latest
extended-hours price (the spark answer's `fulldayPrice`, no extra request)
against its last regular-session price; a name with no extended trade stays
grey, and the caption says which it is. LIVE is the default in those hours too.
The board asks every `board_extended_refresh_seconds` (15 minutes) then, only
while the tab is visible; overnight and at weekends it asks only on REFRESH and
wakes at 04:00 ET.

Three more blocks take live prices **only when the reader presses REFRESH**,
and never fetch on their own:

- **SECTORS: a TODAY window.** The page's own GICS baskets priced at each
  member's live change from the heat-map board, weighted by today's official
  SPY weight, against the whole index built the same way. Relative strength,
  breadth, sub-industries and the members that moved a sector all get TODAY;
  members without a live price are left out and counted. Beside each basket
  is its SPDR fund against SPY (`[live] sector_etfs`), as the tradable
  comparison. The rotation graph stays on weekly closes.
- **MACRO commodities.** PRICE and 1D from Yahoo (`[macro.commodities]`);
  1W and longer stay on the build's closes.
- **Treasury yields.** CNBC's on-the-run yields for all 13 tenors in one call
  (since 2026-10-12 CNBC answers Cloudflare's servers with HTTP 403, so the
  live columns show its error until that changes)
  (`[live] yield_board`), as LIVE and TODAY columns, live 10Y-2Y and 10Y-3M,
  and a dashed live curve on the chart. These are market yields, not
  Treasury's fitted par curve: the two differ by a few bp on coupons and
  about ten on bills on the same day, so TODAY is the comparison, not the
  level.

- **Refresh.** The strip every `refresh_seconds` (60) during the session; the
  heat map and the index charts every `board_refresh_seconds` (300). Closed,
  each checks every `closed_refresh_seconds` / `board_closed_refresh_seconds`
  for the open. A hidden tab does not poll and catches up when shown. REFRESH
  asks again at once, though never sooner than `manual_min_seconds` (30)
  after the last fetch.
- **Server side.** `functions/api/quotes.js` is a Cloudflare Pages Function,
  deployed with the site because `wrangler pages deploy` picks up
  `functions/` from the repository root. It fetches only what `dist/live.json`
  lists; `site.build` writes that file from `[live]` and the heat-map
  artifact's members, so the endpoint cannot proxy arbitrary symbols. Spark
  takes 20 symbols a call: the 504-name heat map is 26 calls, inside the 50
  sub-requests a Function may make. Readers share one fetch per
  `server_cache_seconds` (15, the strip) or `board_cache_seconds` (60) per
  Cloudflare isolate.
- **Session.** Open means now falls inside the regular session Yahoo reports
  for the indices (or the board's stocks), which handles weekends and
  holidays without a calendar here. Change is against Yahoo's previous close.
  Yahoo's Russell 2000 quote runs about 15 minutes behind and its futures and
  dollar index about 10; their ages say so.
- **Sources were chosen by measurement** from Cloudflare's edge (2026-09-24
  after the close, 2026-09-25 mid-session): Yahoo ~45 ms with prices a few
  seconds old, CNBC ~120 ms and ~15 s behind (CNBC refuses Cloudflare since
  2026-10-12; the strip's yields moved to Yahoo). Nasdaq (2-3 s per call) and
  Cboe (15-minute delay, up to 0.3% off) were not used.
- **Locally**, `make serve` has no function, so the live blocks report HTTP
  404 and the heat map stays on the close; `make serve-live` runs the same
  tree under `wrangler pages dev` with it.

## Agent feed

Two files for an outside research agent, written by every `refresh` right
after validation and published with the site:

| File | Size | What it is |
|---|---|---|
| [`artifacts/agent-index.json`](https://market-recap-b5p.pages.dev/artifacts/agent-index.json) | ≤ 16 KB | The entry point: the market's state in a few numbers, the research candidates in a fixed order, the next seven days and every data-quality alert. |
| [`artifacts/agent-brief.json`](https://market-recap-b5p.pages.dev/artifacts/agent-brief.json) | ≤ 150 KB | The detail, along the page's chain: risk budget, market, sectors, names (full cards for changes, one line per exit), timing (seven days in full, thirty as one line each), review (the last session's reports against what was expected), every candidate, and the candidate ledger. |

Both are condensed from the artifacts the same build published
(`agent_feed.py`): nothing is recomputed, nothing new becomes public, and
each section names the artifact behind it. A **research candidate** is raised
by a fixed rule (`agent_feed.RULES`) and carries a neutral question, never a
verdict. Conditions -- a risk tile past its threshold, MOVE against VIX, a
sector event -- are tracked against the previous published feed: `new`,
`continuing`, `resolved` only when a valid new reading shows the condition
ended, `unknown` when this build had no valid reading. A rerun of a session
compares with the session before it. The overlay's exposure is labelled as the
model's suggestion, not a position.

The interface for the agent -- per-company files, update times, known gaps
and how to request data -- is [`docs/research_agent.md`](docs/research_agent.md).

A feed that cannot be built or fails its own checks (size, schema, every
candidate pointing at an artifact this build wrote) is deleted, never left
from an older build; the site answers a missing file with **404**
(`web/404.html`), not with the dashboard page.

## MCP server

A read-only remote MCP server at `/mcp` lets an assistant (Claude, ChatGPT,
Gemini, Claude Code) ask the dashboard questions: a market snapshot, the
catalyst calendar, one company, unusual moves, a sector or theme, macro cards,
and `search`/`fetch`. It answers only from the files this site publishes, with
every result carrying its `as_of`, sources, caveats and what was unavailable.
Tools, client setup and the rule that a panel and its adapter change together
(`scripts/check_mcp.mjs`, run by `make smoke`) are in [`docs/mcp.md`](docs/mcp.md).

## Design rules this repo follows

- **Absence is rendered as an em dash, never as zero.** "No data" and "no
  change" are different statements.
- **A panel that fails leaves a named gap.** An empty tab with no explanation
  reads like a true report of a quiet market.
- **One definition per concept.** A "1M return" is 21 trading days on every
  tab, or the tabs contradict each other.
- **Every number carries a source and an observation date**, shown in the
  footer with a freshness label. The header shows how old the build is, not a
  ticking clock: this is a static build, and a live-looking clock beside stale
  data is a lie the page tells for free.
  The live strip is the one intraday element, and it carries its own age per
  price instead of borrowing the header's.
- **Short history degrades per reading, not per ticker.** A recent listing
  keeps the readings its history supports and names what the rest would need
  ("needs 200 sessions, has 51") rather than vanishing from the tab.
- **Area and colour stay independent on the heat map.** Tile size is the
  published index weight; colour is return.
- **A number that is a choice lives in `config/dashboard.toml`; a number that
  is a definition lives in `config.py` with a name.** A trading year is 252
  sessions whatever anyone wants; which windows a table offers is a preference.
  Nothing analytic is written as a literal in a builder — adding a third index
  is a config change, not a code change.
- **Identity is resolved from the publisher, never remembered.** A hard-coded
  BlackRock portfolio id for SHY returned the 0–1 Year Treasury fund, and
  nothing downstream would have shown that the flow series belonged to a
  different fund. Ticker→id now comes from BlackRock's own screener.
- **The build validates itself.** See the table above.
- **A new 10-Q reaches the page the night it is filed.** Company facts are
  megabytes per filer and SEC answers no conditional request for them, so they
  used to live out a fixed three-day cache: a 10-Q filed on Monday showed on
  Thursday. Each night the build now reads every filer's submissions index
  (tens of KB, updated as filings are accepted; six in parallel under SEC's
  ten-a-second limit, about a minute for 515 filers) and refetches only the
  company facts older than the latest 10-K/10-Q/20-F/40-F or amendment. A
  copy fetched within six hours of that filing is fetched again the next
  night, in case SEC had not processed it yet. The thirty-day cache lifetime
  is only the backstop. The manifest's `sec_filings` says how many were
  checked and refetched and keeps the latest filing date. Submissions-index
  freshness uses the oldest actual index-fetch date, so a quiet filer does
  not look like a failed fetch and a stale cache fallback stays visible.

## Known limits

- **Yahoo's recent sessions are checked against IVV's closes, and rebuilt when
  wrong or missing.** Yahoo has served a session as NaN, dropped one outright
  (1D then spanned two days), and on 2026-09-22 served adjusted closes that
  were a stale snapshot -- RCL +1.6% on a day it closed −6.1%, advancers 291
  against 248 -- which passed every check because every name had a price.
  Now the last five rows are checked against the NYSE calendar (a skipped
  session becomes an empty row), and the session on the IVV holdings date is
  compared name by name with the prices the fund's NAV was struck at; a
  median disagreement over 0.1% marks it wrong. A wrong or missing session is
  rebuilt from IVV (S&P 500 members), Nasdaq's historical quotes (other
  stocks, ETFs) and FRED (S&P 500 and Nasdaq-100), put on the adjusted basis
  with each name's factor from the session before. The MARKETS tab says so at
  the top, with the counts by source and anything still missing. IVV's file
  comes out the morning after, so the night's own session is checked against
  Nasdaq's closes for the 30 largest members instead; when too few answer,
  the page says the session was not cross-checked.
- **Spin-offs are adjusted from `[[corporate_actions]]`, not by Yahoo.** Yahoo
  adjusts closes for splits and dividends but not distributions: Corteva's
  separation of Vylor (one share per share, ex-date 2026-10-01) showed CTVA as
  77.65 to 12.57, an 84% loss on a holder who had lost nothing, and dragged
  Materials 4 points under on the rotation tab. Each entry in
  `config/dashboard.toml` names the ticker, ex-date, the distributed ticker and
  the ratio from the filing; the factor is computed from both lines' prices on
  the ex-date (`corporate_actions.py`), applied to every close and traded price
  before it, and said at the top of MARKETS and in the manifest. If the
  distributed line has no price that day, history before the date is dropped
  rather than left wrong. `[price_checks]` lists any recent one-session fall of
  60% or rise of 150% with no split on record as a notice, because it may be
  the next one; news produces these too, so it never blocks a build. VALUATION
  for a spun-off parent stays on pre-spin EPS until its first post-spin 10-Q.
- **SEC's company-facts feed can skip a filing, so the build reads it itself.**
  Citigroup's 10-Qs of 2026-05-07 and 2026-08-06 never reached company facts,
  and the VALUATION row sat on FY2025 (P/E 15.7, ROE 6.8%) while every other
  bank was on 2026-06-30. Each night the build compares a filer's statement
  filings in the submissions index with what company facts carry, and reads any
  it lacks from the filing's own XBRL instance (`sources/xbrl_instance.py`:
  facts with no dimension, in company-facts' shape, cached per filing). A
  filing accepted in the last six hours is left for SEC to process. The
  manifest's `sec_filings.backfilled` lists the filers; one that cannot be read
  is `unprocessed` and fails `--strict`. IFRS filers are not read. Checked
  against SEC's own rows for 13 filers (5,292 rows): the only differences are
  four figures Veeva's instance states rounded to the million, and six rows the
  parser left out.
- **Optional feeds cannot hold back the page.** Validation has three levels:
  an error is not publishable, a warning makes `--strict` refuse the deploy,
  and a notice is shown on its tab and nothing more. The catalyst calendars
  and the ETF holdings files -- several of them unofficial endpoints -- report
  notices; prices, index holdings and SEC filings report warnings.
- **CATALYSTS notices a renamed release.** The macro lane matches agency
  titles by pattern, so a renamed release would silently vanish. The key ones
  carry `expect_within_days`; none found that far ahead in the agency's own
  calendar is reported on the tab.
- **The repository lives in `market-recap.nosync`.** macOS syncs the Desktop
  to iCloud, which was leaving `dist 2`, `dist 3`… conflict copies; a folder
  ending in `.nosync` is not synced, and `market-recap` is a symlink to it.

- **ETF X-RAY matches holdings within a market.** A ticker only names the same
  company on one exchange: EFA's `DG` is Vinci in Paris and its `EL` is
  EssilorLuxottica, and matching by ticker alone priced them as Dollar General
  and Estée Lauder. Lines are keyed by ticker *and* market (an iShares line by
  its exchange, a Vanguard line in an international fund by a US ISIN), so
  only US listings are priced or joined to VALUATION. That leaves the
  international funds' look-through valuation blank: under 50% of a fund
  matched, a fund multiple describes the matched names, not the fund. Sectors
  for SSGA and Vanguard funds, which publish none, come from this build's GICS
  labels or another fund's file in the same market; what stays unclassified
  (mostly Canada in VEA, and Indian and Thai names in VWO) is shown as such.

- **The cache is compressed where it pays.** SEC company facts are 3–4 MB of
  JSON per filer, of which the DCF reads six line items; 121 of them filled
  472 MB. They are stored gzipped now — the raw document, so nothing about
  reproducibility changes — which takes the whole cache from 557 MB to 55 MB.
- **ETF net flow covers 27 of 34 funds.** It is the daily change in the
  issuer's published shares outstanding valued at that day's NAV, taken from
  State Street's or BlackRock's own history, so it is measured and reaches back
  to each fund's inception. Vanguard, Invesco and USCF publish no equivalent
  daily share history, and a sampled substitute is not offered: a vendor's
  `sharesOutstanding` for QQQ disagrees with its own assets-over-price by 67%,
  and day-over-day changes in a field that inconsistent would be fiction.
- **EFA and EEM flows go unknown when iShares stops updating.** Their published
  share count has sat unchanged for up to 127 sessions (every other fund moves
  within 19), so past 20 unchanged sessions a window lying wholly inside that
  stretch is shown as unknown, not as a measured zero; longer windows that
  contain real changes are kept.
- **Vanguard tiles are month-end and rounded.** VOO, VTI, VEA and VWO are one
  share class of larger funds; a vendor's total assets cover every class
  ($2.3tn for VTI). They are sized by Vanguard's own share-class net assets
  (`/characteristic`, month end, published to one decimal: VOO's "$1.0
  trillion" is good to about 5%). A tile falls back to the whole-fund figure,
  marked `*`, only if that call fails.
- Sector and index rows in the sector table are the buy-and-hold return of
  **today's members at today's published weights**, from dividend-adjusted
  closes. Over days and weeks that tracks the index to a few basis points;
  over YTD it runs ahead of the price index by roughly the dividends plus
  whatever joined the index after rallying (+1.7pp in September 2026).
- Change in NWC is the year-over-year move in current assets less current
  liabilities as filed. It does not strip out cash, so a company that banked
  cash shows a working-capital build. The DCF tab says so beside the row.
- FRED values are the current vintage and reflect later revisions. They are a
  release table, not a record of what was known on the day.
- Sector and sub-industry labels are current, not point-in-time. Members of
  the S&P 500 carry GICS labels; Nasdaq-100 members and watchlist names outside
  it are labelled from Yahoo's taxonomy mapped onto the same GICS sector names,
  so sub-industry wording differs between the two groups.
- Line items a filer did not tag are left blank and are editable in the model.
- FINANCIALS reads US-GAAP only. IFRS filers (ASML, CCEP, FER, TRI) and
  registrants with no annual report yet are listed on the tab as not
  extracted, with the reason. Fiscal years are named by their period end,
  which matches NVIDIA, Microsoft and Apple; retailers whose year ends in late
  January call it the year before, so the period end is printed beside every
  label.
- VALUATION's market cap is the close times a filed share count, so its
  weak point is the count. Three things are handled and one is checked: a
  cover page that lists one class of several (then the diluted count is used),
  a diluted count with a units error (Waters filed 98.2 *billion*), and a split
  after the last filing (Amphenol, Monster in 2026 — applied from the split
  record Yahoo returns with the prices). Every count is then compared with the
  company's SPY weight, by company rather than listing; a count more than 2.5x
  off is listed on the tab. Berkshire, Visa and a few other multi-class filers
  tag no complete count at all and have no market cap rather than a guessed one.
- The P/E history is point in time. Each quarter's TTM EPS is built only from
  filings made by the day that quarter was first reported, and applies from
  the next session; every part is put on today's share basis by the splits
  after its own filing date. Prices are split-adjusted but not
  dividend-adjusted (`Close`, not `Adj Close`): a multiple on dividend-adjusted
  prices understates every past P/E by the dividends paid since. An EPS with
  no successor for two quarters expires rather than being carried forward
  (Monster stopped tagging `EarningsPerShareDiluted` in 2011). The table's P/E
  (market cap / net income) and the history's (price / EPS) are computed
  independently and compared; the ~2% that disagree by more than 25% are
  listed on the tab — mergers and spin-offs that move the share count,
  preferred dividends, large minority interests.
- The P/E history, its percentile and the index and sector P/E lead with
  **operating** earnings; REPORTED is one click away. Reported EPS counts
  whatever sits below the operating line: Alphabet's 2026 Q2 carried $99bn of
  gains on its equity stakes (Anthropic, SpaceX) against $41bn of operating
  income, and on reported EPS it sat at the bottom of its own ten years.
  Operating TTM EPS is pre-tax income capped at operating income less
  interest paid, taxed at the median of the company's own trailing tax rates
  over twelve quarters (bounded 0–35%), less minority holders' share, over
  diluted shares — every input as filed by the day the quarter was reported.
  Only a net gain below the line is removed: some filers' operating line
  leaves costs out (Disney tags its segment total), so a net loss stays.
  Financials and utilities, whose ordinary earnings are partly below the line,
  and companies that tag no operating line (Merck, J&J, Deere), are on
  reported EPS less gains on equity securities after tax. A company with too
  little operating history to rank stays on reported. The table's own P/E
  column stays reported; `P/E operating` sits beside it.
- A 10-Q never replaces a 10-K's figure for a whole year: Comfort Systems'
  2026 Q1 10-Q tagged its Q1 2025 operating income as all of 2025, and as the
  later filing it had won. A diluted share count 20x away from the one the
  filing's own net income and EPS imply is a units error (Waters) and the
  implied count is used.
- TTM is last fiscal year + year to date − the same span a year earlier. A
  line the latest 10-Q did not tag (Alphabet's Q2 2026 dividends) is taken
  from the quarter before, at most one quarter stale, and starred on the row.
  EBIT falls back to pre-tax income + interest, and D&A to depreciation +
  intangible amortization, for filers that tag no combined line.
- SEC's ticker map points at a company's *current* registrant. After a
  holding-company reorganisation (Exxon, 2026) that CIK has no history, so the
  extraction follows the accession-number prefix to the predecessor CIK, and
  only when the entity name matches.

## The cross-listing premium, and why it ships with diagnostics

Comparing two listings of one company looks like subtraction and is not. Two
inputs decide whether the number means anything, and both fail quietly.

**The depositary ratio must come from the filing.** SK hynix's Nasdaq line
prices at roughly 7.2 Korean shares per ADS if you back it out of today's
quotes — and using that figure forces the premium to zero and draws a flat
line forever. The 424B4 says one ADS is one-tenth of a common share, and at
that ratio the premium is about +40%. The panel cites the filing on the page.

**The home market closes first.** Seoul shuts roughly fourteen hours before
New York, so a same-date comparison sets a fresh US close against a stale one.
On this pair the daily change in the premium correlates +0.55 with the US
leg's own return and −0.63 with the home leg's, its day-to-day swing (11.7pp)
exceeds the spread of the level itself (9.0pp), and its autocorrelation is
0.14. Those are the fingerprints of a timing artifact, not a moving
dislocation, so the tab says to read the level and not the change.

What the gap does make usable is the lead: the US return today correlates
+0.59 with the home market's *next* session against +0.30 with the same date.
That is an overnight indicator, and it is what a desk actually uses an ADR
premium for.

## Not investment advice

This is a research and teaching tool. The DCF tab in particular is a model you
fill in yourself; it does not produce a recommendation.
