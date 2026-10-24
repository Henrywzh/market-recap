import { el, card, table, num, pct, sectionTitle, notice, DASH } from '../fmt.js';
import { resolveTicker } from '../routes.js';
import { finite, parseInput, prepareReverseInputs, scenarioValue, requiredMargin, impliedDiscountRate } from '../reverse-dcf-math.js';
import { historicalContext, scenarioCharts, marginReferenceState, industryComparators, openingGrowth, plausibleBox, growthWindow, marginScale } from '../reverse-dcf-context.js';
import { drawHistory, drawFrontier, drawSensitivity } from '../reverse-dcf-charts.js';
import { disposeWithin } from '../charts.js';
import { consensusGrowthRanges } from '../consensus-growth-ranges.js';

const BILLION = 1e9;
// 'ANALYST FY REVENUE GROWTH' -> 'analyst FY revenue growth' for use mid-sentence.
const sentence = (label) => label.toLowerCase().replace(/\bfy\b/g, 'FY').replace(/\b(\d+)y\b/g, '$1Y').replace(/\bcagr\b/g, 'CAGR');
const currency = (v) => finite(v) ? `$${num(v / BILLION, 2)}B` : DASH;

export default async function renderReverseDcf(root, data, manifest, ctx) {
  root.append(sectionTitle('REVERSE DCF', 'WHAT DOES THIS PRICE REQUIRE?'));
  const settings = data.reverse;
  if (!settings) {
    root.append(notice('Reverse DCF settings are absent from this build. Rebuild DCF metadata; the existing forward model remains available.'));
    return;
  }
  if (!Number.isInteger(settings.reference_years) || settings.reference_years < 1 || !Number.isInteger(settings.peer_min_count) || settings.peer_min_count < 1
      || !Number.isInteger(settings.peer_max_age_days) || settings.peer_max_age_days < 0
      || !['history_cagr_years', 'sensitivity_wacc_shifts_pp', 'sensitivity_investment_shifts_pp'].every((key) => Array.isArray(settings[key]) && settings[key].length)
      || !finite(settings.chart_growth_step_pct) || settings.chart_growth_step_pct <= 0) {
    root.append(notice('Historical reference / chart settings are absent from this metadata version. Rebuild DCF metadata; no fallback assumptions were invented. BUILD YOUR OWN remains available.'));
    return;
  }
  let valuation;
  let financials;
  try {
    [valuation, financials] = await Promise.all([ctx.loadArtifact('valuation'), ctx.loadArtifact('financials')]);
  } catch (error) {
    root.append(notice(`Reverse DCF inputs are unavailable: ${error.message}`));
    return;
  }
  if (!valuation.as_of || valuation.as_of !== financials.as_of) {
    root.append(notice('Price and financial artifact sessions differ. Reverse DCF is disabled until a consistent build is available.'));
    return;
  }
  if (manifest?.as_of && manifest.as_of !== valuation.as_of) {
    root.append(notice(`HISTORICAL INPUT SNAPSHOT · Inputs ${valuation.as_of}; page header ${manifest.as_of}. Not live; dates are not relabelled.`));
  }
  const rows = valuation.rows || [];
  if (!rows.length) { root.append(notice('No valuation records in this build.')); return; }
  const universe = new Map(rows.map((row) => [row.ticker, row]));
  const requested = resolveTicker(ctx.arg, (t) => universe.has(t));
  const symbol = requested || rows[0].ticker;
  const input = el('input', { id: 'reverse-ticker', value: symbol, list: 'reverse-tickers', size: '10', 'aria-label': 'Reverse DCF ticker' });
  const status = el('span', { class: 'field-note', role: 'status' });
  const host = el('div', { class: 'reverse-dcf' });
  const list = el('datalist', { id: 'reverse-tickers' }, rows.map((row) => el('option', { value: row.ticker, text: row.name })));
  root.append(card('COMPANY', el('span', { class: 'dim', text: `Price session ${valuation.as_of} · not live` }), [
    el('div', { class: 'field-row' }, [input, el('button', { type: 'button', class: 'action', text: 'LOAD', onclick: () => load() }), status, list]),
  ]));
  root.append(host);
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') load(); });
  let request = 0;
  async function load() {
    const token = ++request;
    const next = resolveTicker(input.value.trim().toUpperCase(), (t) => universe.has(t));
    disposeWithin(host);
    host.replaceChildren();
    const row = universe.get(next);
    if (!row) { status.textContent = 'Ticker not covered by this valuation build; no replacement ticker was selected.'; return; }
    input.value = next;
    status.textContent = `Loading ${next}…`;
    try {
      // Avoid requesting files explicitly skipped by the current extractor.
      if (!financials.available?.some((entry) => entry.ticker === next)) throw new Error(financials.skipped?.[next] || 'Annual statements were not extracted for this ticker.');
      const annual = await ctx.loadArtifact(`financials/${next}`);
      if (token !== request || host.isConnected === false) return;
      const prepared = prepareReverseInputs(row, annual, valuation.as_of, settings);
      status.textContent = `${row.name} · ${row.sub_sector || row.sector}`;
      ctx.arg = next;
      ctx.setArg?.(next);
      if (prepared.issues.length) {
        host.append(card('OPERATING TEMPLATE NOT AVAILABLE', null, prepared.issues.map((text) => el('p', { class: 'gap', text }))));
        return;
      }
      renderModel(host, row, annual, prepared, settings, valuation.as_of, rows, data.risk_free_rate);
    } catch (error) {
      if (token !== request) return;
      status.textContent = `${next}: ${error.message}`;
      host.append(notice('No calculation is shown. Missing statements are not replaced with zeros or another company.'));
    }
  }
  await load();
}

