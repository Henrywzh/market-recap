import test from 'node:test';
import assert from 'node:assert/strict';
import { signedBn, ordinal, pctileText, summaryRows, chartSeries, GROUP_KEYS, section } from '../../web/js/flows-z1.js';

const MINUS = '−';

test('signed dollars in billions use a true minus sign and fall back to millions under a billion', () => {
  assert.equal(signedBn(350.49), '+$350.5bn');
  assert.equal(signedBn(-1163.6), `${MINUS}$1,163.6bn`);
  assert.equal(signedBn(-0.31), `${MINUS}$310m`);
  assert.equal(signedBn(0), '$0.0bn');
  for (const v of [null, undefined, NaN, Infinity]) assert.equal(signedBn(v), '—');
});

test('percentiles read as ordinals, teens included, and a missing one is a dash', () => {
  assert.equal(ordinal(1), '1st');
  assert.equal(ordinal(12), '12th');
  assert.equal(ordinal(21), '21st');
  assert.equal(pctileText(91.4), '91st pct');
  assert.equal(pctileText(null), '—');
});

const data = {
  latest: [
    { key: 'households', label: 'Households (residual sector)', q_bn: 350.49, trailing_4q_bn: 1523.6, pctile_4q: 100 },
    { key: 'mutual_funds', label: 'Mutual funds', q_bn: -222.96, trailing_4q_bn: -1163.6, pctile_4q: 0.7 },
    { key: 'etfs', label: 'ETFs', q_bn: 393.13, trailing_4q_bn: null, pctile_4q: null },
    { key: 'pensions', label: 'Pension funds', q_bn: -37.11, trailing_4q_bn: -48.6, pctile_4q: 58.2 },
    { key: 'insurers', label: 'Insurers', q_bn: -77.62, trailing_4q_bn: -179, pctile_4q: 3.4 },
    { key: 'rest_of_world', label: 'Rest of world', q_bn: 410.24, trailing_4q_bn: 736.9, pctile_4q: 100 },
    { key: 'broker_dealers', label: 'Broker-dealers', q_bn: -33.29, trailing_4q_bn: -41, pctile_4q: 4.8 },
    { key: 'other', label: 'Other', q_bn: -52.32, trailing_4q_bn: -156.8, pctile_4q: 18.5 },
    { key: 'total', label: 'Total, all sectors', q_bn: 730.55, trailing_4q_bn: 1959.9, pctile_4q: 100 },
  ],
  issuers: [
    { key: 'nfc_issues', label: 'Nonfinancial corporate net issues', q_bn: 120.5, trailing_4q_bn: -45.2, pctile_4q: 88 },
    { key: 'financial_issues', label: 'Financial corporate net issues', q_bn: -43.08, trailing_4q_bn: 1832.4, pctile_4q: 100 },
  ],
  history: {
    dates: ['2026-01-01', '2026-04-01'],
    total: [1, 2],
    groups: { households: [1, 2], mutual_funds: [-1, null], other: [0, 0] },
    nfc_issues: [-43.08, null],
  },
};

test('table rows keep a missing figure as a dash and skip groups with no value', () => {
  const rows = summaryRows(data);
  assert.deepEqual(rows.holders.map((r) => r.key), ['households', 'mutual_funds', 'etfs', 'pensions', 'insurers', 'rest_of_world', 'broker_dealers', 'other']);
  const etf = rows.holders.find((r) => r.key === 'etfs');
  assert.equal(etf.last4, '—');
  assert.equal(etf.pctile, '—');
  assert.equal(rows.total.latest, '+$730.6bn');
  assert.equal(rows.issuers[1].latest, `${MINUS}$43.1bn`);
});

test('chart series take the groups in order and the net-issues line beside them', () => {
  const out = chartSeries(data.history);
  assert.deepEqual(out.dates, ['2026-01-01', '2026-04-01']);
  assert.deepEqual(out.bars.map((b) => b.key), ['households', 'mutual_funds', 'other']);
  assert.deepEqual(out.line, [-43.08, null]);
  assert.ok(GROUP_KEYS.includes('other'));
});

class FakeNode {
  constructor(tag) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.className = '';
    this.textContent = '';
  }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  append(...nodes) { this.children.push(...nodes); }
}

// Run against a small fake DOM: no ECharts, and the chart draw is a no-op frame.
function withDom(run) {
  const saved = { document: globalThis.document, window: globalThis.window, rAF: globalThis.requestAnimationFrame };
  globalThis.document = {
    createElement: (tag) => new FakeNode(tag),
    createTextNode: (text) => ({ nodeType: 3, text: String(text) }),
  };
  globalThis.window = {};
  globalThis.requestAnimationFrame = () => 0;
  try {
    return run();
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
}

function textOf(node) {
  if (node.nodeType === 3) return node.text;
  return (node.textContent || '') + node.children.map(textOf).join(' ');
}

test('a failed or empty section is a gap card, never a blank', () => {
  withDom(() => {
    for (const input of [null, { unavailable: 'FRED served no CSV' }, { latest: [], history: {} }]) {
      const nodes = section(input);
      assert.equal(nodes.length, 1);
      assert.match(textOf(nodes[0]), /Not built this session|No Z\.1 quarters/);
    }
  });
});

test('a built section shows the quarter, the table and no placeholder words', () => {
  const payload = {
    ...data,
    latest_quarter: '2026Q2',
    latest_quarter_end: '2026-06-30',
    released: '2026-09-11',
    next_release: '2026-12-10',
    groups: GROUP_KEYS.map((key) => ({ key, label: key, members: '' })),
    not_covered: ['Nonfinancial corporate net issues'],
    revisions: 'Each release revises earlier quarters.',
  };
  withDom(() => {
    const [card] = section(payload);
    const text = textOf(card);
    assert.match(text, /Quarter 2026Q2 \(ended 2026-06-30\)/);
    assert.match(text, /GROUP/);
    assert.match(text, /Method & limits/);
    for (const bad of ['NaN', 'undefined', '[object Object]']) assert.equal(text.includes(bad), false, bad);
  });
});
