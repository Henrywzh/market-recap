# Descriptive risk context preview

Branch trial, 2026-10-26. RISK opens on own-asset price pressure, fixed-roster
sector participation and grouped market context. It does not add a prediction
model, trade signal, calibrated probability or combined vote score.

## Asset definitions

`risk.context` in `config/dashboard.toml` owns the assets, labels and measurement
choices. SPX uses the S&P price index; QQQ and SOXX are explicitly labelled ETF
proxies, and IEF is a 7–10 year Treasury fund. Dividend-adjusted ETF closes are
not the SOX/NDX price indexes used in some research. IEF price weakness describes
bond price pressure, not an equity risk prediction. Do not transplant the research
models' catch rates or alert statistics onto these proxy series.

Drawdown is close / trailing 3M highest close − 1, where 3M comes from the shared
period definitions. One monthly sigma is the standard deviation of the previous
1Y daily log returns, excluding the current return, times sqrt(1M sessions).
Scaled drawdown is drawdown magnitude / that sigma. The scale updates each day.
References at 1 and 1.7 sigma are descriptive conventions, not event probabilities.
Amber/red distinguish the magnitude of observed pressure. Missing or dated asset
readings do not receive a current pressure color. Realized volatility uses 20
sessions, annualized; its rank is relative to the trailing 1Y window.

## Participation and shared context

Participation reuses `risk.stress.sector_roster`: nine fixed sector ETFs, omitting
communication services and real estate. At each close, compare every fund with
its own 20/50/200-session average. All nine must have both inputs; any missing
member withholds the full-roster aggregate. Do not reduce the denominator or
interpret unknown as below-average. Display 20D and 200D together; 50D is optional.
Weekly changes use the shared 1W trading-session definition. This proxy is shared
context and stays unchanged when the asset selector changes. It is not index
constituent breadth, a point-in-time constituent universe, or a bottom signal.

Existing tiles are grouped into equity volatility, credit, rates/funding, macro
background and options/co-movement. Their values, dates and weekly changes keep
their original source definitions. Amber indicates an existing configured
reference breach. Families are not added together. The site's seven-component
Fear & Greed stays distinct from the four-component research rebuild.

S&P 500 constituent breadth is now the main participation card; sector ETF
participation is a folded supplement. Constituent breadth uses the complete current
primary roster from the configured index, with equal-count percentages among
eligible members. Each window shows above / eligible and eligible / roster;
missing closes and incomplete windows are excluded explicitly. Zero eligible
members gives a missing percentage. Historical current-roster reconstructions
contain survivorship/membership bias and are not point-in-time breadth.

One RISK-wide range defaults to YTD, anchored to the artifact session, and drives
asset, breadth, liquidity, valuation, sentiment, section/library and stress-history
charts. Short sources stay incomplete; changing range does not change latest
card values or source dates. Blackout projections remain separately dashed beyond
the session; the volatility term-structure snapshot is not a history range.
The RATES view's reused history renderer retains independent controls.

CFTC leveraged-fund futures are net long minus short as a percentage of open
interest, not whole-fund equity exposure. ES is S&P 500; NQ is Nasdaq-100.
Short interest is outstanding short positions; DTC is short shares divided by
average daily volume (shown as the cross-company median). Neither high DTC nor
negative futures exposure is automatically bullish. Insider clusters retain their
coverage-through date, which may be much older than the artifact session.

READ THIS FIRST, Fear & Greed and What Changed This Week remain on the main view;
the original 9-vote stress count and full library stay folded.
No research-selected per-asset 8/8 or 2/2 count is imported into the new header.

## Build and preview

The risk builder assembles `risk.context` from the build's existing prices only;
it makes no extra HTTP request. All histories stop at the risk artifact's date.
Trailing gaps preserve an asset's actual last date; internal gaps are not filled.

To augment the local cached risk artifact without fetching or changing its date:

```sh
PYTHONPATH=src .venv/bin/python scripts/preview_risk_context.py
make site PYTHON=.venv/bin/python
.venv/bin/python scripts/serve.py --port 4317
```

This local preview does not refresh the other artifacts or alter the manifest's
session/generation time. The broader research remains exploratory; see
`research/triage_validation_v1/README.md` and `research/regimes_v1/README.md`.
