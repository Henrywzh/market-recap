// SCENARIO WATCH: the model's helpers on the spec's example figures, and the
// page rendered from a fixture under node against a small fake DOM.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as M from '../../web/js/watch-model.js';
import renderWatch from '../../web/js/tabs/watch.js';

const trigger = {
  label: 'USD/JPY 20-session change', series: 'usdjpy', measure: 'change_pct', sessions: 20, op: 'below',
  threshold: -5, near: -3, unit: '%', value: 0.4, as_of: '2026-10-21', met: false, is_near: false,
  history: [['2025-10-20', 1.2], ['2025-10-21', 0.9]],
};

const kill = {
  label: 'USD/JPY level', series: 'usdjpy', measure: 'level', sessions: 0, op: 'above', threshold: 165, near: null,
  unit: '', value: 158.1, as_of: '2026-10-21', met: false, is_near: false, history: [],
};

const cpi = {
  kind: 'release', key: 'cpi', label: 'CPI m/m', unit: 'pp', date: '2026-11-10', time: '08:30',
  forecast: 0.3, previous: 0.4, band: 0.05, band_basis: 'any miss of the published tick',
  market: { source: 'Kalshi', median: 0.235, low: 0.057, high: 0.432, open_interest: 423838, p_above: 0.18, p_inline: 0.47, p_below: 0.35 },
  branches: {
    above: { n: 34, dY2: 6.3, dY2_se: 1.4, SPY: -0.16, SPY_se: 0.23 },
    inline: { n: 44, dY2: -0.8, dY2_se: 0.8, SPY: 0.17, SPY_se: 0.09 },
    below: { n: 43, dY2: -3.3, dY2_se: 1.1, SPY: 0.14, SPY_se: 0.20 },
  },
  latest: { date: '2026-10-15', actual: 0.3, forecast: 0.3, cls: 'inline', dY2: -1.2, SPY: 0.4 },
};

const fomc = {
  kind: 'fomc', key: 'fomc', label: 'FOMC decision', date: '2026-10-28',
  market: { source: 'Kalshi', outcomes: [{ label: 'Fed maintains rate', change_bp: 0, probability: 0.865 }, { label: 'Hike 25bps', change_bp: 25, probability: 0.135 }] },
  branches: { bp: 5, hawkish: { n: 20, SPY: -0.6 }, dovish: { n: 22, SPY: 0.7 } },
};

const yen = {
  key: 'yen_carry', name: 'Yen carry unwind', thesis: 'A fast yen rally forces carry trades funded in yen to close.',
  added: '2026-10-21', horizon: '2027-03-31', match: 'any', state: 'quiet', previous_state: 'quiet', changed: false,
  since: '2026-10-21', first_triggered: null, triggered_sessions: 0, killed_on: null, outcome: null,
  episodes: { count: 3, since: '2016-10-21', last: { start: '2024-08-02', end: '2024-08-09', sessions: 6 } },
  triggers: [trigger], kill: [kill],
};

const oil = {
  key: 'oil_shock', name: 'Oil shock', thesis: 'A sharp crude rally squeezes margins and bond sentiment.',
  added: '2026-10-01', horizon: '2026-12-31', match: 'all', state: 'triggered', previous_state: 'near', changed: true,
  since: '2026-10-20', first_triggered: '2026-10-20', triggered_sessions: 2, killed_on: null, outcome: null,
  episodes: { count: 2, since: '2016-10-21', last: { start: '2022-03-07', end: '2022-03-11', sessions: 5 } },
  triggers: [{
    label: 'Brent 10-session change', series: 'brent', measure: 'change_pct', sessions: 10, op: 'above', threshold: 8, near: 5,
    unit: '%', value: 9.1, as_of: '2026-10-21', met: true, is_near: true,
    history: [['2026-10-19', 6.2], ['2026-10-20', 8.4], ['2026-10-21', 9.1]],
  }],
  kill: [],
};

