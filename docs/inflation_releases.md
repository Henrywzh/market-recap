# Observed CPI / PPI release versions

`macro.json` keeps a `release_ledger` inside each CPI/PPI section and marks the
top-level contract with `release_ledger_schema_version = 1`. A ledger record
contains its reference month, official publication timestamp, first-observed
and last-checked times, source URL/body hash and original source-file retrieval
time, calendar retrieval time, parsed official components, weights and release
comparisons, plus a digest of those parsed values. The capture time is when
this build recorded them, not when BLS first published them.

The digest covers BLS values only: `weight_month`, the components, and each
comparison's `key, label, basis, actual, previous_mom_bls`. The calendar's
consensus and "previous" sit beside the version in the record's `calendar`
list, with `consensus_retrieved_at` as their fetch time. Records carry
`digest_version` (missing means 1, the older shape whose digest also covered
consensus; 2 is the current one) and each is validated by its own version, so
older records still validate and are never rewritten.

An unchanged check updates `last_checked_at`, and refreshes `calendar` and
`consensus_retrieved_at` in place on version-2 records (a check that returns no
consensus does not blank one already stored). Changed parsed official values
append a version; earlier records never change. A calendar change alone does not
create a version. A body-format change alone does not create an economic
version. `record_calendar` reads consensus from either shape (`calendar` for
version 2, `values.comparisons` for version 1). Source hashes refer to the
body used when that version was first observed, not every later HTTP response.
An unavailable release carries its entire previous ledger. There is no older-
month backfill, first-print claim, pre-release survey claim or FRED history
vintage ledger. Calendar disappearance/recovery is an observation change, not
proof that the original survey changed. No prediction model is added.

Recording never takes the MACRO build down. If extending one kind's ledger
fails (clock or release moved backwards, digest mismatch), that kind keeps its
data, carries the previous ledger unchanged when it validates (otherwise
omits it), sets `revisions` to `[]` and adds `release_ledger_note` with the
reason. `cpi.build` and `ppi.build` likewise turn any error into
`{"status": "unavailable", "reason": ...}` plus an error source record.

Prior-month MoM revisions compare this release's official `previous_mom` with
the earliest/latest stored observation for that month **captured before this
release's publication instant**. Comparison uses timezone-aware instants, not
same-date matching. No matching earlier observation leaves the delta null,
not zero. Even the earliest stored value is not necessarily the first print.
This covers the previous-month fields parsed from each new release, not every
historical month affected by annual seasonal-adjustment revisions.

BLS latest-release discovery still occurs on every build. Dated release bodies
now use the existing 12-hour `macro_series` TTL rather than the one-year article
cache so corrections can be observed. `retrieved_at` is the cached body's actual
file-fetch time (including stale fallback), not the time a build read it. There
is no release-window collector, new schedule or promise to observe every
intervening revision. Source outage and normal FRED lags stay visible.

## Durability

Local builds read the previous local `macro.json`; both preview helpers run the
same merge and preserve unrelated data and session dates. They use atomic
replacement and refuse concurrent changes. With `INFLATION_PUBLISHED_STATE=1`,
normal CI reads the published macro artifact through the project HTTP adapter,
checking the manifest's generation before and after the read. It ignores the
local artifact/TTL cache as a state authority. Missing/corrupt state, a marked
ledger that disappears, backward source/observation time, or a deployment race
makes `inflation_state.load_previous` raise. `macro.build` catches that, logs a
`cpi_fred_release_state` source record (status `partial`, optional under
`validate.py`) and carries no history for that build: a failed MACRO build
publishes no `macro.json`, so a raising restore would fail every later build
too, and commodities and PCE must not depend on it. The cost is that a
successful build after a failed restore starts the ledgers again from its own
observation; the earlier published artifact is the recovery evidence. A legacy
macro without the schema marker/ledgers is the explicit first-run bootstrap.

History is published with the macro artifact and included in the existing
90-day Actions artifact archive. CI must not deploy a failed macro build.
Failed/unpublished-run observations are not incorporated into the next published
ledger automatically; that run's archived artifact is the recovery evidence.
This is a published observation history, not an exhaustive collection service.
