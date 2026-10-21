// The earnings REPORT CARD: its words (position, report line, guide, revisions,
// drift) and what it draws for a full report and for a sparse one. The card is
// rendered under node against a fake DOM, as the other tab tests are.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  outcomeCard, positionWord, positionTone, reportLine, guideRange, guideStreet, revisionText, driftText, reportFieldNote,
} from '../../web/js/event-card.js';

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
  append(...nodes) { this.children.push(...nodes); }
}

// Installs the fake document for one render and restores the global after.
function withDocument(run) {
  const saved = globalThis.document;
  globalThis.document = {
    createElement: (tag) => new FakeNode(tag),
    createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  };
  try {
    return run();
  } finally {
    if (saved === undefined) delete globalThis.document;
    else globalThis.document = saved;
  }
}

function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.text;
  return [node.textContent || '', ...(node.children || []).map(textOf)].filter(Boolean).join(' ');
}

function nodesWithClass(node, cls, out = []) {
  if (!node || node.nodeType !== 1) return out;
  if (String(node.className).split(' ').includes(cls)) out.push(node);
  for (const child of node.children || []) nodesWithClass(child, cls, out);
  return out;
}

const BAD = /\bNaN\b|\bundefined\b|\[object Object\]/;

// GE as the build writes it: the EPS and revenue scorecard, a guide above the
// street, two revisions, the 5-day drift in and the 20-day not yet.
const GE = {
  symbol: 'GE',
  name: 'General Electric',
  as_of: '2026-10-21',
  card: { priced: { mean_abs: 5.28 } },
  outcome: {
    date: '2026-10-20',
    timing: 'bmo',
    session: '2026-10-20',
    sessions_since: 0,
    eps: 2.25,
    eps_forecast: 2.02,
    surprise_pct: 11.4,
    move_pct: -4.0,
    excess_pct: -4.3,
    vs_implied: 0.8,
    implied: { straddle_pct: 5.0, snapshot_day: '2026-10-16', expiry: '2026-10-23' },
    scorecard: {
      quarter: '3Q2026',
      consensus_day: '2026-10-19',
      eps: { actual: 2.25, consensus: 2.02, low: 1.91, high: 2.10, surprise_pct: 11.4, position: 'above_range', source: 'nasdaq' },
      revenue: { actual: 13285000000, consensus: 12900000000, low: null, high: null, surprise_pct: 3.0, position: 'beat', source: 'yahoo' },
    },
    guide: {
      period: 'FY2026', eps_low: 7.10, eps_high: 7.40, eps_horizon: 'year', revenue_low: null, revenue_high: null, revenue_horizon: null,
      quote: 'Adjusted EPS of $7.10 to $7.40', url: 'https://example.com/ex99',
      vs_consensus: { eps: { low: 7.10, high: 7.40, consensus: 7.05, against: '0y', position: 'above', vs_mid_pct: 2.8 } },
    },
    revisions: [
      { period: '+1q', label: 'Next quarter', end: '2026-12-31', before: 2.30, now: 2.41, change_pct: 4.8 },
      { period: '0y', label: 'This year', end: '2026-12-31', before: 7.05, now: 7.31, change_pct: 3.7 },
    ],
    drift: { '5d': 1.2, '20d': null },
    peers: [],
  },
};

// A report the build could place with nothing else: no scorecard, guide,
// revisions, implied move or name.
const SPARSE = {
  symbol: 'XYZ',
  name: null,
  outcome: {
    date: '2026-10-20', timing: null, session: '2026-10-21', sessions_since: 2,
    eps: null, eps_forecast: null, surprise_pct: null, move_pct: null, excess_pct: null, vs_implied: null, implied: null, peers: [],
  },
};

test('a position word names the band or the consensus, and DASH when the build has none', () => {
  assert.equal(positionWord('above_range'), 'ABOVE EVERY ESTIMATE');
  assert.equal(positionWord('beat'), 'BEAT');
  assert.equal(positionWord('inline'), 'IN LINE');
  assert.equal(positionWord('miss'), 'MISS');
  assert.equal(positionWord('below_range'), 'BELOW EVERY ESTIMATE');
  assert.equal(positionWord(null), '—');
  assert.equal(positionTone('above_range'), 'up');
  assert.equal(positionTone('miss'), 'down');
  assert.equal(positionTone('inline'), '');
});

test('the report line gives the day, the timing, the traded session and sessions since', () => {
  assert.equal(reportLine(GE.outcome), 'reported 2026-10-20 BMO · traded 2026-10-20');
  assert.equal(reportLine({ ...GE.outcome, sessions_since: 1 }), 'reported 2026-10-20 BMO · traded 2026-10-20 · 1 session ago');
  assert.equal(reportLine({ ...GE.outcome, sessions_since: 3 }), 'reported 2026-10-20 BMO · traded 2026-10-20 · 3 sessions ago');
  assert.equal(reportLine({ date: null, timing: null, session: null }), 'reported — · traded —');
});