const fixture = () => ({
  as_of: '2026-10-21',
  settings: { event_days: 14, history_sessions: 260 },
  events: [fomc, cpi].map((e) => JSON.parse(JSON.stringify(e))),
  scenarios: [yen, oil].map((s) => JSON.parse(JSON.stringify(s))),
  notes: ['Probabilities are market prices.', 'Branch figures come from the SCENARIOS panel.'],
});

// --- a small fake DOM, as the TODAY tests use ----------------------------------

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.style = {};
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  get isConnected() { return true; }
}

const fakeDocument = () => ({
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
});

// The text of a node and everything under it, as a reader would see it.
function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

// Runs a synchronous render with a document and no charting library: the charts
// return without drawing, and nothing outlives the test.
function withBrowser(run) {
  const saved = { document: globalThis.document, window: globalThis.window };
  globalThis.document = fakeDocument();
  globalThis.window = {};
  try {
    return run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

// --- the model -----------------------------------------------------------------

test('a state has its label, and an unknown or missing state reads as no data', () => {
  assert.equal(M.stateLabel('triggered'), 'TRIGGERED');
  assert.equal(M.stateLabel('near'), 'NEAR');
  assert.equal(M.stateLabel('quiet'), 'QUIET');
  assert.equal(M.stateLabel('killed'), 'KILLED');
  assert.equal(M.stateLabel('expired'), 'EXPIRED');
  assert.equal(M.stateLabel('constructor'), 'NO DATA');
  assert.equal(M.stateLabel(null), 'NO DATA');
});

test('a trigger reads as its value now, where it fires, and its near band', () => {
  assert.equal(M.triggerText(trigger), 'USD/JPY 20-session change +0.4% · triggers at ≤ −5% (near ≤ −3%)');
  assert.equal(M.triggerText(kill, 'kills'), 'USD/JPY level 158.1 · kills at ≥ 165');
  assert.equal(M.triggerText({ ...trigger, value: null, near: null }), 'USD/JPY 20-session change — · triggers at ≤ −5%');
  assert.equal(M.triggerText({ ...trigger, value: -2.25 }), 'USD/JPY 20-session change −2.25% · triggers at ≤ −5% (near ≤ −3%)');
  assert.equal(M.triggerText(null), null);
});

test('an episode count names its years and the last run; no episodes says never', () => {
  assert.equal(M.episodeText(yen.episodes), '3 episodes since 2016 · last 2024-08-02 to 2024-08-09');
  assert.equal(M.episodeText({ count: 0, since: '2016-10-21', last: null }), 'never since 2016');
  assert.equal(M.episodeText({ count: 1, since: '2016-10-21', last: { start: '2020-03-02', end: '2020-03-02' } }), '1 episode since 2016 · last 2020-03-02');
  assert.equal(M.episodeText({ count: 2, since: null, last: null }), '2 episodes');
  assert.equal(M.episodeText(null), null);
  assert.equal(M.episodeText({ count: null }), null);
});

test('the match and the change since the last build read in words', () => {
  assert.equal(M.matchText(oil), 'every trigger must hold');
  assert.equal(M.matchText(yen), 'any one trigger is enough');
  assert.equal(M.matchText({}), null);
  assert.equal(M.changedText(oil), 'CHANGED TODAY (was NEAR)');
  assert.equal(M.changedText({ changed: true, previous_state: null }), 'CHANGED TODAY');
  assert.equal(M.changedText(yen), null);
  assert.equal(M.changedText(null), null);
});

test('an expired or killed scenario says how it ended, and a live one has no outcome', () => {
  assert.equal(M.outcomeText(yen), null);
  assert.equal(M.outcomeText({ outcome: 'killed', killed_on: '2026-11-02' }), 'Killed on 2026-11-02');
  assert.equal(M.outcomeText({ outcome: 'killed', killed_on: null }), 'Killed');
  assert.equal(M.outcomeText({ outcome: 'not triggered', horizon: '2027-03-31', first_triggered: null }), 'Expired 2027-03-31: not triggered');
  assert.equal(M.outcomeText({ outcome: 'triggered', horizon: '2027-03-31', first_triggered: '2026-12-02' }), 'Expired 2027-03-31: triggered · first triggered 2026-12-02');
});

test('a history becomes aligned dates and values, with a missing value as null', () => {
  assert.deepEqual(M.historySeries(trigger), { dates: ['2025-10-20', '2025-10-21'], values: [1.2, 0.9] });
  assert.deepEqual(M.historySeries({ history: [['2026-01-02', NaN], ['2026-01-03', null]] }), { dates: ['2026-01-02', '2026-01-03'], values: [null, null] });
  assert.deepEqual(M.historySeries({ history: null }), { dates: [], values: [] });
});

test('the chart axis holds every value and every threshold, and is absent with none', () => {
  const b = M.axisBounds([1.2, 0.9], [-5, -3]);
  assert.ok(b.min < -5 && b.max > 1.2);
  assert.deepEqual(M.axisBounds([null], [null]), null);
  assert.ok(M.axisBounds([2], []).max > 2);
});

test('figures print a true minus sign, a plus only on a move, and the em dash when absent', () => {
  assert.equal(M.figure(0.4, 1, '%'), '+0.4%');
  assert.equal(M.figure(-1.2, 1, ' bp'), '−1.2 bp');
  assert.equal(M.figure(0, 1, '%'), '0.0%');
  assert.equal(M.figure(-0.04, 1, '%'), '0.0%');
  assert.equal(M.figure(null), '—');
  assert.equal(M.figure(NaN), '—');
  assert.equal(M.level(0.3, 'pp'), '0.3%');
  assert.equal(M.level(0.235, 'pp'), '0.235%');
  assert.equal(M.level(197, 'k'), '197k');
  assert.equal(M.level(158.1, ''), '158.1');
  assert.equal(M.level(undefined, 'pp'), '—');
});

test('a probability is a percentage, rounded to one decimal at most', () => {
  assert.equal(M.probText(0.18), '18%');
  assert.equal(M.probText(0.135), '13.5%');
  assert.equal(M.probText(0.865), '86.5%');
  assert.equal(M.probText(0.235), '23.5%');
  assert.equal(M.probText(null), '—');
});

test('a measured mean carries its standard error; without one the ± drops', () => {
  assert.equal(M.measureText(6.3, 1.4, 1, ' bp'), '+6.3 bp ±1.4');
  assert.equal(M.measureText(-0.16, 0.23, 2, '%'), '−0.16% ±0.23');
  assert.equal(M.measureText(-0.6, null, 2, '%'), '−0.60%');
  assert.equal(M.measureText(null, 1, 1, ' bp'), '—');
});

test('a measured figure is detected at |t| of 2 or more, and t needs a non-zero error', () => {
  assert.equal(M.measured(6.3, 1.4).detected, true);
  assert.equal(M.measured(-0.8, 0.8).detected, false);
  assert.equal(M.measured(-3.3, 1.1).detected, true);
  assert.equal(M.measured(0.17, 0.09).detected, false);      // t 1.9
  assert.equal(M.measured(1, 0).t, null);
  assert.equal(M.measured(1, 0).detected, false);
  assert.deepEqual(M.measured(null, 1), { mean: null, se: 1, t: null, detected: false });
});

test('a FOMC change reads as no change or in basis points', () => {
  assert.equal(M.changeText(0), 'no change');
  assert.equal(M.changeText(25), '+25 bp');
  assert.equal(M.changeText(-25), '−25 bp');
  assert.equal(M.changeText(null), '—');
});

test('the release stats are the consensus, the prior, and the Kalshi median and range', () => {
  assert.deepEqual(M.releaseStats(cpi), {
    forecast: '0.3%', previous: '0.4%', median: '0.24%', range: '0.06% to 0.43%', openInterest: '423,838',
  });
  const noMarket = M.releaseStats({ ...cpi, market: null, forecast: null });
  assert.deepEqual(noMarket, { forecast: '—', previous: '0.4%', median: '—', range: null, openInterest: null });
});

test('the release branches are above, in line, below, with their probability and past moves', () => {
  const rows = M.branchRows(cpi);
  assert.deepEqual(rows.map((r) => r.cls), ['above', 'inline', 'below']);
  assert.deepEqual(rows.map((r) => r.label), ['ABOVE FORECAST', 'IN LINE', 'BELOW FORECAST']);
  assert.deepEqual(rows.map((r) => r.probability), [0.18, 0.47, 0.35]);
  assert.deepEqual(rows.map((r) => r.n), [34, 44, 43]);
  assert.equal(rows[0].dY2.detected, true);
  assert.equal(rows[1].dY2.detected, false);
  assert.equal(rows[2].SPY.detected, false);
  assert.equal(rows[0].SPY.se, 0.23);
});

test('a branch with too few releases has its count and no figure, and a missing market has no probability', () => {
  const rows = M.branchRows({ ...cpi, market: null, branches: { above: { n: 2, dY2: null, dY2_se: null, SPY: null, SPY_se: null } } });
  assert.deepEqual(rows[0], { cls: 'above', label: 'ABOVE FORECAST', probability: null, n: 2, dY2: { mean: null, se: null, t: null, detected: false }, SPY: { mean: null, se: null, t: null, detected: false } });
  assert.equal(rows[2].n, null);
  assert.equal(rows[2].probability, null);
  assert.deepEqual(M.branchRows(null), []);
});

test('the last release reads as its actual against the forecast, the branch, and the day\'s moves', () => {
  assert.equal(M.lastReleaseText(cpi), 'Last release 2026-10-15: actual 0.3% vs forecast 0.3% — IN LINE · 2Y −1.2 bp, SPY +0.40%');
  assert.equal(M.lastReleaseText({ ...cpi, latest: null }), null);
  assert.equal(M.lastReleaseText({ ...cpi, latest: { date: '2026-10-15', actual: 0.5, forecast: 0.3, cls: 'above', dY2: null, SPY: null } }),
    'Last release 2026-10-15: actual 0.5% vs forecast 0.3% — ABOVE FORECAST');
});

test('the FOMC rows are the outcomes, then the hawkish and dovish branches with their bp definition', () => {
  const rows = M.fomcRows(fomc);
  assert.deepEqual(rows.map((r) => r.kind), ['market', 'market', 'hawkish', 'dovish']);
  assert.deepEqual(rows[1], { kind: 'market', label: 'Hike 25bps', changeBp: 25, probability: 0.135 });
  assert.deepEqual(rows[2], { kind: 'hawkish', label: '2Y up ≥ 5 bp that day', bp: 5, n: 20, SPY: -0.6 });
  assert.deepEqual(rows[3], { kind: 'dovish', label: '2Y down ≥ 5 bp that day', bp: 5, n: 22, SPY: 0.7 });
  assert.deepEqual(M.fomcRows(null), []);
  assert.deepEqual(M.fomcRows({ kind: 'fomc', market: null, branches: null }).map((r) => r.n), [null, null]);
});

test('the scheduled events sort by date, then time, and the input is left alone', () => {
  const late = { ...cpi, date: '2026-11-12', time: '08:30' };
  const early = { ...cpi, date: '2026-11-10', time: '14:00' };
  const input = [late, fomc, early];
  const sorted = M.sortEvents(input);
  assert.deepEqual(sorted.map((e) => e.date), ['2026-10-28', '2026-11-10', '2026-11-12']);
  assert.equal(input[0], late);
  assert.deepEqual(M.sortEvents(null), []);
});

test('the scenarios sort triggered, near, quiet, killed, expired, then by name', () => {
  const list = [
    { name: 'Zed', state: 'quiet' }, { name: 'Beta', state: 'expired' }, { name: 'Alpha', state: 'quiet' },
    { name: 'Gamma', state: 'near' }, { name: 'Delta', state: 'killed' }, { name: 'Omega', state: 'triggered' },
    { name: 'Bogus', state: 'nonsense' },
  ];
  const sorted = M.sortScenarios(list);
  assert.deepEqual(sorted.map((s) => s.name), ['Omega', 'Gamma', 'Alpha', 'Zed', 'Delta', 'Beta', 'Bogus']);
  assert.equal(list[0].name, 'Zed');
  assert.deepEqual(M.sortScenarios(undefined), []);
});

test('the header counts the triggered and near conditions', () => {
  assert.deepEqual(M.countStates([{ state: 'triggered' }, { state: 'near' }, { state: 'quiet' }, { state: 'triggered' }]), { triggered: 2, near: 1 });
  assert.deepEqual(M.countStates(null), { triggered: 0, near: 0 });
});

test('CLASS_LABELS names the three branches of a release', () => {
  assert.deepEqual(M.CLASS_LABELS, { above: 'ABOVE FORECAST', inline: 'IN LINE', below: 'BELOW FORECAST' });
});

test('the page renders from the fixture: the strip, both sections, the chips, the change tag and the notes', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderWatch(root, fixture(), null, {});
  const text = textOf(root);
  assert.ok(text.includes('AS OF'), 'the strip has the as-of date');
  assert.ok(text.includes('2026-10-21'));
  assert.ok(text.includes('Scheduled events are automatic'), 'the one-sentence intro');
  assert.ok(text.includes('SCHEDULED') && text.includes('NEXT 14 DAYS'));
  assert.ok(text.includes('CPI M/M') && text.includes('FOMC DECISION'));
  assert.ok(text.includes('Tue 10 Nov 08:30'), 'the release shows its date and time');
  assert.ok(text.includes('Last release 2026-10-15'));
  assert.ok(text.includes('ABOVE FORECAST') && text.includes('BELOW FORECAST'));
  assert.ok(text.includes('SPY mean −0.60%') && text.includes('SPY mean +0.70%'));
  assert.ok(text.includes('CONDITIONS') && text.includes('YOUR SCENARIOS'));
  assert.ok(text.includes('Oil shock') && text.includes('Yen carry unwind'));
  assert.ok(text.includes('TRIGGERED') && text.includes('QUIET'));
  assert.ok(text.includes('CHANGED TODAY (was NEAR)'));
  assert.ok(text.includes('Brent 10-session change +9.1%'));
  assert.ok(text.includes('Kill: USD/JPY level 158.1 · kills at ≥ 165'));
  assert.ok(text.includes('3 episodes since 2016 · last 2024-08-02 to 2024-08-09'));
  assert.ok(text.includes('ⓘ NOTES') && text.includes('Probabilities are market prices.'));
  assert.ok(text.indexOf('Oil shock') < text.indexOf('Yen carry unwind'), 'the triggered condition leads');
}));

