# Index put/call ratios

Configuration: `positioning.index_put_call` in `config/dashboard.toml`.
The component is embedded in `positioning.json`, built after RISK. It makes
no new upstream requests and does not change Fear & Greed's Total P/C.

SPX + SPXW is put volume divided by call volume in Cboe's daily statistics
already cached by RISK. Open interest is not used. No ratio is emitted for
zero call volume. It includes all expiries, including 0DTE; no buyer/seller,
opening/closing or market-maker inference can be made from this aggregate.

The chart offers daily, five-session and 21-session arithmetic means of the
daily ratios, using `PERIOD_TRADING_DAYS`. These are not ratios of summed
multi-day volumes. Missing NYSE sessions stay null and invalidate a rolling
window; no forward fill or interpolation. The page's latest reading is for the
artifact's session, not a silently substituted older day. Dates, observed /
expected counts and gaps are visible. The artifact stores only daily window
values, observation counts and coverage. The page computes latest, median and
midrank percentile for the selected range (1M, 3M, 6M, YTD, 1Y or MAX) from
each series' own available values, so those statistics match the chart and
are not a common sample or a predictive probability. MAX is the configured
400-session display. Ranges are calendar-date looks ending on the artifact
session; smoothing uses the shared trading-day definitions and is calculated
before slicing.

NDX is **disabled**. OCC's public query describes a rolling 24-month
availability, but its general terms restrict automated access and
incorporation into other services. Public availability is not permission to
republish. This branch therefore has no OCC crawler. While `publish_allowed`
is not exactly `true` or `permission_reference` is blank, the artifact lists
NDX under `disabled` with its reason: no series row, no source record, and the
CSV is not opened. The page shows that reason in the method fold. Before
enabling NDX, obtain permission covering this site's display and the source
dataset:

- Set `publish_allowed = true` and a nonempty `permission_reference`.
- Supply an authorized CSV at the configured private path, with one daily
  aggregate per underlying: `date,underlying,put_volume,call_volume`.
- Dates must be ISO dates; underlying must match the configured identifier.
  Aggregate all roots/accounts/exchanges stated in `scope`, not just NDX's
  standard monthly root. Do not add total rows to their component rows.
- Duplicate dates and invalid volumes fail the import. Future sessions are
  excluded. Private CSVs are never copied into the static site.

References:

- [Cboe daily statistics](https://www.cboe.com/us/options/market_statistics/daily/)
- [OCC volume query](https://www.theocc.com/market-data/market-data-reports/volume-and-open-interest/volume-query)
- [OCC batch documentation](https://www.theocc.com/market-data/market-data-reports/other-market-data-info/batch-processing/volume-query-batch-processing)
- [OCC terms](https://www.theocc.com/specialpages/legal/terms-and-conditions)

The local preview can be built from existing artifacts/cache without
refreshing prices, SEC filings or news:
`python scripts/preview_index_put_call.py`, then `make site`.
It retains the original artifact's date and does not claim a fresh market run.
