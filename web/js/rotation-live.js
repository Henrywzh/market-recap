// SECTORS, today so far: the page's own baskets priced at the heat-map
// board's live member quotes, so TODAY is the same basket, weighting and
// benchmark as the 1M-12M windows -- only the prices are intraday. The SPDR
// sector funds come alongside as the tradable comparison, never in place of
// the basket. Kept apart from the DOM so it can be tested under node.

export const TODAY = 'TODAY';
const SCHEMES = ['cap', 'equal'];
const ok = (v) => typeof v === 'number' && Number.isFinite(v);
const less = (a, b) => (ok(a) && ok(b) ? a - b : null);

// {benchmark, groups, subs, members, etfs, priced, total} from the members'
// change since the previous close. A member without a live price is left out
// of every average (and counted in `priced`), not read as unchanged.
export function todayFrom(data, quotes, etfQuotes = []) {
  const live = new Map((quotes || []).filter((q) => ok(q.change_pct)).map((q) => [q.symbol, q.change_pct]));
  const priced = (data.members || []).filter((m) => live.has(m.ticker) && ok(m.weight));
  const mean = (rows, weigh) => {
    let total = 0;
    let sum = 0;
    rows.forEach((m) => { total += weigh(m); sum += weigh(m) * live.get(m.ticker); });
    return total ? sum / total : null;
  };
  const basket = (rows) => ({ cap: mean(rows, (m) => m.weight), equal: mean(rows, () => 1) });
  const benchmark = basket(priced);
  const beating = (rows, scheme) => (rows.length && ok(benchmark[scheme])
    ? (100 * rows.filter((m) => live.get(m.ticker) > benchmark[scheme]).length) / rows.length : null);
  const describe = (rows) => {
    const r = basket(rows);
    return Object.fromEntries(SCHEMES.map((s) => [s, { return: r[s], excess: less(r[s], benchmark[s]), breadth: beating(rows, s) }]));
  };

  const groups = {};
  const members = {};
  (data.groups || []).forEach((g) => {
    const rows = priced.filter((m) => m.sector === g.key);
    groups[g.key] = { ...describe(rows), priced: rows.length };
    const weight = rows.reduce((t, m) => t + m.weight, 0);
    // A member's share of its sector's pp: its weight in the sector times its
    // lead over the index, as the longer windows define it.
    rows.forEach((m) => {
      const r = live.get(m.ticker);
      members[m.ticker] = {
        return: r,
        contribution: {
          cap: weight && ok(benchmark.cap) ? (m.weight / weight) * (r - benchmark.cap) : null,
          equal: ok(benchmark.equal) ? (r - benchmark.equal) / rows.length : null,
        },
      };
    });
  });
  const subs = {};
  (data.sub_industries || []).forEach((x) => {
    subs[`${x.sector}|${x.label}`] = describe(priced.filter((m) => m.sector === x.sector && m.sub_sector === x.label));
  });

  const spy = (etfQuotes || []).find((q) => q.label === 'benchmark');
  const etfs = {};
  (etfQuotes || []).filter((q) => q.label !== 'benchmark').forEach((q) => {
    etfs[q.label] = { symbol: q.symbol, return: ok(q.change_pct) ? q.change_pct : null,
      excess: less(q.change_pct, spy?.change_pct), error: q.error || null };
  });
  return {
    benchmark, groups, subs, members, etfs,
    etfBenchmark: spy ? { symbol: spy.symbol, return: ok(spy.change_pct) ? spy.change_pct : null } : null,
    priced: priced.length, total: (data.members || []).length,
  };
}

// Write `today` into the artifact's own shape as a TODAY window, so every
// card that reads `windows[w]`, `breadth[w]`, `returns[w]` or
// `contribution[scheme][w]` draws it without knowing it is live.
export function applyToday(data, today) {
  SCHEMES.forEach((s) => {
    data.benchmark[s][TODAY] = today.benchmark[s];
    data.groups.forEach((g) => {
      const t = today.groups[g.key]?.[s];
      g[s].windows[TODAY] = { return: t?.return ?? null, excess: t?.excess ?? null };
      g[s].breadth[TODAY] = t?.breadth ?? null;
    });
    (data.sub_industries || []).forEach((x) => {
      const t = today.subs[`${x.sector}|${x.label}`]?.[s];
      x[s][TODAY] = { return: t?.return ?? null, excess: t?.excess ?? null };
    });
  });
  data.members.forEach((m) => {
    const t = today.members[m.ticker];
    m.returns[TODAY] = t?.return ?? null;
    m.contribution = m.contribution || { cap: {}, equal: {} };
    SCHEMES.forEach((s) => {
      m.contribution[s] = m.contribution[s] || {};
      m.contribution[s][TODAY] = t?.contribution[s] ?? null;
    });
  });
  return data;
}