function renderModel(root, row, annual, facts, cfg, asOf, universeRows, riskFree) {
  const history = historicalContext(annual, asOf, cfg);
  const opening = openingGrowth(row.revenue_consensus, history, cfg.growth_pct);
  const box = plausibleBox(row.revenue_consensus, history);
  const state = {
    ev: facts.workingEv === null ? null : facts.workingEv / BILLION,
    growth: opening.value, margin: Number((facts.margin * 100).toFixed(1)),
    wacc: cfg.wacc_pct, tax: cfg.tax_pct,
    netInvestment: cfg.net_investment_pct,
    terminalGrowth: cfg.terminal_growth_pct, terminalRoic: cfg.terminal_roic_pct,
    years: cfg.years, transitionYears: cfg.margin_transition_years,
  };
  const initial = { ...state };
  const inputs = new Map();
  const origins = new Map();
  const peers = industryComparators(universeRows, row, asOf, cfg.peer_min_count, cfg.peer_max_age_days);
  let chartVersion = 0;
  let historyMetric = 'margin';
  root.append(el('p', { class: 'reverse-purpose', text: 'Reads the price backwards: the discount rate, growth and margin it takes to justify today\'s enterprise value. Scenarios to compare with the company\'s own evidence, not forecasts or a cheap / expensive verdict.' }));
  const stat = (label, value, note) => el('div', { class: 'stat' }, [
    el('div', { class: 'stat-label', text: label }), el('div', { class: 'stat-value', text: value }), el('div', { class: 'stat-note', text: note }),
  ]);
  const factsStrip = el('div', { class: 'stat-strip' }, [
    stat('LAST CLOSE', finite(row.price) ? `$${num(row.price)}` : DASH, asOf),
    stat('ANNUAL REVENUE', currency(facts.revenue), `Period end ${facts.column.period_end}`),
    stat('OPERATING MARGIN', `${num(facts.margin * 100, 1)}%`, 'Reported annual EBIT / revenue'),
    stat('PUBLISHED EV PROXY', currency(facts.workingEv), 'Cash / debt / claims not independently reconciled'),
  ]);
  const resultHost = el('div', { class: 'reverse-results', 'aria-live': 'polite' });
  const gridHost = el('div', {});
  const pathHost = el('div', {});
  const checkHost = el('div', { class: 'reverse-checks', 'aria-live': 'polite' });
  const evidenceHost = el('div', { class: 'reverse-evidence', id: 'reverse-evidence' });
  const evidenceModelNote = el('p', { class: 'note-text' });
  const historyChart = el('div', { class: 'reverse-chart', role: 'img', 'aria-label': 'Reported annual history and separate hypothetical model-year path' });
  const frontierChart = el('div', { class: 'reverse-chart', role: 'img', 'aria-label': 'Revenue growth versus required operating margin at different discount rates' });
  const sensitivityChart = el('div', { class: 'reverse-chart', role: 'img', 'aria-label': 'Enterprise value sensitivity to WACC and net reinvestment assumptions' });
  const chartData = el('div', {});
  const assumptionSummary = el('p', { class: 'reverse-assumptions', id: 'reverse-assumption-summary' });
  const sensitivitySummary = el('p', { class: 'reverse-sensitivity-summary', id: 'reverse-sensitivity-summary' });
  const valuationDetails = el('div', { class: 'reverse-valuation-details' });
  const formatPercent = (v) => finite(v) ? `${num(v, 1)}%` : DASH;
  const rangeText = (stats) => stats.n ? `${formatPercent(stats.min)}–${formatPercent(stats.max)}; median ${formatPercent(stats.median)} (${stats.n} annual observations)` : 'Unavailable';
  const cagrText = history.cagr.map((c) => `${c.years}Y CAGR ${formatPercent(c.value)}`).join(' · ');
  const references = {
    growth: `Opens at ${sentence(opening.origin)}${opening.note ? ` (${opening.note})` : ''}, held for the horizon. Company history: ${cagrText}.`,
    margin: `Last ${cfg.reference_years} available fiscal years: ${rangeText(history.margin)}. Reported, not normalised.`,
    wacc: 'No company-specific WACC estimate is supplied. Compare discount-rate scenarios below.',
    netInvestment: `Historical gross cash CapEx: ${rangeText(history.capex)} of revenue. This is NOT net reinvestment; operating ΔNWC and leases are not reconciled.`,
  };
  const field = (key, label, unit, note, { step = '0.5', min = null, max = null } = {}) => {
    const control = el('input', {
      id: `reverse-${key}`, type: 'number', inputmode: 'decimal', step, min, max,
      value: state[key] ?? '', 'aria-label': label,
    });
    inputs.set(key, control);
    const origin = el('span', { class: 'reverse-origin' });
    origins.set(key, origin);
    control.addEventListener('input', () => { state[key] = parseInput(control.value); update(); });
    return el('div', { class: 'field' }, [
      el('label', { for: `reverse-${key}`, text: `${label} (${unit})` }), origin, control,
      note ? el('span', { class: 'sub', text: note }) : null,
      references[key] ? el('span', { class: 'reverse-reference', text: references[key] }) : null,
    ]);
  };
  const mainControls = el('div', { class: 'field-row reverse-controls' }, [
    field('growth', 'Revenue growth', '% / year', 'Held for the explicit forecast horizon', { min: -99, max: 100 }),
    field('margin', 'Sustainable operating margin', '%', 'Starts at the reported margin, then transitions', { min: 0, max: 100 }),
    field('wacc', 'WACC', '%', 'Assumed discount rate; not inferred from price', { min: 0.1, max: 50 }),
    field('netInvestment', 'Net reinvestment', '% of revenue', 'Net CapEx + operating ΔNWC, not gross cash CapEx', { min: 0, max: 100 }),
  ]);
  const details = el('details', { class: 'method-fold' }, [
    el('summary', { text: 'Terminal, tax, horizon & EV assumptions' }),
    el('div', { class: 'field-row reverse-controls' }, [
      field('tax', 'Operating tax', '%', 'Future assumption, not reported cash tax', { min: 0, max: 99 }),
      field('terminalGrowth', 'Terminal growth', '%', 'Below WACC and terminal ROIC', { min: 0 }),
      field('terminalRoic', 'Terminal ROIC', '%', 'Stable reinvestment = NOPAT × growth / ROIC', { min: 0, max: 100 }),
      field('years', 'Forecast horizon', 'years', 'Growth changes to terminal growth after this horizon', { step: '1', min: 1, max: 30 }),
      field('transitionYears', 'Margin transition', 'years', 'Linear transition to sustainable operating margin', { step: '1', min: 1, max: 30 }),
      field('ev', 'Working enterprise value', '$B', facts.evReason || 'Editable published EV proxy; enter a reviewed EV including appropriate claims.', { step: '1', min: 0 }),
    ]),
  ]);
  const reset = el('button', { type: 'button', class: 'action', text: 'RESET ASSUMPTIONS', onclick: () => {
    Object.assign(state, initial);
    inputs.forEach((node, key) => { node.value = state[key] ?? ''; });
    update();
  } });
  const scenarioEditor = el('details', { class: 'method-fold reverse-editor', id: 'reverse-editor' }, [
    el('summary', { text: 'Edit assumptions · illustrative, not company forecasts' }),
    el('div', { class: 'reverse-editor-actions' }, [reset]), mainControls, details,
  ]);
  const historySelect = el('select', { id: 'reverse-history-metric', 'aria-label': 'Historical comparison metric' }, [
    el('option', { value: 'margin', text: 'Operating & gross margin' }),
    el('option', { value: 'growth', text: 'Revenue growth' }),
  ]);
  historySelect.addEventListener('change', () => { historyMetric = historySelect.value; update(); });
  const historyDescription = el('p', { class: 'note-text' });
  const historyFold = el('details', { class: 'method-fold reverse-chart-fold', id: 'reverse-history-fold' }, [
    el('summary', { text: 'Explore history & scenario path' }), historySelect, historyDescription,
    historyChart,
    el('details', { class: 'method-fold' }, [el('summary', { text: 'Inspect historical inputs & filing dates' }),
      table(['PERIOD END', 'FILED', 'REVENUE ($B)', 'YOY GROWTH', 'GROSS MARGIN', 'OP MARGIN', 'CASH CAPEX / SALES'], history.rows.map((r) => el('tr', {}, [r.period_end, r.filed, finite(r.revenue) ? num(r.revenue / BILLION, 2) : DASH, formatPercent(r.growth), formatPercent(r.grossMargin), formatPercent(r.operatingMargin), formatPercent(r.capexShare)].map((text) => el('td', { text }))))),
    ]),
  ]);
  historyFold.open = true;
  const primaryCagr = history.cagr.at(-1);
  root.append(card('01 · WHAT HAS THE COMPANY DELIVERED?', el('span', { class: 'dim', text: `Annual through ${facts.column.period_end}` }), [
    el('div', { class: 'stat-strip reverse-key-stats' }, [
      stat(`${primaryCagr.years}Y REVENUE CAGR`, formatPercent(primaryCagr.value), finite(primaryCagr.value) ? `${primaryCagr.start} → ${primaryCagr.end}` : `Needs ${primaryCagr.years + 1} complete annual revenue observations`),
      stat('MEDIAN OPERATING MARGIN', formatPercent(history.margin.median), history.margin.n ? `${history.margin.n}/${cfg.reference_years} annual observations · range ${formatPercent(history.margin.min)}–${formatPercent(history.margin.max)}` : 'Annual EBIT / revenue unavailable'),
    ]),
    historyFold,
  ]));
  root.append(card('02 · WHAT DOES THIS PRICE REQUIRE?', el('span', { class: 'dim', text: 'Scenario, not forecast' }), [
    resultHost, assumptionSummary, checkHost, scenarioEditor,
    el('p', { class: 'reverse-chart-guide', text: 'READ THE CHART · each curve is the margin the price requires at that growth, for one WACC. Shaded box: near-term analysts\' growth ranges × historical reported margins. These cover different horizons: their intersection is not a validated long-term scenario or a probability region.' }),
    frontierChart,
    el('p', { class: 'note-text', text: 'Diamond: your scenario (above its curve, model EV exceeds working EV). Dotted line: median reported margin. Gaps lie outside the solve range.' }),
    evidenceHost,
  ]));
  const sensitivityFold = el('details', { class: 'method-fold reverse-chart-fold', id: 'reverse-sensitivity-fold' }, [
    el('summary', { text: 'Compare discount-rate & reinvestment scenarios' }),
    el('p', { class: 'note-text', text: 'Growth and target margin stay fixed. Compare the lines with dotted working EV. Invalid combinations remain gaps; these are scenario ranges, not confidence intervals.' }), sensitivityChart,
  ]);
  root.append(card('03 · HOW SENSITIVE IS THE ANSWER?', null, [sensitivitySummary, sensitivityFold]));
  historyFold.addEventListener('toggle', update);
  sensitivityFold.addEventListener('toggle', update);
  const audit = [];
  audit.push(el('details', { class: 'method-fold' }, [el('summary', { text: 'Inspect curve & sensitivity values' }), chartData]));
  audit.push(el('details', { class: 'method-fold' }, [el('summary', { text: 'Valuation details · implied rate, EV & terminal dependence' }), valuationDetails]));
  audit.push(el('details', { class: 'method-fold' }, [el('summary', { text: 'Growth × margin scenario grid · enterprise-value gaps' }),
    el('p', { class: 'note-text', text: 'Pick a cell to inspect that scenario. These are enterprise-value gaps, not expected stock returns. A positive gap does not establish that the stock is cheap.' }), gridHost,
  ]));
  audit.push(el('details', { class: 'method-fold' }, [el('summary', { text: 'Forecast cash-flow path & terminal dependence' }), pathHost]));
  audit.push(el('details', { class: 'method-fold' }, [el('summary', { text: 'Sources, accounting boundaries & method' }),
    el('div', { class: 'method-copy' }, [
      factsStrip,
      el('p', { text: 'Opening growth is the analysts\' later fiscal-year revenue growth (else the longest reported CAGR, else the shared default), held flat for the horizon: a scenario anchored to the company, not a ten-year forecast. Other opening assumptions are shared defaults, not company-specific estimates. Forward operating-margin consensus and reviewed company guidance are not in this data set, so revenue expectations alone cannot establish whether a required margin is realistic. No comparable forward operating-margin consensus or business-model-matched peer benchmark is supplied. GICS comparators are historical context, not validated business-model matches. Historical ranges are not confidence intervals or probabilities.' }),
      el('p', { text: `Price / published EV: dashboard valuation artifact, session ${asOf}. Balance period ${row.period_end}; last filed ${row.filed}. Debt basis: ${row.debt_basis || 'unknown'}. Annual period ${facts.column.period_end}; last filed ${facts.column.filed}.` }),
      el('p', { text: `Published EV less market cap: ${currency(facts.netClaims)}. This is the artifact's aggregate net-claims proxy, not a newly verified cash/debt/preferred/minority bridge. Editable EV is explicitly a working assumption.` }),
      annual.source_url ? el('a', { href: annual.source_url, text: 'SEC company facts', target: '_blank', rel: 'noopener' }) : null,
      ...facts.warnings.map((text) => el('p', { text })),
      el('p', { text: 'The implied discount rate solves model EV = working EV for the rate, with growth, margin, tax, reinvestment and terminal assumptions held. It is an enterprise-level rate, not an expected share return.' }),
      el('p', { text: 'Explicit FCF = revenue × operating margin × (1 − tax) − net reinvestment. SBC stays in operating profit, with no addback. Growth and explicit reinvestment remain independent assumptions, not a validated growth-capital feasibility model. At the horizon, reinvestment switches to terminal NOPAT × terminal growth / terminal ROIC. Discounting uses end-of-year cash flows. Financing, future issuance and segment-specific economics are not modelled.' }),
    ]),
  ]));
  root.append(card('DETAILS & AUDIT', null, audit));
  // Put the most consequential accounting warning beside the controls too.
  if (facts.capexShare !== null && facts.capexShare >= cfg.capital_warning_share) {
    mainControls.after(el('p', { class: 'note-text reverse-caution', text: facts.warnings[0] }));
  }
  if (facts.evReason) { scenarioEditor.open = true; details.open = true; }

  function scenario() {
    return {
      revenue: facts.revenue, baseMargin: facts.margin,
      growth: state.growth === null ? null : state.growth / 100,
      margin: state.margin === null ? null : state.margin / 100,
      wacc: state.wacc === null ? null : state.wacc / 100,
      tax: state.tax === null ? null : state.tax / 100,
      netInvestment: state.netInvestment === null ? null : state.netInvestment / 100,
      terminalGrowth: state.terminalGrowth === null ? null : state.terminalGrowth / 100,
      terminalRoic: state.terminalRoic === null ? null : state.terminalRoic / 100,
      years: state.years, transitionYears: state.transitionYears,
    };
  }
  function renderEvidence() {
    evidenceHost.replaceChildren();
    const consensus = row.revenue_consensus;
    evidenceHost.append(el('h3', { class: 'reverse-evidence-title', text: 'WHAT CAN YOU COMPARE AGAINST?' }));
    evidenceHost.append(evidenceModelNote);
    if (consensus?.periods?.length && consensus.observed_at && consensus.observed_market_date) {
      const later = consensus.observed_market_date > asOf;
      evidenceHost.append(el('p', { class: later ? 'note-text reverse-caution' : 'note-text', text: `${consensus.source} · fetched ${consensus.observed_at.slice(0, 10)}${later ? `, after the ${asOf} price session` : ''}. Fetch time, not the estimates' revision time.` }));
      evidenceHost.append(consensusGrowthCards(consensus.periods));
      evidenceHost.append(el('p', { class: 'note-text', text: 'Growth is on Yahoo’s own prior-year base. Low–high is analyst dispersion, not a probability interval.' }));
      if (consensus.periods.some((p) => p.range_issue)) evidenceHost.append(el('p', { class: 'note-text reverse-caution', text: 'An inconsistent vendor estimate range was withheld; the mean was retained.' }));
      evidenceHost.append(el('a', { href: `https://finance.yahoo.com/quote/${encodeURIComponent(row.ticker)}/analysis/`, target: '_blank', rel: 'noopener', text: 'Yahoo analyst estimates ↗' }));
    } else evidenceHost.append(el('p', { class: 'gap', text: 'Dated FY revenue consensus unavailable. Missing forecasts are not replaced with EPS growth or historical growth.' }));
    evidenceHost.append(el('p', { class: 'note-text', text: `INDUSTRY ACTUALS · ${row.sub_sector} · ${peers.usable}/${peers.candidates} other issuers with a dated TTM operating margin ≤ ${peers.maximumAgeDays} days old. ${peers.thin ? `Thin sample: fewer than ${peers.minimum}; no peer median shown.` : `Median ${formatPercent(peers.median)}.`} GICS comparators, not validated business-model peers.` }));
    const companyActual = finite(row.operating_margin) ? [row] : [];
    evidenceHost.append(el('details', { class: 'method-fold' }, [el('summary', { text: 'Inspect company & industry actual margins' }),
      table(['ISSUER', 'TTM OP MARGIN', 'PERIOD END', 'FILED'], [...companyActual, ...peers.members].map((peer) => el('tr', {}, [
        `${peer.ticker}${peer.ticker === row.ticker ? ' · selected company' : ''}`, formatPercent(peer.operating_margin), peer.period_end, peer.filed,
      ].map((text) => el('td', { text }))))),
      el('p', { class: 'note-text', text: `Valuation artifact ${asOf}. Selected issuer / duplicate share classes excluded from peer statistics; missing, stale, future-dated or lagged revenue / EBIT inputs excluded. TTM periods differ by issuer and are not the annual-history median above.` }),
    ]));
  }
  function update() {
    const version = ++chartVersion;
    resultHost.replaceChildren(); gridHost.replaceChildren(); pathHost.replaceChildren(); checkHost.replaceChildren(); chartData.replaceChildren(); valuationDetails.replaceChildren();
    for (const node of [historyChart, frontierChart, sensitivityChart]) { disposeWithin(node); node.replaceChildren(); }
    origins.forEach((node, key) => {
      node.textContent = state[key] !== initial[key] ? 'USER SCENARIO' : key === 'margin' ? 'COMPANY HISTORY · STARTING SEED' : key === 'ev' ? (initial.ev === null ? 'MISSING PROXY · REVIEW REQUIRED' : 'PUBLISHED PROXY · UNREVIEWED') : key === 'growth' ? opening.origin : 'SHARED ILLUSTRATIVE DEFAULT';
      node.setAttribute('data-origin', state[key] !== initial[key] ? 'user' : key === 'margin' ? 'history' : key === 'ev' ? 'proxy' : key === 'growth' && opening.source !== 'default' ? opening.source : 'default');
    });
    evidenceModelNote.textContent = `Your scenario holds ${formatPercent(state.growth)} revenue growth for ${state.years ?? DASH} years; the fiscal-year consensus below covers only the next two years.`;
    const s = scenario();
    const value = scenarioValue(s);
    const edited = Object.keys(initial).some((key) => state[key] !== initial[key]);
    assumptionSummary.textContent = `${edited ? 'Edited scenario' : 'Opening scenario'} · Growth ${formatPercent(state.growth)} for ${state.years ?? DASH} years (${edited && state.growth !== initial.growth ? 'yours' : sentence(opening.origin)}) · WACC ${formatPercent(state.wacc)} · net reinvestment ${formatPercent(state.netInvestment)} of revenue · working EV ${finite(state.ev) ? currency(state.ev * BILLION) : DASH} (unreviewed). Change under Edit assumptions.`;
    sensitivitySummary.textContent = value.error || !finite(state.ev) || state.ev <= 0 ? 'Complete valid scenario inputs and working EV to inspect sensitivity.' : `TERMINAL PV / MODEL EV ${value.ev > 0 ? formatPercent(value.terminalPv / value.ev * 100) : DASH} · Value beyond the explicit horizon. This measures model dependence, not probability. Open the chart to see how discount and investment choices change the answer.`;
    historyDescription.textContent = `Solid: reported annual margins / growth through ${facts.column.period_end}. Dashed: your M1–M${state.years ?? '?'} scenario, not fiscal-year forecasts. NOW is the ${asOf} run-rate proxy. Filing vintage is the build's available version, not point-in-time history.`;
    const ev = finite(state.ev) && state.ev > 0 ? state.ev * BILLION : null;
    const valid = !value.error && ev !== null;
    const curves = valid ? scenarioCharts(s, ev, cfg, growthWindow(box, state.growth)) : null;
    // Initial tab rendering happens before attachment. Draw after mount, and
    // ignore queued renders after an edit or company change.
    if (typeof window !== 'undefined') requestAnimationFrame(() => {
      if (version !== chartVersion || !root.isConnected) return;
      if (!window.echarts) {
        for (const node of [historyChart, frontierChart, sensitivityChart]) node.append(notice('Chart runtime unavailable; inspect the numeric source tables.'));
        return;
      }
      if (historyFold.open) drawHistory(historyChart, history, s, value, historyMetric, asOf);
      if (valid) {
        drawFrontier(frontierChart, curves.frontier, history, s, cfg, box);
        if (sensitivityFold.open) drawSensitivity(sensitivityChart, curves.sensitivity, ev);
      } else {
        for (const node of [frontierChart, sensitivityChart]) node.append(notice('Complete valid assumptions and working EV to draw this chart.'));
      }
    });
    if (value.error || ev === null) {
      resultHost.append(notice(value.error || facts.evReason || 'Enter a positive working enterprise value.'));
      gridHost.append(el('div', { class: 'gap', text: 'No scenario map until every required input is valid.' }));
      checkHost.append(el('p', { text: `Historical context remains available: ${cagrText}; operating margin ${rangeText(history.margin)}. No scenario comparison until inputs are valid.` }));
      return;
    }
    const solved = requiredMargin(s, ev, cfg.margin_bounds_pct.map((v) => v / 100));
    const gap = (value.ev / ev - 1) * 100;
    const reference = solved.status === 'solved'
      ? marginReferenceState(solved.value * 100, history.margin, cfg.reference_years)
      : { tone: 'neutral', label: 'REQUIRED MARGIN OUTSIDE SOLVE RANGE' };
    const implied = impliedDiscountRate(s, ev);
    const impliedPct = implied.status === 'solved' ? implied.value * 100 : null;
    const impliedStat = stat('IMPLIED DISCOUNT RATE', finite(impliedPct) ? formatPercent(impliedPct) : implied.status === 'below-range' ? `< ${formatPercent((s.terminalGrowth + 0.0005) * 100)}` : implied.status === 'above-range' ? '> 50%' : DASH,
      finite(impliedPct) && finite(riskFree) ? `10Y Treasury ${formatPercent(riskFree)} ${impliedPct >= riskFree ? '+' : '−'} ${num(Math.abs(impliedPct - riskFree), 1)} pp · at ${formatPercent(state.growth)} growth, ${formatPercent(state.margin)} margin`
        : `At ${formatPercent(state.growth)} growth and ${formatPercent(state.margin)} margin`);
    const requiredPct = solved.status === 'solved' ? solved.value * 100 : null;
    const versus = finite(requiredPct) && history.margin.n ? `${requiredPct >= history.margin.median ? '+' : '−'}${num(Math.abs(requiredPct - history.margin.median), 1)} pp vs own median` : null;
    const requiredStat = stat('REQUIRED MARGIN', finite(requiredPct) ? formatPercent(requiredPct) : 'OUTSIDE RANGE',
      `At ${formatPercent(state.growth)} growth and ${formatPercent(state.wacc)} WACC${versus ? ` · ${versus}` : ''}`);
    requiredStat.className = `stat reverse-reference-${reference.tone}`;
    resultHost.append(el('div', { class: 'stat-strip' }, [requiredStat,
      stat('SCENARIO OPERATING MARGIN', formatPercent(state.margin), 'Your assumption, not forward margin consensus. Historical median is a reference, not a target.'),
    ]));
    resultHost.append(marginBar(requiredPct, history, peers, reference));
    valuationDetails.append(el('div', { class: 'stat-strip' }, [
      impliedStat,
      stat('SELECTED SCENARIO EV', currency(value.ev), `${num(state.margin, 1)}% sustainable operating margin`),
      stat('ENTERPRISE VALUE GAP', `${pct(gap, 1)}`, 'Against working EV; not share-price upside'),
      stat('TERMINAL PV / MODEL EV', value.ev > 0 ? formatPercent(value.terminalPv / value.ev * 100) : DASH, 'Dependence on value beyond the explicit horizon'),
    ]));
    valuationDetails.append(el('p', { class: 'note-text', text: 'The implied rate is conditional on every operating assumption and applies to enterprise cash flows, not an expected equity return. Its difference from the Treasury yield is not an equity risk premium.' }));
    valuationDetails.append(el('p', { class: 'note-text', text: `Assumptions: ${state.years} forecast years · ${state.transitionYears}-year margin transition · operating tax ${num(state.tax, 1)}% · terminal growth ${num(state.terminalGrowth, 1)}% · terminal ROIC ${num(state.terminalRoic, 1)}%. All are editable scenario inputs, not estimates.` }));
    if (value.path.some((year) => year.fcf < 0)) resultHost.append(el('p', { class: 'note-text reverse-caution', text: 'This scenario has negative forecast free cash flow. External financing and dilution are not modelled.' }));
    if (solved.status !== 'solved') {
      checkHost.append(el('p', { text: `No margin inside ${cfg.margin_bounds_pct.join('–')}% supports the working EV at this growth rate under the other assumptions. No boundary value is substituted; inspect other growth / discount / investment combinations.` }));
    } else if (!history.margin.n) {
      checkHost.append(el('p', { text: 'The conditional margin requirement is available, but insufficient history prevents comparison with a historical median.' }));
    }
    const latestGross = history.rows.at(-1)?.grossMargin;
    if (finite(latestGross) && state.margin > latestGross) checkHost.append(el('p', { class: 'reverse-caution', text: `Target operating margin exceeds the latest reported gross margin (${formatPercent(latestGross)}). It would require higher gross margins / a changed business mix; the historical gross margin is not a hard future cap.` }));
    if (finite(latestGross) && solved.status === 'solved' && solved.value * 100 > latestGross) checkHost.append(el('p', { class: 'reverse-caution', text: `The price-required operating margin also exceeds the latest gross margin (${formatPercent(latestGross)}). This combination needs a changed margin structure or different growth / discount / investment assumptions; it does not establish a uniquely implied market forecast.` }));
    if (value.ev > 0 && value.terminalPv / value.ev > 1) checkHost.append(el('p', { class: 'reverse-caution', text: 'Terminal PV exceeds total model EV because explicit-period FCF detracts from value. No funding or dilution scenario is included.' }));
    chartData.append(table(['WACC', 'NET REINVESTMENT / SALES', 'MODEL EV ($B)', 'EV GAP', 'TERMINAL PV / EV'], curves.sensitivity.map((r) => el('tr', {}, [formatPercent(r.wacc * 100), formatPercent(r.netInvestment * 100), finite(r.ev) ? num(r.ev / BILLION, 2) : DASH, formatPercent(r.gap), formatPercent(r.terminalShare)].map((text) => el('td', { text }))))));
    chartData.append(table(['WACC', 'GROWTH / YEAR', 'REQUIRED OP MARGIN'], curves.frontier.flatMap((curve) => curve.points.map(([growth, margin]) => el('tr', {}, [formatPercent(curve.wacc * 100), formatPercent(growth), formatPercent(margin)].map((text) => el('td', { text })))))));
    const grid = cfg.margin_grid_pct.map((margin) => el('tr', {}, [
      el('th', { scope: 'row', text: `${num(margin, 0)}%` }),
      ...cfg.growth_grid_pct.map((growth) => {
        const cell = scenarioValue({ ...s, growth: growth / 100, margin: margin / 100 });
        const gapPct = cell.ev === null ? null : (cell.ev / ev - 1) * 100;
        const picked = state.growth === growth && state.margin === margin;
        return el('td', {}, [el('button', {
          type: 'button', class: `reverse-cell${finite(gapPct) && gapPct >= 0 ? ' reverse-covered' : ''}`,
          text: finite(gapPct) ? pct(gapPct, 0) : DASH,
          disabled: gapPct === null ? 'disabled' : null, 'aria-pressed': String(picked),
          'aria-label': `Growth ${growth}%, margin ${margin}%, enterprise value gap ${finite(gapPct) ? pct(gapPct, 1) : 'unavailable'}`,
          title: `Growth ${growth}%; margin ${margin}%; model EV ${currency(cell.ev)}`,
          onclick: () => {
            state.growth = growth; state.margin = margin;
            inputs.get('growth').value = growth; inputs.get('margin').value = margin;
            update();
          },
        })]);
      }),
    ]));
    gridHost.append(table(['MARGIN ↓ / GROWTH →', ...cfg.growth_grid_pct.map((g) => `${num(g, 0)}%`)], grid, { class: 'reverse-map' }));
    pathHost.append(el('p', { class: 'note-text', text: `PV of explicit FCF ${currency(value.explicitPv)} + PV of terminal value ${currency(value.terminalPv)}. Terminal share ${value.ev > 0 ? `${num(value.terminalPv / value.ev * 100, 1)}%` : DASH}; above 100% means explicit-period FCF detracts from value.` }));
    pathHost.append(table(['MODEL YEAR', 'REVENUE ($B)', 'OP MARGIN', 'NOPAT ($B)', 'NET INVESTMENT ($B)', 'FCF ($B)'], value.path.map((year) => el('tr', {}, [
      year.year, num(year.revenue / BILLION, 2), `${num(year.margin * 100, 1)}%`, num(year.nopat / BILLION, 2), num(year.reinvestment / BILLION, 2), num(year.fcf / BILLION, 2),
    ].map((text) => el('td', { text }))))));
  }
  renderEvidence();
  update();
}

