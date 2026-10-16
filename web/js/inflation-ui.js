// Shared CPI/PPI weight encoding. Length, not red/green, represents importance.
import { el, num, table, DASH } from './fmt.js';
import { finite } from './cpi-model.js';

export function weightWidth(value) {
  return finite(value) && value >= 0 && value <= 100 ? value : null;
}

export function weightCell(value, month) {
  const width = weightWidth(value);
  return el('td', { class: 'inflation-weight-cell', title: `Official relative importance · ${month || 'date unavailable'} · share of total basket, not contribution` }, [
    el('div', { class: 'inflation-weight' }, [
      el('span', { class: 'inflation-weight-value', text: width === null ? DASH : `${num(width, 2)}%` }),
      el('span', { class: 'inflation-weight-track', 'aria-hidden': 'true' }, [
        width === null ? null : el('span', { class: 'inflation-weight-fill', style: `width:${width}%` }),
      ]),
    ]),
  ]);
}

// One short visible caveat per card; the rest of its method notes sit behind
// one fold. Nothing is dropped, only moved out of the way of the numbers.
export function caveats(visible, method) {
  return [el('div', { class: 'note-text', text: visible }),
    el('details', { class: 'sx-fold' }, [
      el('summary', { text: 'Method & caveats' }),
      el('div', { class: 'note-text', text: method }),
    ])];
}

// Consensus is kept in the record's calendar list. Records written before that
// keep it on each comparison, so the list is read first and the comparison is
// the fallback. Both are retrospective calendar figures, not frozen forecasts.
export function recordConsensus(version, comparison) {
  const entry = (version.calendar || []).find((c) => c.key === comparison.key);
  return entry ? entry.consensus ?? null : comparison.consensus ?? null;
}

export function recordCalendarFetched(version, comparison) {
  const entry = (version.calendar || []).find((c) => c.key === comparison.key);
  return entry?.consensus_retrieved_at || version.consensus_retrieved_at || null;
}

export function releaseHistory(data) {
  const records = data.release_ledger?.records || [];
  const current = records.filter((r) => r.month === data.month);
  const rate = (v) => finite(v) ? `${num(v, 1)}%` : DASH;
  const rows = current.flatMap((version, i) => (version.values?.comparisons || []).map((r) => el('tr', {}, [
    el('td', { text: `V${i + 1} · ${version.observed_at}` }),
    el('td', { text: `${r.label} · ${r.basis}` }),
    el('td', { text: rate(r.actual) }), el('td', { text: rate(recordConsensus(version, r)) }),
    el('td', { text: recordCalendarFetched(version, r) || DASH }),
  ])));
  const revisions = (data.revisions || []).filter((r) => finite(r.first_observed_mom));
  return el('details', { class: 'sx-fold cpi-detail inflation-release-history' }, [
    el('summary', { text: `OBSERVED RELEASE VERSIONS · ${current.length} FOR ${data.month}` }),
    el('div', { class: 'note-text', text: records.length
      ? `Recording since ${records[0].observed_at}. First observed is not necessarily first published. Changed parsed release/calendar values create a new version; unchanged checks do not. Earlier months are not backfilled. Consensus remains retrospective, not verified pre-release. FRED trend revisions are not archived here.`
      : 'No observed release versions have been recorded yet.' }),
    data.release_ledger_note ? el('div', { class: 'note-text dim', text: data.release_ledger_note }) : null,
    rows.length ? table(['FIRST OBSERVED · UTC', 'MEASURE', 'BLS ACTUAL', 'CALENDAR CONSENSUS', 'CALENDAR FETCHED'], rows) : null,
    revisions.length ? table(['PRIOR MONTH', 'MEASURE', 'FIRST OBSERVED MoM', 'LAST OBSERVED MoM', 'NOW REPORTED MoM', 'Δ SINCE FIRST · pp'],
      revisions.map((r) => el('tr', {}, [el('td', { text: r.month }), el('td', { text: r.label }),
        el('td', { text: rate(r.first_observed_mom) }), el('td', { text: rate(r.last_observed_mom) }),
        el('td', { text: rate(r.reported_prior_mom) }),
        el('td', { text: finite(r.revision_since_first_pp) ? num(r.revision_since_first_pp, 2) : DASH }),
      ]))) : el('div', { class: 'note-text', text: 'Prior-month revision comparison unavailable: no matching observation captured before this release. This is not evidence of zero revisions.' }),
  ]);
}
