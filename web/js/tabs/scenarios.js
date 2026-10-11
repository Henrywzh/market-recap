// SCENARIOS: what each data release has done to rates and stocks, measured.
// The build counts past releases above / in line with / below the forecast and
// reads the day's move in the 2-year and 10-year yield, SPY, small caps,
// regional banks and each sector. Figures under |t| of 2 are drawn dim with
// their n: not detected is not zero. Nothing here forecasts.

import { el, card, table, num, metaRow, tag, gap, DASH } from '../fmt.js';
import { detected, diffWithSe, sectorDiffs, barSpan, columnScale, nextText, persistenceView } from '../scenarios-model.js';

const present = (v) => v !== null && v !== undefined && Number.isFinite(v);
const signed = (v, digits, unit = '') => (present(v) ? `${v > 0 ? '+' : ''}${num(v, digits)}${unit}` : DASH);
const CLASS_LABELS = { above: 'ABOVE FORECAST', inline: 'IN LINE', below: 'BELOW FORECAST' };

function stat(label, value, note, cls = '') {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }),
    el('div', { class: `stat-value ${cls}`, text: value }),
    note ? el('div', { class: 'stat-note', text: note }) : null,
  ]);
}

// --- the strip ---------------------------------------------------------------

function strip(data) {
  const r = data.regime || {};
  const coming = data.drivers
    .filter((d) => d.next && d.next.date > data.as_of)
    .sort((a, b) => (a.next.date + a.next.time).localeCompare(b.next.date + b.next.time))
    .slice(0, 3);
  const last = (data.fomc?.recent || []).slice(-1)[0];
  const lag = data.inputs.yields_through < data.inputs.prices_through;
  return el('div', { class: 'stat-strip' }, [
    stat('MARKET IS DRIVEN BY', r.label === 'rates' ? 'RATES' : r.label === 'growth' ? 'GROWTH' : DASH,
      present(r.corr) ? `SPY vs 10Y change, ${r.sessions} sessions: ${signed(r.corr, 2)} · negative ${Math.round((r.share_negative || 0) * 100)}% of days since ${(r.since || '').slice(0, 4)}` : null,
      r.label === 'rates' ? 'warn' : ''),
    stat('NEXT RELEASES', coming.length ? nextText(coming[0].next).when : DASH,
      coming.length ? coming.map((d) => { const t = nextText(d.next); return `${d.label} ${t.when.split(' ').slice(0, 3).join(' ')}: forecast ${t.forecast} · prior ${t.previous}`; }).join(' | ') : 'none in the calendar window'),
    stat('LAST FOMC', last ? `${num(last.rate, 2)}%` : DASH, last ? `${last.date} · was ${num(last.previous, 2)}% · SPY ${signed(last.spy, 2, '%')} · 2Y ${signed(last.dY2, 0, 'bp')}` : null),
    stat('DATA', `prices ${data.inputs.prices_through}`, `yields ${data.inputs.yields_through}${lag ? ' (FRED lags the close by a day; that session has no yield move)' : ''}`, lag ? 'warn' : ''),
  ]);
}

// --- the drivers table -------------------------------------------------------

// A value on a track with a bar from its centre; dim when the figure is not
// detected. `tone` colours the bar: 'rates' (yield up / down) or 'stock'.
function barCell(entry, scale, digits, unit, tone) {
  if (!entry || !present(entry.slope)) return el('td', { class: 'dim', text: DASH });
  const span = barSpan(entry.slope, scale);
  const hit = detected(entry);
  const sign = entry.slope >= 0 ? 'pos' : 'neg';
  return el('td', { class: `sc-cell${hit ? '' : ' sc-dim'}`, title: `n ${entry.n}${present(entry.t) ? ` · t ${num(entry.t, 1)}` : ''}${hit ? '' : ' · not detected (|t| < 2)'}` }, [
    el('div', { class: 'sc-track' }, [span ? el('span', { class: `sc-bar ${tone}-${sign}`, style: `left:${span.left}%;width:${span.width}%` }) : null]),
    el('div', { class: 'sc-val' }, [signed(entry.slope, digits, unit), el('span', { class: 'sc-t', text: ` t ${num(entry.t, 1)}` })]),
  ]);
}