export function consensusGrowthCards(periods) {
  const ranges = consensusGrowthRanges(periods);
  const percent = (v) => finite(v) ? `${num(v, 1)}%` : DASH;
  const cards = ranges.rows.map(({ period, mean, low, high, hasRange, invalid, geometry: g }) => {
    const reading = `${period.end || 'Fiscal year unknown'}: revenue growth ${percent(mean)}; analyst low ${percent(low)}, high ${percent(high)}. Analyst dispersion, not a confidence interval.`;
    return el('div', { class: 'reverse-consensus-card' }, [
      el('div', { class: 'reverse-consensus-head' }, [
        el('span', { text: `FY END ${period.end || DASH}` }),
        el('span', { text: `${finite(period.analysts) ? num(period.analysts, 0) : DASH} revenue analysts` }),
      ]),
      el('div', { class: 'reverse-consensus-mean' }, [
        el('strong', { text: percent(mean) }), el('span', { text: 'REVENUE GROWTH · CONSENSUS' }),
      ]),
      g && (mean !== null || hasRange) ? el('div', { class: 'ec-rbar-wrap', role: 'img', 'aria-label': reading }, [
        el('div', { class: 'ec-rbar' }, [
          hasRange ? el('div', { class: 'ec-rbar-box', style: `left:${g.lowAt}%;width:${g.width}%` }) : null,
          el('div', { class: 'ec-rbar-ref', style: `left:${g.zeroAt}%`, title: '0% revenue growth' }),
          mean !== null ? el('div', { class: 'ec-rbar-point', style: `left:${g.meanAt}%`, title: `Consensus ${percent(mean)}` }) : null,
        ]),
        el('div', { class: 'ec-rbar-labels' }, [
          el('span', { text: `LOW ${percent(low)}` }), el('span', { text: '┆ 0% growth' }), el('span', { text: `HIGH ${percent(high)}` }),
        ]),
      ]) : null,
      !hasRange ? el('p', { class: 'note-text', text: invalid ? 'Inconsistent analyst range withheld; no band drawn.' : 'Analyst low–high unavailable; no band inferred.' }) : null,
      mean === null ? el('p', { class: 'note-text', text: 'Mean growth unavailable; no consensus dot drawn.' }) : null,
    ]);
  });
  return el('div', { class: 'reverse-consensus' }, [
    el('div', { class: 'reverse-consensus-grid' }, cards),
    el('p', { class: 'note-text', text: `Blue band = analyst low–high · amber dot = consensus mean · dashed line = zero growth.${finite(ranges.min) ? ` Shared growth scale across fiscal years: ${percent(ranges.min)} to ${percent(ranges.max)}.` : ''} No probability or forecast accuracy is implied.` }),
  ]);
}

