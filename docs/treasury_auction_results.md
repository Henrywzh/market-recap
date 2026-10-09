# Treasury auction results

The existing `sources/treasury.py` owns this extension; the announcement
calendar is unchanged. No additional source implementation is imported from
a sibling, and the default dashboard build does not make this new fetch.

```bash
PYTHONPATH=src .venv/bin/python -m market_recap.cli auction-results --days 90
PYTHONPATH=src .venv/bin/python -m market_recap.cli auction-results --query
```

The explicit collector reads the official Fiscal Data `auctions_query`
endpoint, with a 1..365 day window, full pagination and source fields retained.
It archives hashes/request URLs and result snapshots under ignored
`data/private/treasury_auctions/runs/<run>/`; `latest.json` is replaced only
after validation. A failed attempt is separate and does not erase last-good
data. `--query` is offline JSON.

Only completed Note/Bond/TIPS/FRN coupon auctions are retained. CUSIP plus
auction date identifies an event; reopenings remain separate. Original
maturity, type and reopening define comparison groups. Null API strings
remain null; null FRN yield is legitimate. Bidder shares divide by
competitive accepted and the three allocations must reconcile. Indirect
bidders are not identical to foreign investors. `record_date`/issue date are
not release timestamps, and historical rows are current-vintage observations.
A yield tail needs the pre-result when-issued yield and stays null here.

Result pagination must explicitly declare its page count; absence is not
assumed to be one page. Bid-to-cover must be positive, and row observation
timestamps are taken after receipt, not before the network request.
Immutable run snapshots contain only that request's observations. The latest
index retains earlier auctions, with their original timestamps, when a
narrower window is requested. Missing previously captured auctions inside
the requested overlap fail the refresh rather than silently shortening
coverage. `captured_row_count` and `stored_coverage` distinguish this fetch
from retained history. These checks cannot prove complete first-fetch
coverage against an unavailable earlier vintage.

`quantamental-lab` references this local JSON through its institutional query
CLI. It does not implement a second Treasury collector. This addition does
not publish the snapshots, deploy the site or add an anchor/risk score.