test('a release shows its branches with the market probability and the detected figures undimmed', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderWatch(root, { ...fixture(), scenarios: [] }, null, {});
  const cells = [];
  const walk = (node) => {
    if (node.tagName === 'TD') cells.push(node);
    (node.children || []).forEach(walk);
  };
  walk(root);
  const dimmed = cells.filter((c) => (c.className || '').includes('watch-dim'));
  assert.ok(dimmed.length >= 2, 'not-detected figures are dimmed');
  assert.ok(dimmed.every((c) => c.attrs.title && c.attrs.title.includes('not detected')), 'a dimmed figure says why');
  assert.ok(textOf(root).includes('18%') && textOf(root).includes('47%'));
  assert.ok(textOf(root).includes('+6.3 bp ±1.4'));
}));

test('the empty states say so: no events, no conditions', () => withBrowser(() => {
  const root = new FakeNode('main');
  renderWatch(root, { ...fixture(), events: [], scenarios: [] }, null, {});
  const text = textOf(root);
  assert.ok(text.includes('No release or FOMC decision in the next 14 days.'));
  assert.ok(text.includes('No conditions in config/dashboard.toml [[watch.scenarios]].'));
}));

test('a build without a watch file says so, and a missing Kalshi market is said, not guessed', () => withBrowser(() => {
  const missing = new FakeNode('main');
  renderWatch(missing, { unavailable: 'watch.json not found' }, null, {});
  assert.ok(textOf(missing).includes('No scenario watch in this build.'));

  const root = new FakeNode('main');
  renderWatch(root, { ...fixture(), events: [{ ...cpi, market: null }], scenarios: [] }, null, {});
  assert.ok(textOf(root).includes('no Kalshi market'));
}));