// One bar for the margin question: the company's reported range, its peers'
// actual margins and the price-required margin on a shared 0-to-top scale.
// The marker keeps the amber / blue / neutral reading of the stat above it.
export function marginBar(requiredPct, history, peers, reference) {
  const peerMargins = (peers.members || []).map((m) => m.operating_margin).filter(finite);
  const top = marginScale([requiredPct, history.margin.max, ...peerMargins]);
  const at = (v) => `${Math.max(0, Math.min(100, (v / top) * 100)).toFixed(1)}%`;
  const marks = [];
  if (history.margin.n) {
    marks.push(el('span', { class: 'reverse-bar-range', style: `left:${at(history.margin.min)};width:calc(${at(history.margin.max)} - ${at(history.margin.min)} + 2px)`,
      title: `Reported operating margin, last ${history.margin.n} years: ${num(history.margin.min, 1)}–${num(history.margin.max, 1)}%` }));
  }
  peerMargins.forEach((v, i) => marks.push(el('span', { class: 'reverse-bar-peer', style: `left:${at(v)}`, title: `${peers.members[i]?.ticker}: ${num(v, 1)}%` })));
  if (finite(requiredPct)) {
    marks.push(el('span', { class: `reverse-bar-required reverse-reference-${reference.tone}`, style: `left:${at(requiredPct)}`, title: `Required: ${num(requiredPct, 1)}%` }));
  }
  const legend = [
    history.margin.n ? `▮ own range ${num(history.margin.min, 1)}–${num(history.margin.max, 1)}%` : 'own range unavailable',
    peerMargins.length ? `● ${peerMargins.length} industry peer${peerMargins.length === 1 ? '' : 's'}` : null,
    finite(requiredPct) ? `◆ required ${num(requiredPct, 1)}% · ${reference.label}` : '◆ required margin outside the solve range',
  ].filter(Boolean).join(' · ');
  return el('div', { class: 'reverse-bar', role: 'img', 'aria-label': legend }, [
    el('div', { class: 'reverse-bar-track' }, marks),
    el('div', { class: 'reverse-bar-scale' }, [el('span', { text: '0%' }), el('span', { text: `${top}%` })]),
    el('div', { class: `reverse-bar-legend reverse-reference-key reverse-reference-${reference.tone}`, text: legend }),
  ]);
}