function eraCells(eras) {
  return el('td', { class: 'sc-eras' }, (eras || []).map((e) => {
    const hit = detected(e);
    return el('span', { class: `sc-era ${hit ? (e.slope > 0 ? 'up' : 'down') : 'sc-dim'}`, title: `${e.era}: n ${e.n}${present(e.t) ? ` · t ${num(e.t, 1)}` : ''}${hit ? '' : ' · not detected'}` }, [
      el('span', { class: 'sc-era-name', text: e.era.replace(/^(\d{2})(\d{2})-/, '$2-').replace(/-(\d{2})(\d{2})$/, '-$2') }),
      el('span', { text: present(e.slope) ? signed(e.slope, 2) : DASH }),
    ]);
  }));
}

function driversCard(data, state, onPick) {
  const ok = data.drivers.filter((d) => d.status === 'ok');
  const rateScale = columnScale(ok.map((d) => d.rates_per_sd.dY2.slope));
  const spyScale = columnScale(ok.map((d) => d.spy_per_sd.slope));
  const rows = data.drivers.map((d) => {
    const next = nextText(d.next);
    const tr = el('tr', { class: `sc-row${d.key === state.key ? ' sc-selected' : ''}`, tabindex: '0', role: 'button', onclick: () => onPick(d.key) }, []);
    tr.append(el('td', {}, [el('div', { class: 'sc-name', text: d.label }), el('div', { class: 'dim sc-sub', text: d.status === 'ok' ? `${d.n} releases since ${(d.first || '').slice(0, 4)}` : `${d.n} releases: too few` })]));
    tr.append(el('td', { class: next ? '' : 'dim' }, next ? [el('div', { text: next.when }), el('div', { class: 'dim sc-sub', text: `forecast ${next.forecast} · prior ${next.previous}` })] : [DASH]));
    if (d.status !== 'ok') {
      tr.append(el('td', { class: 'dim', colspan: '5', text: 'not enough releases to measure' }));
      return tr;
    }
    const c = d.classes;
    tr.append(el('td', { class: 'sc-counts', title: 'releases above / in line with / below the forecast' }, [
      el('span', { class: 'up', text: `${c.above.n}↑` }), ' ', el('span', { class: 'dim', text: `${c.inline.n}=` }), ' ', el('span', { class: 'down', text: `${c.below.n}↓` }),
    ]));
    tr.append(barCell(d.rates_per_sd.dY2, rateScale, 1, 'bp', 'rate'));
    tr.append(barCell(d.spy_per_sd, spyScale, 2, '%', 'stock'));
    tr.append(eraCells(d.spy_by_era));
    const p = persistenceView(d.persistence);
    tr.append(el('td', {}, [tag(p.text, p.tone, p.title)]));
    return tr;
  });
  return card('WHAT A SURPRISE DID · PER STANDARD DEVIATION OF SURPRISE', el('span', { class: 'dim', text: 'click a row for its detail · dim = not detected (|t| < 2)' }), [
    table(['RELEASE', 'NEXT', 'PAST', '2Y YIELD', 'SPY', 'SPY BY ERA', 'SECTOR ORDER HELD?'], rows, { class: 'sc-table' }),
    el('div', { class: 'field-note', text: 'PAST: releases above (↑) / in line (=) / below (↓) the forecast. 2Y YIELD and SPY: the move on release days per standard deviation of the surprise, with the t-statistic. SPY BY ERA: 2016-19, 2020-21, 2022-23, 2024 on. SECTOR ORDER HELD?: whether the ordering of sectors on above-minus-below found before 2022 held after it (rank correlation, permutation p).' }),
  ]);
}

// --- one driver in detail ----------------------------------------------------

function meanCell(entry, digits, unit = '') {
  if (!entry) return el('td', { class: 'dim', text: DASH });
  return el('td', {}, [signed(entry.mean, digits, unit), present(entry.se) ? el('span', { class: 'dim sc-se', text: ` ±${num(entry.se, digits)}` }) : null]);
}

function classTable(d) {
  const rows = ['above', 'inline', 'below'].map((cls) => {
    const c = d.classes[cls];
    const has = present(c?.SPY?.mean) || present(c?.dY2?.mean);
    return el('tr', {}, [
      el('td', { text: CLASS_LABELS[cls] }), el('td', { text: String(c.n) }),
      ...(has ? [meanCell(c.dY2, 1, 'bp'), meanCell(c.dY10, 1, 'bp'), meanCell(c.SPY, 2, '%'), meanCell(c['IWM-SPY'], 2), meanCell(c['KRE-SPY'], 2)]
        : [el('td', { class: 'dim', colspan: '5', text: 'too few releases for a figure' })]),
    ]);
  });
  return table(['', 'N', '2Y', '10Y', 'SPY', 'IWM − SPY', 'KRE − SPY'], rows);
}

