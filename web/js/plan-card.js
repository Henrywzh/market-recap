// TRADE PLAN and REVIEW cards on TRADE DESK. A calculator over the user's own
// inputs: nothing is sent or fetched, and the only saved state is an unsent
// draft in this browser. The arithmetic lives in plan-math.js.

import { card, DASH, dirClass, el, num, notice, tag } from './fmt.js';
import { render } from './charts.js';
import { grid as priceGrid, priceRange, volumeProfile } from './chip-math.js';
import {
  breakevenHeadline, planFileName, planMarkdown, planOutcomes, planSensitivity, planToJson,
  journalSummary, readPlanFile, readReviews, reviewMarkdown, reviewToJson, toNumber,
} from './plan-math.js';

const DRAFT_KEY = 'market-recap.trade-plan-draft.v1';
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const info = (text) => el('div', { class: 'note-text', text });
const field = (label, node) => el('div', { class: 'field' }, [el('label', { text: label }), node]);
const stat = (label, value, note = null, cls = '') => el('div', { class: 'stat' }, [
  el('div', { class: 'stat-label', text: label }),
  el('div', { class: `stat-value ${cls}`, text: value }),
  note ? el('div', { class: 'stat-note', text: note }) : null,
]);

// Money and R carry a sign, so a loss is never read as a gain.
const sMoney = (v, digits = 2) => (finite(v) ? `${v < 0 ? '-' : v > 0 ? '+' : ''}$${num(Math.abs(v), digits)}` : DASH);
const sR = (v) => (finite(v) ? `${v > 0 ? '+' : ''}${num(v, 2)} R` : DASH);
const pctText = (v, digits = 1) => (finite(v) ? `${num(100 * v, digits)}%` : DASH);

// Weights are typed as percentages and held as fractions.
const readPct = (node) => {
  const n = toNumber(node.value);
  return n === null || Number.isNaN(n) ? n : n / 100;
};

// The clipboard is refused in some browsers and embedded views: then the text
// is selected in a box for a manual copy.
async function copyText(text, status, box) {
  try {
    await navigator.clipboard.writeText(text);
    box.replaceChildren();
    status.textContent = 'Copied as Markdown.';
  } catch {
    const area = el('textarea', { class: 'plan-copy', rows: '10' });
    area.value = text;
    box.replaceChildren(area);
    area.select();
    status.textContent = 'The clipboard is blocked here. The text is selected below: copy it with Ctrl+C or Cmd+C.';
  }
}

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const link = el('a', { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// The unsent draft only: cleared once a plan is downloaded. Storage can be
// absent or refused (private windows), and the page works without it.
function readDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY));
    return draft && typeof draft === 'object' ? draft : null;
  } catch {
    return null;
  }
}
function writeDraft(value) {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify(value)); } catch { /* not kept */ }
}
function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to clear */ }
}

function nearestIndex(values, target) {
  let best = -1;
  values.forEach((v, i) => { if (best < 0 || Math.abs(v - target) < Math.abs(values[best] - target)) best = i; });
  return best;
}

// EV in R: success rate across, target distance down, coloured by sign so the
// colour change is the zero line. Missing combinations are left out, not zero.
function drawSensitivity(node, grid, yourRate) {
  render(node, (option, p) => {
    const cells = [];
    grid.rows.forEach((row, y) => row.cells.forEach((v, x) => { if (finite(v)) cells.push([x, y, v]); }));
    const yourRow = grid.rows.findIndex((row) => row.multiple === 1);
    const reach = Math.max(0.25, ...cells.map((c) => Math.abs(c[2])));
    const yourCol = finite(yourRate) ? nearestIndex(grid.rates, yourRate) : -1;
    return {
      ...option,
      grid: { ...option.grid, left: 128, right: 16, top: 8, bottom: 30 },
      tooltip: { ...option.tooltip, trigger: 'item',
        formatter: (q) => `${num(100 * grid.rates[q.value[0]], 0)}% success · target ${grid.rows[q.value[1]].multiple}× · ${num(q.value[2], 2)} R` },
      xAxis: { ...option.xAxis, type: 'category', boundaryGap: true, data: grid.rates.map((r) => `${num(100 * r, 0)}%`) },
      yAxis: { ...option.yAxis, type: 'category', data: grid.rows.map((row) => `${row.multiple}× · $${num(row.target, 2)}`),
        axisLabel: { color: p.dim, fontSize: 10 } },
      // Graded, centred on zero: the sign is the hue, the size its depth, so the break-even edge reads as a fade.
      visualMap: { show: false, dimension: 2, min: -reach, max: reach, inRange: { color: [p.down, p.panel, p.up] } },
      series: [
        { type: 'heatmap', data: cells, itemStyle: { borderColor: p.panel, borderWidth: 1 },
          label: { show: true, fontSize: 9, color: p.text, formatter: (q) => num(q.value[2], 2) } },
        { type: 'scatter', tooltip: { show: false }, silent: true, z: 5, symbol: 'rect', symbolSize: 20,
          itemStyle: { color: 'transparent', borderColor: p.text, borderWidth: 2 },
          data: yourRow >= 0 && yourCol >= 0 ? [[yourCol, yourRow]] : [] },
      ],
    };
  });
}

