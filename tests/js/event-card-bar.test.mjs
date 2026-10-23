// THE BAR on the event card: the usual beat and the EPS that clears it, what
// clearing a usual beat was worth across names, the sub-industry's profile,
// and the reason where a sector gets no EPS bar.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { barStats, barTag } from '../../web/js/event-card.js';

const BAR = {
  usual_beat_pct: 6.1, usual_beat_reports: 7, eps_at_usual_beat: 1.96,
  above_usual: { n: 905, up_pct: 60.0, median: 1.43 }, at_or_below_usual: { n: 615, up_pct: 42.0, median: -0.7 },
  industry: 'Semiconductors',
  industry_profile: { reports: 109, names: 15, beats_fell_pct: 59.0, median_beat: -1.32, median_miss: -4.79, median_surprise: 6.22, since: '2024-02-27' },
};

test('the bar reads the usual beat with its EPS, the across-names split, and the sub-industry', () => {
  const rows = barStats(BAR);
  assert.deepEqual(rows.map((r) => r[0]), ['THE BAR · USUAL BEAT', 'BEATS ABOVE THE USUAL BEAT', 'SEMICONDUCTORS']);
  assert.equal(rows[0][1], '+6.1%');
  assert.match(rows[0][2], /^median EPS surprise of its last 7 reports · EPS 1\.96 matches it$/);
  assert.match(barStats({ ...BAR, usual_beat_pct: -2.7 })[0][2], /^it usually reports below consensus: /);
  assert.equal(rows[1][1], '60% rose');
  assert.match(rows[1][2], /against 42% at or below it/);
  assert.equal(rows[2][1], '59% of beats fell');
  assert.match(rows[2][2], /median beat −1\.3% · median miss −4\.8%/);
  assert.equal(rows[2][3], 'down');
  for (const r of rows) assert.doesNotMatch(r.join(' '), /NaN|undefined|null/);
});

test('without three earlier reports the usual beat is a dash, and a missing profile is left out', () => {
  const rows = barStats({ usual_beat_pct: null, usual_beat_reports: 1, above_usual: null, at_or_below_usual: null, industry_profile: null });
  assert.equal(rows.length, 1);
  assert.equal(rows[0][1], '—');
  assert.deepEqual(barStats(null), []);
});

test('a REIT or utility gets the reason, not a bar', () => {
  const rows = barStats({ no_eps_bar: 'Real Estate' });
  assert.equal(rows.length, 1);
  assert.match(rows[0][2], /^Real Estate: .*no EPS bar/);
});

test('the compact card tags the usual beat, or says there is no EPS bar', () => {
  const saved = globalThis.document;
  globalThis.document = { createElement: (t) => ({ tagName: t, children: [], append() {}, setAttribute() {}, className: '', textContent: '' }), createTextNode: (x) => ({ text: x }) };
  try {
    assert.equal(barTag(BAR).textContent, 'BAR +6.1%');
    assert.equal(barTag({ no_eps_bar: 'Utilities' }).textContent, 'NO EPS BAR');
    assert.equal(barTag({ usual_beat_pct: null }), null);
  } finally {
    if (saved === undefined) delete globalThis.document; else globalThis.document = saved;
  }
});