function sectorBars(d, sectors) {
  const rows = sectorDiffs(d.classes, sectors);
  if (!rows.length) return el('div', { class: 'dim', text: 'No sector figures: a class has too few releases.' });
  const scale = columnScale(rows.flatMap((r) => [r.diff, present(r.se) ? Math.abs(r.diff) + 1.96 * r.se : null])) || 1;
  const at = (v) => Math.max(0, Math.min(100, 50 + (v / scale) * 50));
  return el('div', { class: 'sc-sectors' }, rows.map((r) => {
    const span = barSpan(r.diff, scale);
    const whisker = present(r.se) ? { left: at(r.diff - 1.96 * r.se), right: at(r.diff + 1.96 * r.se) } : null;
    return el('div', { class: `sc-sector${r.within ? ' sc-dim' : ''}`, title: `${r.sector}: above − below ${signed(r.diff, 2, ' pp')}${present(r.se) ? ` ±${num(1.96 * r.se, 2)} (95%)` : ''}${r.within ? ' · within the noise' : ''}` }, [
      el('span', { class: 'sc-sector-name', text: `${r.etf}` }),
      el('div', { class: 'sc-track sc-track-wide' }, [
        el('span', { class: 'sc-axis' }),
        span ? el('span', { class: `sc-bar stock-${r.diff >= 0 ? 'pos' : 'neg'}`, style: `left:${span.left}%;width:${span.width}%` }) : null,
        whisker ? el('span', { class: 'sc-whisker', style: `left:${whisker.left}%;width:${whisker.right - whisker.left}%` }) : null,
      ]),
      el('span', { class: 'sc-sector-val', text: signed(r.diff, 2) }),
    ]);
  }));
}

function detailCard(data, d) {
  if (!d || d.status !== 'ok') return card('DETAIL', null, [gap('Not enough releases of this line to measure.')]);
  const p = d.persistence;
  const pv = persistenceView(p);
  const order = p?.status === 'tested'
    ? `Sector ordering found before ${p.split}, checked after: rank correlation ${signed(p.rho, 2)}, permutation p ${num(p.p_perm, 2)} (${p.permutations} shuffles). ${p.p_perm < 0.05 ? 'It held.' : 'Not a finding: with this many releases the ordering after the split cannot be told from chance.'}`
    : 'Too few releases in a class, before or after 2022, to test whether the ordering held.';
  return card(`${d.label.toUpperCase()} · PAST RELEASES`, el('span', { class: 'dim', text: `${d.first} to ${d.last} · surprise spread ${num(d.scale, 2)} ${d.unit}` }), [
    el('div', { class: 'grid two' }, [
      el('div', {}, [el('div', { class: 'card-title', text: 'WHAT THE DAY DID, BY SURPRISE CLASS · MEAN ± STANDARD ERROR' }), classTable(d)]),
      el('div', {}, [el('div', { class: 'card-title', text: 'SECTOR EXCESS VS SPY · ABOVE MINUS BELOW · 95% RANGE' }), sectorBars(d, data.sectors)]),
    ]),
    el('div', { class: 'field-note', text: `${order} A sector bar whose range crosses zero is dim: its difference is within the noise. SPY when rates drive the market (60-day correlation below zero): ${signed(d.spy_when_rates_drive.slope, 2)}% per standard deviation, t ${num(d.spy_when_rates_drive.t, 1)}, n ${d.spy_when_rates_drive.n}.` }),
    tag(pv.text, pv.tone, pv.title),
  ]);
}

// --- FOMC days ---------------------------------------------------------------