// The plan on the price: the last year's volume by price (from the daily bars, each
// session spread over its range) under the stop, the entry and the target, with
// the loss and gain zones shaded. Where the plan sits against past trading, not a forecast.
const PLAN_SESSIONS = 252;
function drawPlanPrice(node, bars, raw, close) {
  // The form's fields are text; the chart needs the numbers.
  const input = { side: raw.side, entry: toNumber(raw.entry), stop: toNumber(raw.stop), target: toNumber(raw.target) };
  const last = bars.dates.length - 1;
  const from = Math.max(0, last - PLAN_SESSIONS + 1);
  const traded = priceRange(bars, from, last);
  if (!traded) return;
  const levels = [input.entry, input.stop, input.target].filter(finite);
  const lo = Math.min(traded.min, ...levels);
  const hi = Math.max(traded.max, ...levels);
  const pad = (hi - lo) * 0.04;
  const g = priceGrid(lo - pad, hi + pad, 90);
  const volumes = volumeProfile(bars, from, last, g);
  const total = volumes.reduce((a, b) => a + b, 0) || 1;
  const long = input.side !== 'short';
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 16, right: 16, top: 28, bottom: 30 },
    tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: undefined,
      formatter: (items) => { const d = [].concat(items)[0]; return `$${num(d.value[0], 2)} · ${num(d.value[1] * 100, 2)}% of the year's volume`; } },
    xAxis: { ...option.yAxis, type: 'value', min: g.min, max: g.max, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `$${num(v, 0)}` } },
    yAxis: { ...option.yAxis, type: 'value', min: 0, axisLabel: { show: false }, splitLine: { show: false } },
    series: [{
      type: 'line', name: 'Volume by price', smooth: 0.35, showSymbol: false,
      data: g.centers.map((c, k) => [c, volumes[k] / total]),
      lineStyle: { color: p.accent, width: 1.6 }, areaStyle: { color: p.accent, opacity: 0.18 },
      markArea: { silent: true, data: [
        [{ xAxis: input.stop, itemStyle: { color: p.down, opacity: 0.1 } }, { xAxis: input.entry }],
        [{ xAxis: input.entry, itemStyle: { color: p.up, opacity: 0.1 } }, { xAxis: input.target }],
      ] },
      markLine: { silent: true, symbol: 'none', label: { fontSize: 10, position: 'end' }, data: [
        { xAxis: input.stop, name: 'STOP', lineStyle: { color: p.down, type: 'dashed' }, label: { color: p.down, formatter: `STOP $${num(input.stop, 2)}` } },
        { xAxis: input.entry, name: 'ENTRY', lineStyle: { color: p.text, type: 'solid' }, label: { color: p.text, formatter: `${long ? 'LONG' : 'SHORT'} $${num(input.entry, 2)}` } },
        { xAxis: input.target, name: 'TARGET', lineStyle: { color: p.up, type: 'dashed' }, label: { color: p.up, formatter: `TARGET $${num(input.target, 2)}` } },
        ...(finite(close) && Math.abs(close - input.entry) > 1e-9 ? [{ xAxis: close, name: 'CLOSE', lineStyle: { color: p.faint, type: 'dotted' },
          label: { color: p.dim, formatter: `CLOSE $${num(close, 2)}` } }] : []),
      ] },
    }],
  }));
}

