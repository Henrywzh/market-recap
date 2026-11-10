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

test('a formatter gets the English names its chart code keys by, and its output is translated', () => {
  const kindOf = { Revenue: 'money' };
  const option = translateOption({
    series: [{ name: 'Revenue', data: [1] }],
    tooltip: { formatter: (items) => [].concat(items).map((it) => `${it.seriesName} ${kindOf[it.seriesName]}`).join('<br>') },
  });
  assert.equal(option.series[0].name, '营收');
  assert.equal(option.tooltip.formatter([{ seriesName: '营收', value: 1 }]), 'Revenue money');
});

test('words that change meaning with their place read as meant there', () => {
  assert.equal(translateText('OPEN', { label: true }), '打开');            // the ticker box's button, not the market open
  assert.equal(translateText('D1 OPEN'), 'D1 开盘');
  assert.equal(translateText('3M', { label: true }), '3个月');             // a window, not March
  assert.equal(translateText('VALUE · IWD'), '价值 · IWD');                // the style, not a table's value column
});

test('templates put every figure where it belongs', () => {
  assert.equal(translateText('-0.4% vs S&P 5 sessions later'), '5 个交易日后相对标普 -0.4%');
  assert.equal(translateText('beat 6 of 7'), '7 次中 6 次超预期');
  assert.equal(translateText('top 30 S&P 500 weights + watchlist'), '标普 500 前 30 大权重 + 自选');
  assert.equal(translateText('top-1% median'), '前 1% 中位数');
});