function fomcCard(f) {
  if (!f || !f.decisions) return card('FOMC DAYS', null, [gap('No decisions in the calendar history.')]);
  const a = f.abs_move, s = f.spy_per_bp_of_2y;
  const slopeLine = (label, e) => el('div', { class: `sc-fomc-line${detected(e) ? '' : ' sc-dim'}` }, [
    el('span', { text: label }), el('b', { class: e.slope > 0 ? 'up' : 'down', text: `${signed(e.slope, 3, '%')} per +1bp of 2Y` }), el('span', { class: 'dim', text: ` t ${num(e.t, 1)} · n ${e.n}` }),
  ]);
  const b = f.buckets;
  return card('FOMC DAYS · STOCKS AGAINST THE 2-YEAR YIELD', el('span', { class: 'dim', text: `${f.decisions} decisions · ${f.decisions_with_surprise} differed from the forecast` }), [
    el('div', { class: 'grid two' }, [
      el('div', {}, [
        slopeLine('FOMC days', s.fomc_days), slopeLine('Other days', s.other_days),
        el('div', { class: 'sc-fomc-line dim', text: `Average |move|: SPY ${num(a.spy_fomc, 2)}% vs ${num(a.spy_other, 2)}% · 2Y ${num(a.dY2_fomc, 1)}bp vs ${num(a.dY2_other, 1)}bp (FOMC vs other days)` }),
        el('div', { class: 'sc-fomc-line' }, [
          el('span', { text: `2Y up ≥ ${b.bp}bp that day (${b.hawkish.n} days): ` }), el('b', { class: b.hawkish.spy < 0 ? 'down' : 'up', text: `SPY ${signed(b.hawkish.spy, 2, '%')}` }),
          el('span', { text: `   · 2Y down ≥ ${b.bp}bp (${b.dovish.n}): ` }), el('b', { class: b.dovish.spy < 0 ? 'down' : 'up', text: `SPY ${signed(b.dovish.spy, 2, '%')}` }),
        ]),
      ]),
      table(['DECISION', 'RATE', 'WAS', 'SPY', '2Y'], (f.recent || []).slice().reverse().map((r) => el('tr', {}, [
        el('td', { text: r.date }), el('td', { text: `${num(r.rate, 2)}%` }), el('td', { class: 'dim', text: `${num(r.previous, 2)}%` }),
        el('td', { class: r.spy > 0 ? 'up' : 'down', text: signed(r.spy, 2, '%') }), el('td', { text: signed(r.dY2, 0, 'bp') }),
      ]))),
    ]),
    el('div', { class: 'sc-fomc-line', text: s.fomc_days.slope < 0 && s.other_days.slope > 0
      ? 'On FOMC days stocks moved against the 2-year yield; on other days they moved with it: the market reads the day as about the discount rate.'
      : 'On FOMC days and other days stocks moved the same way against the 2-year yield.' }),
    el('div', { class: 'field-note', text: 'Almost no decision differs from the forecast, so the rate decision carries no surprise to classify; the day\'s information is the statement and the press conference. Hawkish and dovish here are what the 2-year yield did that day -- a measure afterwards, not known beforehand.' }),
  ]);
}

// --- the view ----------------------------------------------------------------

export default function renderScenarios(root, data, _manifest, ctx = {}) {
  if (!data || data.unavailable || !Array.isArray(data.drivers)) {
    root.append(gap('No scenario measurements in this build.'));
    return;
  }
  const known = new Set(data.drivers.map((d) => d.key));
  const wanted = (ctx.arg || '').toLowerCase();
  const first = data.drivers.find((d) => d.next && d.status === 'ok') || data.drivers.find((d) => d.status === 'ok') || data.drivers[0];
  const state = { key: known.has(wanted) ? wanted : first.key };
  root.append(metaRow(`SCENARIOS · WHAT PAST RELEASES DID TO RATES AND STOCKS · AS OF ${data.as_of}`, [
    ...data.notes,
    `Releases from ${data.settings.history_start}; ${data.settings.exclude.map((w) => `${w.label} ${w.start} to ${w.end} excluded`).join('; ')}. A release is above or below the forecast by more than ${data.settings.class_threshold_sd} of its line's robust standard deviations (any miss, for lines published to one decimal); a class or era with fewer than ${data.settings.min_class_releases} releases shows its count and no figure.`,
  ]));
  root.append(strip(data));
  const detailHost = el('div', {});
  const tableHost = el('div', {});
  const draw = () => {
    tableHost.replaceChildren(driversCard(data, state, (key) => { state.key = key; ctx.setArg?.(key.toUpperCase()); draw(); }));
    detailHost.replaceChildren(detailCard(data, data.drivers.find((d) => d.key === state.key)));
  };
  draw();
  root.append(tableHost, detailHost, fomcCard(data.fomc));
}
