import { el, card, num, pct, sectionTitle, notice, DASH } from '../fmt.js';
import { withSuggestions } from '../ticker-suggest.js';
import { resolveTicker } from '../routes.js';
import renderReverseDcf from './reverse-dcf.js';
import { viewTabs } from '../view-tabs.js';

const DCF_BASE = 'artifacts/dcf';
const M = 1e6;

// Sensitivity grid: percentage points around the computed WACC, and turns
// around the chosen exit multiple. Both are display choices, not model inputs.
const WACC_STEPS = [-1, -0.5, 0, 0.5, 1];
const EXIT_STEPS = [-2, -1, 0, 1, 2];

const HISTORICAL_ROWS = [
  { key: 'revenue', label: 'Revenue', bold: true },
  { key: 'revenue_growth', label: '% growth', derived: 'growth', of: 'revenue' },
  { key: 'ebit', label: 'EBIT', bold: true },
  { key: 'ebit_margin', label: '% margin', derived: 'ratio', of: 'ebit', over: 'revenue' },
  { key: 'taxes', label: 'Taxes', bold: true },
  { key: 'ebiat', label: 'EBIAT', sub: 'EBIT − taxes', bold: true, computed: true },
  { key: 'dep_amort', label: 'D&A', bold: true },
  { key: 'da_sales', label: '% of sales', derived: 'ratio', of: 'dep_amort', over: 'revenue' },
  { key: 'capex', label: 'CapEx', bold: true },
  { key: 'capex_sales', label: '% of sales', derived: 'ratio', of: 'capex', over: 'revenue' },
  { key: 'nwc_change', label: 'Change in NWC', sub: 'increase = use of cash', bold: true },
  { key: 'nwc_sales', label: '% of sales', derived: 'ratio', of: 'nwc_change', over: 'revenue' },
];

async function loadCompany(symbol) {
  const response = await fetch(`${DCF_BASE}/${symbol.toUpperCase()}.json`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`${symbol.toUpperCase()} was not baked into this build`);
  return response.json();
}

export default async function renderDcf(root, data, manifest, ctx = {}) {
  // Keep each mode's unsaved inputs when switching between the two tools.
  const tabs = viewTabs([['reverse', 'REVERSE DCF'], ['forward', 'BUILD YOUR OWN']], 'reverse', {
    label: 'DCF mode', idPrefix: 'dcf-mode',
    build: async (mode, pane) => {
      try {
        if (mode === 'reverse') await renderReverseDcf(pane, data, manifest, ctx);
        else await renderForwardDcf(pane, data, manifest, ctx);
      } catch (error) {
        pane.replaceChildren(notice(`DCF inputs unavailable: ${error.message}`));
      }
    },
  });
  root.append(tabs.nav, ...tabs.panes);
  await tabs.show('reverse');
}

async function renderForwardDcf(root, data, _manifest, ctx = {}) {
  root.append(sectionTitle('DISCOUNTED CASH FLOW', 'BUILD-YOUR-OWN MODEL · LEARNING TOOL'));
  root.append(notice(
    'For learning purposes only. This is a teaching model, not a target price or investment advice. '
    + 'Figures you do not edit are auto-filled from SEC filings; the assumptions and every forecast '
    + 'column are your own.',
  ));

  if (!data.available || !data.available.length) {
    root.append(el('div', { class: 'gap', text: 'No companies were baked in this build. Run the refresh command without --skip-sec.' }));
    return;
  }

  // A ticker page links here with its ticker; one this build did not bake
  // still opens, on the first company, with the reason in the status line.
  const wanted = resolveTicker(ctx.arg, (t) => data.available.includes(t));
  const requested = wanted && data.available.includes(wanted) ? wanted : null;
  const tickerInput = el('input', { id: 'dcf-ticker', value: requested || data.available[0], size: '8' });
  const tickerBox = withSuggestions(tickerInput, data.available, data.names || {}, () => load(), data.rank || []);
  const status = el('span', { class: 'field-note', text: `${data.available.length} companies available in this build.` });
  const host = el('div', {});

  root.append(card('COMPANY', null, [
    el('div', { class: 'field-row' }, [
      el('div', { class: 'field' }, [el('label', { text: 'TICKER' }), tickerBox]),
      el('button', { class: 'action', text: 'LOAD', onclick: () => load() }),
      status,
    ]),
  ]));
  root.append(host);

  async function load() {
    const symbol = resolveTicker(tickerInput.value.trim().toUpperCase(), (t) => data.available.includes(t));
    status.textContent = `Loading ${symbol}…`;
    try {
      const company = await loadCompany(symbol);
      host.innerHTML = '';
      buildModel(host, company, data);
      const missing = ctx.arg && !requested && symbol === data.available[0]
        ? ` · ${ctx.arg} is not among the ${data.available.length} companies this build baked for the DCF` : '';
      status.textContent = `${company.entity_name} · SEC through FY${company.fiscal_years[company.fiscal_years.length - 1]}${missing}`;
    } catch (error) {
      status.textContent = error.message;
    }
  }

  await load();
}