test('the guide range names its figures and period, and says where the guide sits against the street', () => {
  assert.equal(guideRange(GE.outcome.guide), 'EPS 7.10–7.40 · FY2026');
  assert.equal(guideRange(null), null);
  assert.equal(guideRange({ period: 'FY2026', eps_low: null, eps_high: null }), null);
  assert.equal(guideStreet(GE.outcome.guide), 'street 7.05 → guide above the street (+2.8% at mid)');
  assert.equal(guideStreet({ vs_consensus: null }), null);
});

test('a revision reads from before to now with its change, and a drift waits for its session', () => {
  assert.equal(revisionText(GE.outcome.revisions[0]), 'Next quarter 2.30 → 2.41 (+4.8%)');
  assert.equal(revisionText({ label: 'This year', before: null, now: null, change_pct: null }), 'This year — → —');
  assert.equal(driftText(1.2, 5), '+1.2% vs S&P 5 sessions later');
  assert.equal(driftText(null, 20), '—');
});

test('the field note names the consensus day it was recorded on', () => {
  assert.match(reportFieldNote('2026-10-19'), /consensus recorded on 2026-10-19 \(Yahoo, Nasdaq for the EPS point\)/);
  assert.match(reportFieldNote(null), /consensus recorded before the report/);
});

test('a full report draws its scorecard, guide, revisions and drift, with no empty words', () => {
  const node = withDocument(() => outcomeCard(GE));
  const text = textOf(node);
  assert.equal(BAD.test(text), false, 'no NaN, undefined or [object Object]');
  assert.ok(text.includes('GE · GENERAL ELECTRIC'));
  assert.ok(text.includes('reported 2026-10-20 BMO · traded 2026-10-20'));
  assert.ok(!text.includes('sessions ago'), 'the report was traded today');
  assert.ok(text.includes('EPS BEAT +11.4%'));
  assert.ok(text.includes('INSIDE IMPLIED (0.8×)'));
  assert.ok(text.includes('vs 2.02 consensus · +11.4%'));
  assert.ok(text.includes('ABOVE EVERY ESTIMATE · Nasdaq'));
  assert.ok(text.includes('-4.3% vs S&P 500'));
  assert.ok(text.includes('EPS 7.10–7.40 · FY2026'));
  assert.ok(text.includes('street 7.05 → guide above the street (+2.8% at mid)'));
  assert.ok(text.includes('Next quarter 2.30 → 2.41 (+4.8%)'));
  assert.ok(text.includes('This year 7.05 → 7.31 (+3.7%)'));
  assert.ok(text.includes('+1.2% vs S&P 5 sessions later'));
  assert.ok(text.includes('the consensus recorded on 2026-10-19'));
});

test('the revenue line shows its figures in billions and says there is no range', () => {
  const text = textOf(withDocument(() => outcomeCard(GE)));
  assert.match(text, /\$13\.2[89]B vs \$12\.90B consensus · \+3\.0%/);
  assert.ok(text.includes('BEAT · Yahoo'));
});

test('the EPS and the move are drawn: the actuals marked on their scales, the move on the priced band', () => {
  const node = withDocument(() => outcomeCard(GE));
  const markers = nodesWithClass(node, 'ec-rbar-actual');
  assert.equal(markers.length, 3, 'one for EPS, one for revenue, one for the move');
  assert.ok(markers[0].className.includes('up'), 'an EPS above the range is green');
  assert.ok(markers[2].className.includes('down'), 'a move down is red');
  assert.ok(nodesWithClass(node, 'ec-rbar-box').length >= 1, 'the analysts box is drawn');
});

test('a sparse report shows dashes and the reasons, with no NaN or undefined', () => {
  const node = withDocument(() => outcomeCard(SPARSE));
  const text = textOf(node);
  assert.equal(BAD.test(text), false, 'no NaN, undefined or [object Object]');
  assert.ok(text.includes('XYZ'), 'the symbol stands in for the name');
  assert.ok(text.includes('2 sessions ago'));
  assert.ok(text.includes('no revenue figure yet'));
  assert.ok(text.includes('no guide found in the release'));
  assert.ok(text.includes('no recorded consensus before the report'));
  assert.ok(text.includes('no consensus on file'));
  assert.equal(nodesWithClass(node, 'ec-rbar-actual').length, 0, 'nothing to mark without figures');
});

test('the compact card keeps the same parts under a link title', () => {
  const node = withDocument(() => outcomeCard(GE, { compact: true }));
  assert.ok(node.className.includes('compact'));
  const title = nodesWithClass(node, 'card-title')[0];
  assert.equal(title.tagName, 'A');
  assert.equal(textOf(title), 'GE · GENERAL ELECTRIC');
  const text = textOf(node);
  assert.ok(text.includes('street 7.05 → guide above the street'));
  assert.ok(text.includes('+1.2% vs S&P 5 sessions later'));
  assert.equal(BAD.test(text), false);
});

test('a report without an outcome has no card', () => {
  assert.equal(withDocument(() => outcomeCard({ symbol: 'XYZ' })), null);
});
