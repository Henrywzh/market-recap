import { test } from 'node:test';
import assert from 'node:assert/strict';

// The layer reads its language from the page at import: a page asking for Chinese.
const store = new Map();
globalThis.window = { location: { search: '?lang=zh', href: 'http://x/?lang=zh' } };
globalThis.localStorage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
const { ZH, translateText, translateHtml, translateOption } = await import('../../web/js/i18n.js');

test('the page asked for Chinese and remembers it', () => {
  assert.equal(ZH, true);
  assert.equal(store.get('mr-lang'), 'zh');
});

test('exact phrases match as written or in capitals; whitespace is kept', () => {
  assert.equal(translateText('YIELDS OVER TIME'), '收益率走势');
  assert.equal(translateText('  Yields over time '), '  收益率走势 ');
  assert.equal(translateText('2026-11-09'), '2026-11-09');
  assert.equal(translateText('Something no one wrote down'), 'Something no one wrote down');
});

test('a short all-caps word is a ticker unless it sits in a label', () => {
  assert.equal(translateText('ALL'), 'ALL');            // Allstate in a table cell
  assert.equal(translateText('ALL', { label: true }), '全部');
  assert.equal(translateText('NOW'), 'NOW');
});

test('numbers and dates fill a template in order', () => {
  assert.equal(translateText('76 names'), '76 只个股');
  assert.equal(translateText('AS OF 2026-11-09'), '截至 2026-11-09');
  assert.equal(translateText('CREDIT SPREADS BY RATING · AS OF 2026-11-04'), 'CREDIT SPREADS BY RATING · 截至 2026-11-04');
  assert.equal(translateText('S&P 500'), '标普 500');
});

test('the headline and its line read in Chinese', () => {
  assert.equal(translateText('Semis +7.5% (rare)'), '半导体 +7.5%（罕见）');
  assert.equal(translateText('Rally, led by'), '上涨，领涨：');
  assert.equal(translateText('S&P 500 +2.4%, Nasdaq-100 +3.4%, Equal weight +2.3%. Rare: Semis rose this far on 0.3% of days. VIX 25.6 (−1.2).'),
    '标普 500 +2.4%，纳斯达克-100 +3.4%，等权 +2.3%。罕见：半导体上涨达此幅度的交易日仅占 0.3%。VIX 25.6 (−1.2)。');
  assert.equal(translateText('broad fall: the index did worse than its typical member by 2.1 points, the heaviest names pulling it down'),
    '普跌：指数跑输普通成分股 2.1 个百分点，最大权重股拖累了指数');
  assert.equal(translateText('TUE NOV 10'), '11月10日 周二');
});

test('chart options: names, categories, legend state and formatter output', () => {
  const option = translateOption({
    series: [{ name: 'Volume', data: [1, 2] }], xAxis: { data: ['Energy', 'NVDA', '2026-11-09'] },
    legend: { selected: { Volume: true } }, tooltip: { formatter: () => '<b>MEDIAN</b> 4.2' },
  });
  assert.equal(option.series[0].name, '成交量');
  assert.deepEqual(option.xAxis.data, ['能源', 'NVDA', '2026-11-09']);
  assert.deepEqual(option.legend.selected, { 成交量: true });
  assert.equal(option.tooltip.formatter(), '<b>中位数</b> 4.2');
  assert.equal(translateHtml('plain MEDIAN'), 'plain MEDIAN');
});