function buildModel(host, company, meta) {
  const years = company.fiscal_years;
  const lastYear = years[years.length - 1];
  const forecastYears = Array.from({ length: meta.forecast_years }, (_, i) => lastYear + i + 1);
  const hist = new Map(company.rows.map((row) => [row.fiscal_year, row]));

  // Assumptions, seeded from the artifact where a defensible figure exists
  // and left blank where it is genuinely the modeller's call.
  const assumptions = {
    rf: company.risk_free_rate ?? meta.risk_free_rate ?? null,
    beta: company.beta ?? null,
    erp: null,
    kd: null,
    tax: company.effective_tax_rate ?? null,
    exit: null,
  };
  const forecast = {};
  forecastYears.forEach((year) => {
    forecast[year] = { growth: null, margin: null, da: null, capex: null, nwc: null };
  });

  const assumptionInputs = el('div', { class: 'field-row' });
  const mkInput = (key, label, suffix, note) => {
    const input = el('input', { class: 'model', value: assumptions[key] ?? '', size: '6', style: 'width:72px;text-align:right' });
    input.addEventListener('input', () => {
      assumptions[key] = input.value === '' ? null : Number(input.value);
      recompute();
    });
    return el('div', { class: 'field' }, [
      el('label', { text: label }),
      el('div', {}, [input, el('span', { class: 'dim', text: ` ${suffix}` }), note ? el('span', { class: 'sub', text: note }) : null]),
    ]);
  };

  assumptionInputs.append(
    mkInput('rf', `RISK-FREE RATE (${meta.risk_free_tenor || '10Y'} UST)`, '%', company.risk_free_rate ? 'published par yield' : null),
    mkInput('beta', 'BETA', '', `weekly, ${Math.round((meta.beta_weeks || 104) / 52)}y vs ${meta.market_proxy || 'SPY'}`),
    mkInput('erp', 'EQUITY RISK PREMIUM', '%', 'your assumption'),
    mkInput('kd', 'COST OF DEBT', '%', 'your assumption'),
    mkInput('tax', 'TAX RATE', '%', company.effective_tax_rate ? 'ref: SEC effective' : null),
    mkInput('exit', 'EXIT MULTIPLE (EV/EBITDA)', 'x', 'your assumption'),
  );

  const waccLine = el('div', { class: 'note-text' });
  const modelHost = el('div', {});
  const bridgeHost = el('div', {});
  const sensitivityHost = el('div', {});

  host.append(card('ASSUMPTIONS', el('span', { class: 'dim', text: '— auto = SEC / Treasury / computed; all editable' }), [assumptionInputs, waccLine]));
  host.append(card('MODEL', el('span', { class: 'dim', text: '($ millions)' }), modelHost));
  host.append(el('div', { class: 'grid two' }, [
    card('TERMINAL VALUE & ENTERPRISE → EQUITY BRIDGE', null, bridgeHost),
    card('SENSITIVITY — implied price (WACC × exit multiple)', null, sensitivityHost),
  ]));
  host.append(el('div', { class: 'note-text', text: meta.note }));
  host.append(el('div', { class: 'note-text' }, [
    'Change in NWC is the year-over-year move in current assets less current liabilities as filed. ',
    'It does not strip out cash or short-term borrowings, so a company that simply banked cash will ',
    'show a working-capital build here. Line items the filer did not tag are left blank rather than ',
    'zero-filled — type over them to model them.',
  ]));

  // --- Model grid --------------------------------------------------------
  const inputCell = (year, field, suffix = '%') => {
    const input = el('input', { class: 'model', value: '', placeholder: '' });
    input.addEventListener('input', () => {
      forecast[year][field] = input.value === '' ? null : Number(input.value);
      recompute();
    });
    return el('td', {}, [el('div', { style: 'display:flex;align-items:center;gap:2px' }, [input, el('span', { class: 'dim', text: suffix })])]);
  };

  function histValue(year, key) {
    const row = hist.get(year);
    if (!row) return null;
    const value = row[key];
    return value === null || value === undefined ? null : value / M;
  }

  function buildGrid(results) {
    const head = el('tr', {}, [
      el('th', { text: 'Line item' }),
      ...years.map((y) => el('th', { text: String(y) })),
      ...forecastYears.map((y) => el('th', { style: 'color:var(--accent)', text: `${y}E` })),
    ]);

    const body = [];
    const push = (label, sub, cells, bold) => {
      body.push(el('tr', {}, [
        el('td', {}, [el('span', { style: bold ? 'font-weight:700' : 'font-style:italic;color:var(--text-dim)', text: label }), sub ? el('span', { class: 'sub', text: sub }) : null]),
        ...cells,
      ]));
    };

    const histCell = (value, digits = 0) => el('td', { text: value === null ? DASH : num(value, digits) });
    const pctCell = (value) => el('td', { class: 'dim', text: value === null ? DASH : `${num(value, 1)}%` });

    // Revenue
    push('Revenue', null, [
      ...years.map((y) => histCell(histValue(y, 'revenue'))),
      ...forecastYears.map((y) => histCell(results.revenue[y])),
    ], true);
    push('% growth', null, [
      ...years.map((y, i) => {
        const current = histValue(y, 'revenue');
        const prior = i > 0 ? histValue(years[i - 1], 'revenue') : null;
        return pctCell(current && prior ? (current / prior - 1) * 100 : null);
      }),
      ...forecastYears.map((y) => inputCell(y, 'growth')),
    ]);

    push('EBIT', null, [
      ...years.map((y) => histCell(histValue(y, 'ebit'))),
      ...forecastYears.map((y) => histCell(results.ebit[y])),
    ], true);
    push('% margin', null, [
      ...years.map((y) => {
        const ebit = histValue(y, 'ebit');
        const revenue = histValue(y, 'revenue');
        return pctCell(ebit !== null && revenue ? (ebit / revenue) * 100 : null);
      }),
      ...forecastYears.map((y) => inputCell(y, 'margin')),
    ]);

    push('Taxes', null, [
      ...years.map((y) => histCell(histValue(y, 'taxes'))),
      ...forecastYears.map((y) => histCell(results.taxes[y])),
    ], true);
    push('EBIAT', 'EBIT − taxes', [
      ...years.map((y) => {
        const ebit = histValue(y, 'ebit');
        const taxes = histValue(y, 'taxes');
        return histCell(ebit !== null && taxes !== null ? ebit - taxes : null);
      }),
      ...forecastYears.map((y) => histCell(results.ebiat[y])),
    ], true);

    const ratioBlock = (label, key, field) => {
      push(label, null, [
        ...years.map((y) => histCell(histValue(y, key))),
        ...forecastYears.map((y) => histCell(results[field][y])),
      ], true);
      push('% of sales', null, [
        ...years.map((y) => {
          const value = histValue(y, key);
          const revenue = histValue(y, 'revenue');
          return pctCell(value !== null && revenue ? (value / revenue) * 100 : null);
        }),
        ...forecastYears.map((y) => inputCell(y, field === 'da' ? 'da' : field)),
      ]);
    };
    ratioBlock('D&A', 'dep_amort', 'da');
    ratioBlock('CapEx', 'capex', 'capex');

    push('Change in NWC', 'increase = use of cash', [
      ...years.map((y) => histCell(histValue(y, 'nwc_change'))),
      ...forecastYears.map((y) => histCell(results.nwc[y])),
    ], true);
    push('% of sales', null, [
      ...years.map((y) => {
        const value = histValue(y, 'nwc_change');
        const revenue = histValue(y, 'revenue');
        return pctCell(value !== null && revenue ? (value / revenue) * 100 : null);
      }),
      ...forecastYears.map((y) => inputCell(y, 'nwc')),
    ]);

    push('Unlevered FCF', 'EBIAT + D&A − CapEx − ΔNWC', [
      ...years.map(() => el('td', { class: 'dim', text: DASH })),
      ...forecastYears.map((y) => histCell(results.fcf[y])),
    ], true);
    push('PV of FCF', null, [
      ...years.map(() => el('td', { class: 'dim', text: DASH })),
      ...forecastYears.map((y) => histCell(results.pv[y])),
    ], true);

    modelHost.innerHTML = '';
    modelHost.append(el('table', { class: 'data' }, [el('thead', {}, [head]), el('tbody', {}, body)]));
  }

  // --- Maths -------------------------------------------------------------
  function wacc() {
    const { rf, beta, erp, kd, tax } = assumptions;
    if (rf === null || beta === null || erp === null) return null;
    const ke = rf + beta * erp;
    const debt = company.rows[company.rows.length - 1]?.total_debt || 0;
    const equity = (company.last_price || 0) * (company.rows[company.rows.length - 1]?.shares || 0);
    if (!equity) return { ke, wacc: ke, we: 1, wd: 0 };
    const v = equity + debt;
    const we = equity / v;
    const wd = debt / v;
    const afterTaxKd = kd === null ? 0 : kd * (1 - (tax ?? 0) / 100);
    return { ke, wacc: we * ke + wd * afterTaxKd, we, wd };
  }

  function project() {
    const results = { revenue: {}, ebit: {}, taxes: {}, ebiat: {}, da: {}, capex: {}, nwc: {}, fcf: {}, pv: {} };
    const w = wacc();
    const rate = w ? w.wacc / 100 : null;
    let prior = histValue(lastYear, 'revenue');

    forecastYears.forEach((year, index) => {
      const input = forecast[year];
      const revenue = prior !== null && input.growth !== null ? prior * (1 + input.growth / 100) : null;
      results.revenue[year] = revenue;
      const ebit = revenue !== null && input.margin !== null ? revenue * (input.margin / 100) : null;
      results.ebit[year] = ebit;
      const taxes = ebit !== null && assumptions.tax !== null ? ebit * (assumptions.tax / 100) : null;
      results.taxes[year] = taxes;
      const ebiat = ebit !== null && taxes !== null ? ebit - taxes : null;
      results.ebiat[year] = ebiat;
      results.da[year] = revenue !== null && input.da !== null ? revenue * (input.da / 100) : null;
      results.capex[year] = revenue !== null && input.capex !== null ? revenue * (input.capex / 100) : null;
      results.nwc[year] = revenue !== null && input.nwc !== null ? revenue * (input.nwc / 100) : null;

      const parts = [ebiat, results.da[year], results.capex[year], results.nwc[year]];
      results.fcf[year] = parts.some((p) => p === null)
        ? null
        : ebiat + results.da[year] - results.capex[year] - results.nwc[year];
      results.pv[year] = results.fcf[year] !== null && rate !== null
        ? results.fcf[year] / (1 + rate) ** (index + 1)
        : null;
      prior = revenue;
    });
    return { results, w, rate };
  }

  function valuation(rate, exitMultiple, results) {
    const finalYear = forecastYears[forecastYears.length - 1];
    const ebitda = results.ebit[finalYear] !== null && results.da[finalYear] !== null
      ? results.ebit[finalYear] + results.da[finalYear] : null;
    if (ebitda === null || rate === null || !exitMultiple) return null;
    const terminal = ebitda * exitMultiple;
    const pvTerminal = terminal / (1 + rate) ** forecastYears.length;
    const pvFcf = forecastYears.reduce((sum, y) => sum + (results.pv[y] ?? 0), 0);
    if (forecastYears.some((y) => results.pv[y] === null)) return null;
    const ev = pvFcf + pvTerminal;
    const last = company.rows[company.rows.length - 1] || {};
    const cash = ((last.cash || 0) + (last.short_term_investments || 0)) / M;
    const debt = (last.total_debt || 0) / M;
    const shares = (last.shares || 0) / M;
    const equity = ev + cash - debt;
    return { ebitda, terminal, pvTerminal, pvFcf, ev, cash, debt, shares, equity, perShare: shares ? equity / shares : null };
  }

  function recompute() {
    const { results, w, rate } = project();
    buildGrid(results);

    waccLine.innerHTML = '';
    if (w) {
      waccLine.append(
        `WACC = ${num(w.wacc, 2)}%  ·  Cost of equity = ${num(w.ke, 2)}%  ·  `
        + `%Equity ${num(w.we * 100, 1)} / %Debt ${num(w.wd * 100, 1)}`,
      );
    } else {
      waccLine.append('WACC = —  ·  enter a risk-free rate, beta and equity risk premium to compute it.');
    }

    const v = valuation(rate, assumptions.exit, results);
    bridgeHost.innerHTML = '';
    const bridgeRows = [
      ['Terminal EBITDA (final yr EBIT + D&A)', v?.ebitda],
      [`× Exit multiple → Terminal Value`, v?.terminal],
      ['PV of Terminal Value', v?.pvTerminal],
      ['Σ PV of forecast FCF', v?.pvFcf],
      ['Enterprise Value', v?.ev, true],
      ['+ Cash & ST investments', v?.cash],
      ['− Total debt', v?.debt],
      ['Equity Value', v?.equity, true],
      ['÷ Shares (M)', v?.shares],
    ];
    const tbody = bridgeRows.map(([label, value, bold]) => el('tr', { class: bold ? 'emphasis' : '' }, [
      el('td', { text: label }),
      el('td', { text: value === null || value === undefined ? DASH : num(value, 0) }),
    ]));
    if (v?.perShare) {
      tbody.push(el('tr', { class: 'emphasis' }, [
        el('td', { text: 'Implied value per share' }),
        el('td', { style: 'color:var(--accent);font-weight:700', text: `$${num(v.perShare, 2)}` }),
      ]));
      if (company.last_price) {
        const upside = (v.perShare / company.last_price - 1) * 100;
        tbody.push(el('tr', {}, [
          el('td', { class: 'dim', text: `vs last close $${num(company.last_price)}` }),
          el('td', { class: upside >= 0 ? 'up' : 'down', text: pct(upside) }),
        ]));
      }
    }
    bridgeHost.append(el('table', { class: 'data' }, [el('tbody', {}, tbody)]));

    // --- Sensitivity ----------------------------------------------------
    sensitivityHost.innerHTML = '';
    if (!v || rate === null || !assumptions.exit) {
      sensitivityHost.append(el('div', { class: 'note-text', text: 'Complete the model — growth, margin, D&A, CapEx, ΔNWC, WACC inputs and an exit multiple — to see the sensitivity table.' }));
      return;
    }
    const waccSteps = WACC_STEPS.map((d) => w.wacc + d);
    const exitSteps = EXIT_STEPS.map((d) => assumptions.exit + d).filter((m) => m > 0);
    const header = el('tr', {}, [el('th', { text: 'WACC \\ Exit' }), ...exitSteps.map((m) => el('th', { text: `${num(m, 1)}x` }))]);
    const rows = waccSteps.map((wv) => el('tr', {}, [
      el('td', { text: `${num(wv, 2)}%` }),
      ...exitSteps.map((m) => {
        const cell = valuation(wv / 100, m, results);
        const price = cell?.perShare;
        const cls = !price || !company.last_price ? '' : price >= company.last_price ? 'up' : 'down';
        return el('td', { class: cls, text: price ? `$${num(price, 2)}` : DASH });
      }),
    ]));
    sensitivityHost.append(el('table', { class: 'data' }, [el('thead', {}, [header]), el('tbody', {}, rows)]));
  }

  recompute();
}