// The three outcomes in R after costs, each with the weight you gave it.
function drawOutcomes(node, model) {
  const risk = model.riskPerShare;
  const rows = [['TARGET HIT', model.target, model.weights?.pTarget], ['STOP HIT', model.stop, model.weights?.pStop],
    ['HORIZON ENDS', model.time, model.weights?.pTime]];
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 170, right: 90, top: 10, bottom: 26 },
    tooltip: { show: false },
    xAxis: { ...option.yAxis, type: 'value', axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${num(v, 1)}R` } },
    yAxis: { ...option.xAxis, type: 'category', inverse: true, data: rows.map(([label]) => label), axisLabel: { ...option.xAxis.axisLabel, fontSize: 10 } },
    series: [{
      type: 'bar', barWidth: '46%',
      data: rows.map(([, leg]) => {
        const r = finite(leg.netPerShare) && risk ? leg.netPerShare / risk : null;
        return { value: r, itemStyle: { color: r === null ? p.faint : r >= 0 ? p.up : p.down, opacity: 0.85 },
          label: { position: r < 0 ? 'left' : 'right' } };
      }),
      label: { show: true, position: 'right', color: p.text, fontSize: 10,
        formatter: (d) => `${sR(d.value)}${finite(rows[d.dataIndex][2]) ? ` · ${pctText(rows[d.dataIndex][2], 0)}` : ''}` },
      markLine: { silent: true, symbol: 'none', data: [{ xAxis: 0 }], lineStyle: { color: p.faint }, label: { show: false } },
    }],
  }));
}

function outcomeTable(model) {
  const { weights, expected } = model;
  const rows = [
    ['TARGET HIT', 'up', model.target, weights?.pTarget, expected?.contributions.target],
    ['STOP HIT', 'down', model.stop, weights?.pStop, expected?.contributions.stop],
    // Kept as its own row: a horizon that ends with neither hit is not a stop or a target.
    ['HORIZON ENDS, NEITHER HIT', 'dim', model.time, weights?.pTime, expected?.contributions.time],
  ];
  const body = rows.map(([label, tone, leg, weight, contribution]) => el('tr', {}, [
    el('td', {}, [tag(label, tone)]),
    el('td', { class: dirClass(leg.grossPerShare), text: sMoney(leg.grossPerShare) }),
    el('td', { class: dirClass(leg.netPerShare), text: sMoney(leg.netPerShare) }),
    el('td', { class: dirClass(leg.netPct), text: `${leg.netPct > 0 ? '+' : ''}${num(leg.netPct, 2)}%` }),
    el('td', { text: pctText(weight) }),
    el('td', { class: dirClass(contribution), text: sMoney(contribution) }),
  ]));
  return el('div', { class: 'table-scroll' }, [el('table', { class: 'data trade-plan-out' }, [
    el('thead', {}, [el('tr', {}, ['OUTCOME', 'PER SHARE', 'AFTER COSTS', '% OF ENTRY, AFTER COSTS', 'YOUR WEIGHT', 'EV CONTRIBUTION']
      .map((h) => el('th', { text: h })))]),
    el('tbody', {}, body),
  ])]);
}

// ------------------------------------------------------------ plan card

export function tradePlanCard(root, state) {
  const sizing = state.sizing || {};
  const nodes = {};
  const number = (key, value = '', placeholder = '') => {
    nodes[key] = el('input', { type: 'number', step: 'any', value, placeholder });
    return nodes[key];
  };
  const side = el('select', {}, [el('option', { value: 'long', text: 'LONG' }), el('option', { value: 'short', text: 'SHORT' })]);
  side.value = sizing.side === 'short' ? 'short' : 'long';

  const priceRow = [field('SIDE', side),
    field('ENTRY ($)', number('entry')),
    field('STOP ($)', number('stop', sizing.stop ?? '')),
    field('TARGET ($)', number('target')),
    field('HORIZON (SESSIONS)', number('horizon', '10')),
    field('SHARES (OPTIONAL)', number('shares', sizing.shares ? String(sizing.shares) : ''))];
  const costRow = [field('COMMISSION ($ / SHARE / SIDE)', number('commission', '0')),
    field('SLIPPAGE (BPS / SIDE)', number('slippageBps', sizing.spreadBps ?? '')),
    field('P · TARGET HIT (%)', number('pTarget')),
    field('P · STOP HIT (%)', number('pStop')),
    field('P · HORIZON ENDS (%)', number('pTime')),
    field('HORIZON-END RETURN (%)', number('timeReturnPct', '', '0'))];

  const thesis = {
    why: el('textarea', { rows: '3', class: 'plan-text', placeholder: 'The setup, in your words' }),
    evidence: el('textarea', { rows: '3', class: 'plan-text', placeholder: 'What you looked at; if nothing was tested, say so' }),
    whatWouldProveWrong: el('textarea', { rows: '3', class: 'plan-text', placeholder: 'A price, a date or a fact that would end the thesis' }),
  };
  const headRight = el('span', { class: 'dim', text: 'loading…' });
  const messages = el('div', {});
  const outBox = el('div', {});
  const chartNode = el('div', { class: 'chart plan-heat' });
  const priceNode = el('div', { class: 'chart', style: 'height:250px' });
  const outcomeNode = el('div', { class: 'chart', style: 'height:150px' });
  const visualBox = el('div', {});
  const sensitivityBox = el('div', {});
  const exportStatus = el('div', { class: 'stat-note' });
  const copyBox = el('div', {});

  let entryEdited = false;   // the user typed an entry for this ticker: a new close does not overwrite it
  let lastSymbol = null;
  let draftApplied = false;

  const readInput = () => ({
    side: side.value, entry: nodes.entry.value, stop: nodes.stop.value, target: nodes.target.value,
    horizon: nodes.horizon.value, shares: nodes.shares.value, commission: nodes.commission.value,
    slippageBps: nodes.slippageBps.value, pTarget: readPct(nodes.pTarget), pStop: readPct(nodes.pStop),
    pTime: readPct(nodes.pTime), timeReturnPct: nodes.timeReturnPct.value,
  });
  const readThesis = () => ({ why: thesis.why.value, evidence: thesis.evidence.value,
    whatWouldProveWrong: thesis.whatWouldProveWrong.value });
  const fieldValues = () => ({ side: side.value, ...Object.fromEntries(Object.entries(nodes).map(([k, n]) => [k, n.value])) });

  const paint = () => {
    const input = readInput();
    const model = planOutcomes(input);
    // A blank plan is not wrong yet: the errors wait until a stop or a target is typed.
    const started = Boolean(nodes.stop.value.trim() || nodes.target.value.trim());
    messages.replaceChildren(...(started ? model.errors : []).map((e) => notice(e)));
    if (!model.target) {
      outBox.replaceChildren(info('Enter the side, entry, stop, target, horizon and costs to see the outcomes.'));
      sensitivityBox.replaceChildren();
      return;
    }
    const withTime = model.breakevenWithTime;
    const withTimeText = withTime ? (withTime.feasible ? pctText(withTime.successRate) : 'no split reaches breakeven')
      : (model.weights ? DASH : 'needs the three weights');
    const withTimeNote = withTime && withTime.feasible ? `target share of resolved trades ${pctText(withTime.targetShare)}`
      : (model.weights ? null : 'enter all three weights');
    const roundTrip = `round-trip cost a share: target ${num(model.target.costPerShare, 2)}, stop ${num(model.stop.costPerShare, 2)}`;
    const bars = state.reference?.ohlcv;
    visualBox.replaceChildren(el('div', { class: 'grid two' }, [
      el('div', {}, [el('div', { class: 'card-title', text: 'THE PLAN ON THE PRICE · VOLUME BY PRICE, LAST 252 SESSIONS' }),
        bars?.dates?.length ? priceNode : info('No daily bars for this ticker, so no volume by price.'),
        info('Shaded: the loss zone to the stop and the gain zone to the target. The curve is where shares traded over the year, estimated from daily bars; heavy trading is not a support or a target.')]),
      el('div', {}, [el('div', { class: 'card-title', text: 'OUTCOMES IN R, AFTER COSTS · YOUR WEIGHTS' }), outcomeNode]),
    ]));
    requestAnimationFrame(() => {
      if (bars?.dates?.length) drawPlanPrice(priceNode, bars, input, state.reference?.price);
      drawOutcomes(outcomeNode, model);
    });
    outBox.replaceChildren(
      el('div', { class: `plan-headline ${model.breakevenSuccess > 1 ? 'down' : ''}`, text: breakevenHeadline(model.breakevenSuccess) }),
      visualBox,
      outcomeTable(model),
      el('div', { class: 'stat-strip' }, [
        stat('REWARD : RISK, AFTER COSTS', `${num(model.rewardRisk, 2)} : 1`, roundTrip),
        stat('BREAKEVEN SUCCESS', pctText(model.breakevenSuccess), 'horizon end ignored'),
        stat('BREAKEVEN WITH HORIZON END', withTimeText, withTimeNote),
      ]),
      // Smaller on purpose: it depends on the weights you typed, so it is not the headline.
      info(model.expected
        ? `Expected value from your weights, not a forecast: ${sR(model.expected.r)} · ${sMoney(model.expected.perShare)} a share${model.expected.position === null ? ' · enter shares for a $ position' : ` · ${sMoney(model.expected.position, 0)} position`}.`
        : 'Expected value from your weights, not a forecast: enter all three weights to see it.'),
      info('Costs: commission per share per side; slippage in bps of the price on each leg. R = the initial risk per share, |entry − stop|, before costs. The horizon end is your assumed position return, not a forecast.'),
    );
    const grid = planSensitivity(input);
    if (grid) {
      sensitivityBox.replaceChildren(chartNode, info('EV in R. Across: your success rate, with the horizon-end share held as entered. Down: the target distance as a multiple of yours. Red loses after costs, green gains: the colour change is the zero line. Blank: that success rate is impossible with your horizon share. Outlined: your point, at the nearest 5% column.'));
      requestAnimationFrame(() => drawSensitivity(chartNode, grid, model.weights?.pTarget ?? null));
    } else {
      sensitivityBox.replaceChildren(info('The sensitivity grid needs a valid plan, and weights that sum to 100% or are blank.'));
    }
  };
  const save = () => writeDraft({ ticker: state.reference?.symbol ?? null, fields: fieldValues(), thesis: readThesis() });
  const edit = () => { paint(); save(); };

  Object.entries(nodes).forEach(([key, node]) => node.addEventListener('input', () => {
    if (key === 'entry') entryEdited = true;
    edit();
  }));
  side.addEventListener('change', edit);
  Object.values(thesis).forEach((node) => node.addEventListener('input', edit));

  const applyDraft = (draft) => {
    Object.entries(nodes).forEach(([key, node]) => { if (typeof draft.fields?.[key] === 'string') node.value = draft.fields[key]; });
    if (draft.fields?.side) side.value = draft.fields.side === 'short' ? 'short' : 'long';
    thesis.why.value = draft.thesis?.why ?? '';
    thesis.evidence.value = draft.thesis?.evidence ?? '';
    thesis.whatWouldProveWrong.value = draft.thesis?.whatWouldProveWrong ?? '';
    entryEdited = true;
  };
  // Runs when the page loads a ticker, and at build when one is already loaded.
  const onReference = () => {
    const ref = state.reference;
    if (ref) {
      headRight.textContent = `${ref.symbol} · data as of ${ref.asOf ?? DASH}`;
      const draft = readDraft();
      if (!draftApplied && draft?.ticker === ref.symbol) {
        applyDraft(draft);
        draftApplied = true;
      } else if (ref.symbol !== lastSymbol || !entryEdited) {
        nodes.entry.value = String(ref.price);
        entryEdited = false;
      }
      lastSymbol = ref.symbol;
    }
    paint();
  };
  state.onPlan = onReference;

  const useClose = el('button', { class: 'action', text: 'ENTRY = LAST CLOSE', onclick: () => {
    if (!state.reference) return;
    nodes.entry.value = String(state.reference.price);
    entryEdited = false;
    edit();
  } });
  // Stop and shares come from the sizing calculator above, read as it stands now.
  const fromSizing = el('button', { class: 'action', text: 'STOP & SHARES FROM SIZING', onclick: () => {
    const current = state.sizing;
    if (!current) return;
    side.value = current.side === 'short' ? 'short' : 'long';
    nodes.stop.value = current.stop ?? '';
    nodes.shares.value = current.shares ? String(current.shares) : '';
    edit();
  } });

  // Export: the same plan object feeds the file and the Markdown, and refuses an invalid plan.
  const planForExport = () => {
    const ref = state.reference;
    if (!ref) { exportStatus.textContent = 'Load a ticker first.'; return null; }
    if (!planOutcomes(readInput()).ok) { exportStatus.textContent = 'Fix the errors above before exporting.'; return null; }
    const created = new Date().toISOString();
    return planToJson({ ticker: ref.symbol, created, dataAsOf: ref.asOf ?? null, input: readInput(), thesis: readThesis() });
  };
  const downloadPlan = el('button', { class: 'action', text: 'DOWNLOAD PLAN (JSON)', onclick: () => {
    const plan = planForExport();
    if (!plan) return;
    download(planFileName('plan', plan.ticker, plan.created), JSON.stringify(plan, null, 2));
    clearDraft();
    exportStatus.textContent = 'Downloaded. Nothing was sent, and the draft in this browser is cleared.';
  } });
  const copyPlan = el('button', { class: 'action', text: 'COPY AS MARKDOWN', onclick: () => {
    const plan = planForExport();
    if (plan) copyText(planMarkdown(plan), exportStatus, copyBox);
  } });

  root.append(card('TRADE PLAN', headRight, [
    info('Your assumptions, not a forecast. No historical success rate is filled in: none of these entry/exit rules has been tested.'),
    el('div', { class: 'field-row' }, priceRow),
    el('div', { class: 'field-row' }, costRow),
    el('div', { class: 'field-row' }, [useClose, fromSizing]),
    messages,
    outBox,
    sensitivityBox,
    el('div', { class: 'plan-thesis' }, [
      field('WHY THIS TRADE', thesis.why),
      field('EVIDENCE', thesis.evidence),
      field('WHAT WOULD PROVE IT WRONG', thesis.whatWouldProveWrong),
    ]),
    el('div', { class: 'field-row' }, [downloadPlan, copyPlan]),
    exportStatus,
    copyBox,
    info('Kept on this device and sent nowhere: the file is yours to share or not. A blank field is not entered, never zero.'),
  ]));

  reviewCard(root);
  journalCard(root);
  onReference();
}

// ------------------------------------------------------------ review card

function reviewCard(root) {
  let loaded = null;
  const fileInput = el('input', { type: 'file', accept: 'application/json,.json' });
  const loadStatus = el('div', { class: 'stat-note' });
  const summary = el('div', { class: 'note-text' });
  const fields = {
    entry: el('input', { type: 'number', step: 'any', placeholder: 'actual fill' }),
    exit: el('input', { type: 'number', step: 'any', placeholder: 'actual fill' }),
    shares: el('input', { type: 'number', step: 'any', placeholder: 'plan shares' }),
    costs: el('input', { type: 'number', step: 'any', placeholder: '0 if none' }),
  };
  const options = (values) => values.map((v) => el('option', { value: v, text: v || '—' }));
  const followed = el('select', {}, options(['', 'yes', 'partly', 'no']));
  const thesisOutcome = el('select', {}, options(['', 'supported', 'refuted', 'unclear']));
  const whatChanged = el('textarea', { rows: '3', class: 'plan-text', placeholder: 'What you did differently from the plan, and why' });
  const result = el('div', {});
  const status = el('div', { class: 'stat-note' });
  const copyBox = el('div', {});

  const reviewNow = () => {
    if (!loaded) {
      result.replaceChildren(info('Load a plan file to record what happened against it.'));
      return null;
    }
    const shares = toNumber(fields.shares.value) ?? loaded.input.shares ?? 1;
    const review = reviewToJson({
      plan: loaded,
      created: new Date().toISOString(),
      actual: { entry: toNumber(fields.entry.value), exit: toNumber(fields.exit.value), shares, costs: toNumber(fields.costs.value) },
      followedPlan: followed.value || null,
      whatChanged: whatChanged.value,
      thesisOutcome: thesisOutcome.value || null,
    });
    const r = review.result;
    result.replaceChildren(el('div', { class: 'stat-strip' }, [
      stat('REALISED, AFTER ACTUAL COSTS', r ? `${sMoney(r.realised_per_share)} a share` : DASH,
        r ? `${sMoney(r.realised_total, 0)} on ${num(shares, 0)} shares` : 'enter the fills and costs (0 if none)', dirClass(r?.realised_per_share)),
      stat("R · ÷ PLAN'S INITIAL RISK", r ? sR(r.r) : DASH,
        r ? `plan risk ${num(r.risk_per_share, 2)} a share, before costs` : null, dirClass(r?.r)),
    ]));
    return review;
  };
  Object.values(fields).forEach((node) => node.addEventListener('input', reviewNow));
  [followed, thesisOutcome].forEach((node) => node.addEventListener('change', reviewNow));
  whatChanged.addEventListener('input', reviewNow);

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      const parsed = readPlanFile(JSON.parse(await file.text()));
      loaded = parsed.ok ? parsed.plan : null;
      loadStatus.textContent = parsed.ok ? `Loaded ${file.name}.` : parsed.error;
      summary.textContent = parsed.ok
        ? `${loaded.ticker} · ${loaded.input.side} · entry ${loaded.input.entry} · stop ${loaded.input.stop} · target ${loaded.input.target} · planned ${loaded.input.shares ?? 'no'} shares · created ${loaded.created ?? DASH}`
        : '';
    } catch {
      loaded = null;
      loadStatus.textContent = 'That file is not readable JSON.';
      summary.textContent = '';
    }
    reviewNow();
  });

  const exportReview = (asMarkdown) => {
    const review = reviewNow();
    if (!review?.result) { status.textContent = 'Enter the actual entry, exit and costs first.'; return; }
    if (asMarkdown) {
      copyText(reviewMarkdown(review), status, copyBox);
    } else {
      download(planFileName('review', review.ticker, review.created), JSON.stringify(review, null, 2));
      status.textContent = 'Downloaded. Nothing was sent.';
    }
  };

  root.append(card('REVIEW · LOAD A PLAN', el('span', { class: 'dim', text: 'after the trade' }), [
    el('div', { class: 'field-row' }, [field('PLAN FILE (JSON)', fileInput)]),
    loadStatus,
    summary,
    el('div', { class: 'field-row' }, [
      field('ACTUAL ENTRY ($)', fields.entry), field('ACTUAL EXIT ($)', fields.exit),
      field('SHARES FILLED', fields.shares), field('ACTUAL COSTS ($, TOTAL)', fields.costs),
      field('FOLLOWED THE PLAN', followed), field('THESIS', thesisOutcome),
    ]),
    field('WHAT CHANGED', whatChanged),
    result,
    info("Judgement and execution are recorded separately. A loss can come from a sound decision, and a gain does not prove the reasoning. R is realised P&L after actual costs over the plan's initial risk per share."),
    el('div', { class: 'field-row' }, [
      el('button', { class: 'action', text: 'DOWNLOAD REVIEW (JSON)', onclick: () => exportReview(false) }),
      el('button', { class: 'action', text: 'COPY AS MARKDOWN', onclick: () => exportReview(true) }),
    ]),
    status,
    copyBox,
  ]));
  reviewNow();
}

// ------------------------------------------------------------ journal card

// The running total in R, one point per review in date order, with zero dashed.
function drawJournalCurve(node, rows, summary) {
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 44, right: 16, top: 12, bottom: 28 },
    tooltip: { ...option.tooltip, trigger: 'axis', valueFormatter: undefined,
      formatter: (items) => { const k = [].concat(items)[0].dataIndex; const x = rows[k];
        return `${x.date} · ${x.ticker}<br>this trade ${sR(x.r)} · total ${sR(summary.cumulative[k])}`; } },
    xAxis: { ...option.xAxis, type: 'category', data: rows.map((x, i) => `${i + 1}`), boundaryGap: false },
    yAxis: { ...option.yAxis, scale: true, axisLabel: { ...option.yAxis.axisLabel, formatter: (v) => `${num(v, 1)}R` } },
    series: [{
      type: 'line', name: 'Total R', data: summary.cumulative, showSymbol: rows.length < 40, symbolSize: 5,
      lineStyle: { color: p.accent, width: 1.6 }, itemStyle: { color: p.accent }, areaStyle: { color: p.accent, opacity: 0.12 },
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }], lineStyle: { color: p.faint, type: 'dashed' }, label: { show: false } },
    }],
  }));
}

// Each trade's R in half-R bins, gains and losses in their own colours.
function drawJournalSpread(node, rs) {
  const lo = Math.floor(Math.min(...rs, -1) * 2) / 2;
  const hi = Math.ceil(Math.max(...rs, 1) * 2) / 2;
  const edges = [];
  for (let e = lo; e < hi - 1e-9; e += 0.5) edges.push(e);
  const counts = edges.map((e) => rs.filter((r) => r >= e && r < e + 0.5).length);
  rs.filter((r) => r === hi).forEach(() => { counts[counts.length - 1] += 1; });
  render(node, (option, p) => ({
    ...option,
    grid: { ...option.grid, left: 30, right: 12, top: 12, bottom: 28 },
    xAxis: { ...option.xAxis, type: 'category', data: edges.map((e) => `${e >= 0 ? '+' : ''}${num(e, 1)}`), boundaryGap: true },
    yAxis: { ...option.yAxis, min: 0, minInterval: 1 },
    series: [{ type: 'bar', name: 'Trades', barCategoryGap: '15%',
      data: counts.map((c, k) => ({ value: c, itemStyle: { color: edges[k] >= 0 ? p.up : p.down, opacity: 0.8 } })) }],
  }));
}

// JOURNAL: several review files read together, in this browser only. The record in R, and
// the mean R split by execution (followed the plan) and by judgement (the thesis held),
// so a good result from a broken plan and a loss from a sound one stay visible.
function journalCard(root) {
  const fileInput = el('input', { type: 'file', accept: 'application/json,.json', multiple: '' });
  const status = el('div', { class: 'stat-note' });
  const body = el('div', {});
  const empty = () => body.replaceChildren(info('Load the review files you downloaded (several at once) to see your record in R. They are read in this browser and sent nowhere.'));

  fileInput.addEventListener('change', async () => {
    const files = [...(fileInput.files || [])];
    const parsed = [];
    let unreadable = 0;
    for (const file of files) {
      try { parsed.push(JSON.parse(await file.text())); } catch { unreadable += 1; }
    }
    const { rows, skipped } = readReviews(parsed);
    status.textContent = `${rows.length} reviews read${skipped + unreadable ? ` · ${skipped + unreadable} skipped (not a review, no result, or not JSON)` : ''}.`;
    const s = journalSummary(rows);
    if (!s) { empty(); return; }
    const curve = el('div', { class: 'chart', style: 'height:220px' });
    const spread = el('div', { class: 'chart', style: 'height:220px' });
    const split = (label, groups) => el('table', { class: 'data' }, [
      el('thead', {}, [el('tr', {}, [label, 'TRADES', 'MEAN R'].map((h) => el('th', { text: h })))]),
      el('tbody', {}, Object.entries(groups).filter(([, g]) => g.n).map(([k, g]) => el('tr', {}, [
        el('td', { text: k }), el('td', { text: num(g.n, 0) }), el('td', { class: dirClass(g.mean), text: sR(g.mean) }),
      ]))),
    ]);
    body.replaceChildren(
      el('div', { class: 'stat-strip' }, [
        stat('TRADES', num(s.n, 0), s.n < 20 ? 'under 20: a short record, read it loosely' : null),
        stat('EXPECTANCY', sR(s.expectancy), 'mean R a trade', dirClass(s.expectancy)),
        stat('GAINS', pctText(s.winRate, 0), `avg gain ${sR(s.avgWin)} · avg loss ${sR(s.avgLoss)}`),
        stat('TOTAL', sR(s.total), `worst fall from a high ${sR(s.maxDrawdown)}`, dirClass(s.total)),
      ]),
      el('div', { class: 'grid two' }, [
        el('div', {}, [el('div', { class: 'card-title', text: 'RUNNING TOTAL IN R, BY TRADE' }), curve]),
        el('div', {}, [el('div', { class: 'card-title', text: 'R PER TRADE' }), spread]),
      ]),
      el('div', { class: 'grid two' }, [
        el('div', {}, [el('div', { class: 'card-title', text: 'EXECUTION · FOLLOWED THE PLAN' }), split('FOLLOWED', s.byFollowed)]),
        el('div', {}, [el('div', { class: 'card-title', text: 'JUDGEMENT · THE THESIS' }), split('THESIS', s.byThesis)]),
      ]),
      info('R is each trade\'s realised result after costs over its plan\'s initial risk. A loss with the plan followed and the thesis refuted is a call that did not work; a gain with the plan broken is not evidence for the plan.'),
    );
    requestAnimationFrame(() => {
      drawJournalCurve(curve, rows, s);
      drawJournalSpread(spread, s.rs);
    });
  });

  root.append(card('JOURNAL · YOUR REVIEWS', el('span', { class: 'dim', text: 'read here, sent nowhere' }), [
    el('div', { class: 'field-row' }, [field('REVIEW FILES (JSON, SEVERAL)', fileInput)]),
    status,
    body,
  ]));
  empty();
}
