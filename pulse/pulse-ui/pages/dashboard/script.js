// PULSE Dashboard — Diagnostic-first (concept C, winning)
// Vanilla ES module. Tokens-only. Chart.js for visualisation.

import { GLOBAL_METRICS, TEAMS, TRIBES, PERIOD_OPTIONS, classifyDora, fmtNumber, fmtTrend } from './mock-data.js';

/* -------------------------------------------------------- *
 * Token helpers (read from CSS custom properties)
 * -------------------------------------------------------- */
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const DORA_COLOR = {
  elite:  () => css('--color-dora-elite'),
  high:   () => css('--color-dora-high'),
  medium: () => css('--color-dora-medium'),
  low:    () => css('--color-dora-low'),
  neutral:() => css('--color-text-tertiary'),
};

/* -------------------------------------------------------- *
 * Dashboard state
 * -------------------------------------------------------- */
const state = {
  teamId: null,          // null = all squads
  period: '60d',
  customStart: null,
  customEnd:   null,
  activeRankingMetric: 'deployFreq',
  activeEvolutionMetric: 'cycleTimeP50',
};

/* ---------------- KPI GROUP RENDER ---------------- */
function renderKpiGroups() {
  const dora = GLOBAL_METRICS.dora;
  const flow = GLOBAL_METRICS.flow;

  const doraOrder = [
    ['deploymentFrequency', 'Deploy Freq',     'dora'],
    ['leadTimeForChanges',  'Lead Time',       'dora'],
    ['changeFailureRate',   'Change Failure',  'dora'],
    ['timeToRestore',       'Time to Restore', 'dora'],
  ];
  const flowOrder = [
    ['cycleTimeP50', 'Cycle Time P50', 'flow'],
    ['cycleTimeP85', 'Cycle Time P85', 'flow'],
    ['wip',          'Work in Progress','flow'],
    ['throughput',   'Throughput',      'flow'],
  ];

  const doraEl = document.getElementById('kpi-dora');
  const flowEl = document.getElementById('kpi-flow');
  doraEl.innerHTML = doraOrder.map(([k, lbl]) => kpiCardHtml(dora[k], lbl, 'dora', k)).join('');
  flowEl.innerHTML = flowOrder.map(([k, lbl]) => kpiCardHtml(flow[k], lbl, 'flow', k)).join('');

  // sparklines
  [...doraOrder, ...flowOrder].forEach(([k, , ,], idx) => {
    const m = (dora[k] || flow[k]);
    const canvas = document.getElementById(`sp-${k}`);
    if (canvas && m?.sparkline) drawSparkline(canvas, m.sparkline, m.classification);
  });
}

function kpiCardHtml(m, label, family, key) {
  if (!m) return '';
  const badge = m.classification
    ? `<span class="badge badge--${m.classification}">${classifLabel(m.classification)}</span>`
    : '<span class="badge badge--neutral">—</span>';
  const trendClass = trendClassFor(key, m.trendPct);
  return `
    <div class="kpi" role="group" aria-label="${label}">
      <div class="kpi__label">${label}</div>
      <div class="kpi__value-row">
        <span class="kpi__value">${m.value}</span>
        <span class="kpi__unit">${m.unit}</span>
      </div>
      <div class="kpi__meta">
        <span class="kpi__trend ${trendClass}" title="Variação vs período anterior">
          ${fmtTrend(m.trendPct)}
        </span>
        <canvas class="kpi__spark" id="sp-${key}" width="60" height="20" aria-hidden="true"></canvas>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
        ${badge}
      </div>
    </div>
  `;
}

function classifLabel(c) {
  return { elite: 'Elite', high: 'High', medium: 'Medium', low: 'Low', neutral: '—' }[c] || c;
}

// Lower-is-better metrics: leadTime, cfr, timeToRestore, cycleTimeP50/P85, wip
function trendClassFor(key, pct) {
  const lowerIsBetter = ['leadTimeForChanges','changeFailureRate','timeToRestore','cycleTimeP50','cycleTimeP85','wip'];
  if (lowerIsBetter.includes(key)) {
    return pct < 0 ? 'kpi__trend--down' : 'kpi__trend--bad-up';
  }
  // higher is better
  return pct >= 0 ? 'kpi__trend--up' : 'kpi__trend--bad-up';
}

/* ---------------- SPARKLINE (Chart.js) ---------------- */
function drawSparkline(canvas, data, classification = 'neutral') {
  const color = DORA_COLOR[classification]?.() || css('--color-brand-primary');
  new Chart(canvas, {
    type: 'line',
    data: {
      labels: data.map((_, i) => i),
      datasets: [{ data, borderColor: color, borderWidth: 1.5, fill: false,
                   pointRadius: 0, tension: 0.35 }],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
      animation: false,
    },
  });
}

/* ---------------- COMBOBOX (team filter) ---------------- */
function initTeamCombobox() {
  const trigger = document.getElementById('f-team');
  const panel   = document.getElementById('team-list');
  const search  = document.getElementById('team-search');
  const optsEl  = document.getElementById('team-options');
  const value   = document.getElementById('team-value');

  function renderOptions(filter = '') {
    const needle = filter.toLowerCase();
    const byTribe = new Map();
    TEAMS.forEach((t) => {
      const hay = `${t.name} ${t.tribe}`.toLowerCase();
      if (needle && !hay.includes(needle)) return;
      if (!byTribe.has(t.tribe)) byTribe.set(t.tribe, []);
      byTribe.get(t.tribe).push(t);
    });

    const parts = [];
    parts.push(`<li class="combobox__option" data-id="" aria-selected="${state.teamId === null}">
        <span>Todas as squads</span><span style="color:var(--color-text-tertiary);font-size:11px">${TEAMS.length}</span>
      </li>`);
    for (const [tribe, list] of byTribe.entries()) {
      parts.push(`<li class="combobox__group">${tribe}</li>`);
      list.forEach((t) => {
        parts.push(`<li class="combobox__option" data-id="${t.id}" aria-selected="${state.teamId === t.id}">
            <span>${t.name}</span>
          </li>`);
      });
    }
    optsEl.innerHTML = parts.join('');
  }

  function open() {
    panel.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    renderOptions('');
    search.value = ''; search.focus();
  }
  function close() {
    panel.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  }

  trigger.addEventListener('click', () => panel.hidden ? open() : close());
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#team-combobox')) close();
  });
  search.addEventListener('input', (e) => renderOptions(e.target.value));

  optsEl.addEventListener('click', (e) => {
    const li = e.target.closest('.combobox__option');
    if (!li) return;
    state.teamId = li.dataset.id || null;
    value.textContent = state.teamId
      ? TEAMS.find((t) => t.id === state.teamId)?.name
      : 'Todas as squads';
    close();
    updateAppliedFilters();
    renderAll();
    trackEvent('dashboard_team_filter_changed', { teamId: state.teamId });
  });

  renderOptions();
}

/* ---------------- PERIOD SEGMENTED ---------------- */
function initPeriodSegmented() {
  const btns = document.querySelectorAll('.segmented__opt');
  const dateRange = document.getElementById('date-range');

  btns.forEach((b) => {
    b.addEventListener('click', () => {
      btns.forEach((x) => { x.classList.remove('is-active'); x.setAttribute('aria-checked', 'false'); });
      b.classList.add('is-active'); b.setAttribute('aria-checked', 'true');
      state.period = b.dataset.period;
      dateRange.hidden = state.period !== 'custom';
      updateAppliedFilters();
      renderAll();
      trackEvent('dashboard_period_changed', { period: state.period });
    });
  });

  document.getElementById('date-start').addEventListener('change', (e) => { state.customStart = e.target.value; updateAppliedFilters(); });
  document.getElementById('date-end').addEventListener('change',   (e) => { state.customEnd   = e.target.value; updateAppliedFilters(); });

  document.getElementById('btn-reset').addEventListener('click', () => {
    state.teamId = null; state.period = '60d';
    document.getElementById('team-value').textContent = 'Todas as squads';
    btns.forEach((x) => { x.classList.toggle('is-active', x.dataset.period === '60d'); });
    dateRange.hidden = true;
    updateAppliedFilters();
    renderAll();
  });
}

function updateAppliedFilters() {
  document.getElementById('af-scope').textContent = state.teamId
    ? TEAMS.find((t) => t.id === state.teamId)?.name
    : 'todas as 27 squads';
  const label = PERIOD_OPTIONS.find((p) => p.id === state.period)?.label;
  document.getElementById('af-period').textContent = state.period === 'custom'
    ? `${state.customStart || '—'} a ${state.customEnd || '—'}`
    : label;
}

/* ---------------- RANKING TAB + CHART ---------------- */
function initRankingTabs() {
  document.querySelectorAll('.metric-tab').forEach((t) => {
    t.addEventListener('click', () => {
      document.querySelectorAll('.metric-tab').forEach((x) => {
        x.classList.remove('is-active'); x.setAttribute('aria-selected', 'false');
      });
      t.classList.add('is-active'); t.setAttribute('aria-selected', 'true');
      state.activeRankingMetric = t.dataset.metric;
      renderRanking();
      trackEvent('dashboard_ranking_metric_changed', { metric: state.activeRankingMetric });
    });
  });
}

const METRIC_META = {
  deployFreq:  { title: 'Deploy Frequency por squad', sub: 'Deploys por dia · maior é melhor',        key: 'deployFreq',   sortDir: 'desc', unit: '/dia' },
  leadTime:    { title: 'Lead Time por squad',         sub: 'Horas commit → produção · menor é melhor',key: 'leadTime',     sortDir: 'asc',  unit: 'h'    },
  cfr:         { title: 'Change Failure Rate por squad', sub: '% de deploys com falha · menor é melhor', key: 'cfr',       sortDir: 'asc',  unit: '%'    },
  cycleTime:   { title: 'Cycle Time P50 por squad',    sub: 'Dias · menor é melhor',                   key: 'cycleTimeP50', sortDir: 'asc',  unit: 'd'    },
  wip:         { title: 'Work in Progress por squad',  sub: 'Itens em progresso · menor é mais saudável', key: 'wip',     sortDir: 'asc',  unit: 'itens'},
  throughput:  { title: 'Throughput por squad',        sub: 'PRs/semana · maior é melhor',             key: 'throughput',   sortDir: 'desc', unit: 'PRs/sem'},
};

function classifyForMetric(metric, value) {
  // Map to DORA classification where possible
  if (metric === 'deployFreq') return classifyDora('deployFreq', value);
  if (metric === 'leadTime')   return classifyDora('leadTime', value);
  if (metric === 'cfr')        return classifyDora('cfr', value);
  // Flow metrics: quantile-based (approx)
  if (metric === 'cycleTimeP50') return value < 3 ? 'elite' : value < 5 ? 'high' : value < 8 ? 'medium' : 'low';
  if (metric === 'wip')          return value < 15 ? 'elite' : value < 22 ? 'high' : value < 30 ? 'medium' : 'low';
  if (metric === 'throughput')   return value >= 20 ? 'elite' : value >= 14 ? 'high' : value >= 9 ? 'medium' : 'low';
  return 'neutral';
}

function renderRanking() {
  const meta = METRIC_META[state.activeRankingMetric];
  document.getElementById('ranking-metric-title').textContent = meta.title;
  document.getElementById('ranking-metric-sub').textContent   = meta.sub;

  const teams = [...TEAMS].sort((a, b) => meta.sortDir === 'desc'
    ? b[meta.key] - a[meta.key]
    : a[meta.key] - b[meta.key]);

  const max = Math.max(...teams.map((t) => t[meta.key]));
  const container = document.getElementById('ranking-chart');

  if (teams.length === 0) {
    container.innerHTML = `<div class="state-empty">
      <h3>Sem squads para exibir</h3>
      <p>Conecte DevLake para começar a coletar dados.</p>
    </div>`;
    return;
  }

  container.innerHTML = teams.map((t, i) => {
    const value = t[meta.key];
    const cls = classifyForMetric(state.activeRankingMetric, value);
    const pct = max > 0 ? (value / max) * 100 : 0;
    return `
      <div class="rank-row" role="button" tabindex="0" data-team-id="${t.id}" aria-label="${t.name}: ${value} ${meta.unit}">
        <span class="rank-row__pos">${i + 1}</span>
        <span class="rank-row__team">
          <span class="rank-row__team-name">${t.name}</span>
          <span class="rank-row__team-tribe">${t.tribe}</span>
        </span>
        <span class="rank-row__bar-track" aria-hidden="true">
          <span class="rank-row__bar-fill rank-row__bar-fill--${cls}" style="width:${pct}%"></span>
        </span>
        <span class="rank-row__value">${fmtNumber(value)} <span style="color:var(--color-text-tertiary);font-size:11px">${meta.unit}</span></span>
        <span class="rank-row__badge badge badge--${cls}">${classifLabel(cls)}</span>
      </div>
    `;
  }).join('');

  // bind row click → drawer
  container.querySelectorAll('.rank-row').forEach((row) => {
    row.addEventListener('click', () => openDrawer(row.dataset.teamId));
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(row.dataset.teamId); }
    });
  });
}

/* ---------------- EVOLUTION SMALL MULTIPLES ---------------- */
function initEvolutionControls() {
  document.getElementById('ev-metric').addEventListener('change', (e) => {
    state.activeEvolutionMetric = e.target.value;
    renderSmallMultiples();
    trackEvent('dashboard_evolution_metric_changed', { metric: state.activeEvolutionMetric });
  });
}

function renderSmallMultiples() {
  const metricKey = state.activeEvolutionMetric;
  const container = document.getElementById('small-multiples');
  container.innerHTML = '';

  // Group by tribe
  const groups = new Map();
  TEAMS.forEach((t) => {
    if (!groups.has(t.tribe)) groups.set(t.tribe, []);
    groups.get(t.tribe).push(t);
  });

  for (const [tribe, teams] of groups.entries()) {
    const title = document.createElement('div');
    title.className = 'sm-group-title';
    title.textContent = `${tribe} · ${teams.length} squads`;
    container.appendChild(title);

    teams.forEach((t) => {
      const tile = document.createElement('div');
      tile.className = 'sm-tile';
      tile.setAttribute('role', 'button');
      tile.setAttribute('tabindex', '0');
      tile.dataset.teamId = t.id;
      const series = t.evolution[metricKey] || [];
      const current = series[series.length - 1] ?? 0;
      const prev    = series[0] ?? 0;
      const delta   = prev > 0 ? ((current - prev) / prev) * 100 : 0;
      tile.innerHTML = `
        <div class="sm-tile__head">
          <span class="sm-tile__name">${t.name}</span>
          <span class="sm-tile__tribe">${t.tribe}</span>
        </div>
        <div class="sm-tile__chart"><canvas id="sm-${t.id}" height="40"></canvas></div>
        <div class="sm-tile__value">${fmtNumber(current)}</div>
        <div class="sm-tile__delta">${fmtTrend(delta)} vs 12 sem atrás</div>
      `;
      tile.addEventListener('click', () => openDrawer(t.id));
      tile.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDrawer(t.id); }
      });
      container.appendChild(tile);

      const cls = classifyForMetric(state.activeRankingMetric, current);
      drawSparkline(tile.querySelector('canvas'), series, cls);
    });
  }
}

/* ---------------- DRAWER ---------------- */
let drawerCharts = [];
function openDrawer(teamId) {
  const team = TEAMS.find((t) => t.id === teamId);
  if (!team) return;

  drawerCharts.forEach((c) => c.destroy());
  drawerCharts = [];

  document.getElementById('drawer-tribe').textContent = `TRIBO ${team.tribe}`;
  document.getElementById('drawer-title').textContent = team.name;

  const body = document.getElementById('drawer-body');
  body.innerHTML = `
    <div class="drawer-metrics">
      ${drawerMetric('Deploy Freq',   fmtNumber(team.deployFreq),   '/dia',   classifyForMetric('deployFreq', team.deployFreq))}
      ${drawerMetric('Lead Time',     fmtNumber(team.leadTime),     'h',      classifyForMetric('leadTime',   team.leadTime))}
      ${drawerMetric('Change Failure',fmtNumber(team.cfr),          '%',      classifyForMetric('cfr',        team.cfr))}
      ${drawerMetric('Cycle P50',     fmtNumber(team.cycleTimeP50), 'd',      classifyForMetric('cycleTimeP50', team.cycleTimeP50))}
      ${drawerMetric('Cycle P85',     fmtNumber(team.cycleTimeP85), 'd',      'neutral')}
      ${drawerMetric('WIP',           fmtNumber(team.wip),          'itens',  classifyForMetric('wip', team.wip))}
      ${drawerMetric('Throughput',    fmtNumber(team.throughput),   'PRs/sem',classifyForMetric('throughput', team.throughput))}
    </div>

    <div class="drawer-chart-block">
      <h4>Evolução (12 sem) · ${METRIC_META[state.activeRankingMetric].title.replace(' por squad','')}</h4>
      <div class="drawer-chart"><canvas id="drawer-evo"></canvas></div>
    </div>

    <div class="drawer-chart-block">
      <h4>Distribuição Cycle Time (P50 / P85)</h4>
      <div class="drawer-chart"><canvas id="drawer-dist"></canvas></div>
    </div>
  `;

  const metricKey = METRIC_META[state.activeRankingMetric].key;
  const series = team.evolution[metricKey] || team.evolution.cycleTimeP50;

  const evoCanvas = document.getElementById('drawer-evo');
  drawerCharts.push(new Chart(evoCanvas, {
    type: 'line',
    data: {
      labels: series.map((_, i) => `S-${11 - i}`),
      datasets: [{
        data: series, borderColor: css('--color-brand-primary'), borderWidth: 2,
        backgroundColor: 'rgba(99,102,241,0.08)', fill: true, pointRadius: 2, tension: 0.3,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { font: { family: css('--font-mono'), size: 10 } } },
        y: { grid: { color: css('--color-border-subtle') }, ticks: { font: { family: css('--font-mono'), size: 10 } } },
      },
    },
  }));

  const distCanvas = document.getElementById('drawer-dist');
  drawerCharts.push(new Chart(distCanvas, {
    type: 'bar',
    data: {
      labels: ['P50', 'P85'],
      datasets: [{
        data: [team.cycleTimeP50, team.cycleTimeP85],
        backgroundColor: [css('--color-brand-primary'), css('--color-warning')],
        borderRadius: 4,
      }],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: css('--color-border-subtle') }, ticks: { font: { family: css('--font-mono'), size: 10 } } },
        y: { grid: { display: false } },
      },
    },
  }));

  const drawer = document.getElementById('drawer');
  drawer.hidden = false;
  document.getElementById('drawer-close').focus();
  trackEvent('dashboard_drawer_opened', { teamId });
}

function drawerMetric(label, value, unit, cls) {
  return `
    <div class="drawer-metric">
      <div class="drawer-metric__label">${label}</div>
      <div class="drawer-metric__value" style="color:${DORA_COLOR[cls]?.() || css('--color-text-primary')}">
        ${value} <span style="color:var(--color-text-tertiary);font-size:12px">${unit}</span>
      </div>
    </div>
  `;
}

function initDrawer() {
  document.getElementById('drawer-close').addEventListener('click', () => {
    document.getElementById('drawer').hidden = true;
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') document.getElementById('drawer').hidden = true;
  });
}

/* ---------------- ANALYTICS ---------------- */
function trackEvent(name, payload = {}) {
  // Hook point — replaced by Mixpanel/PostHog in production.
  // eslint-disable-next-line no-console
  console.debug('[analytics]', name, payload);
}

/* ---------------- MAIN ---------------- */
function renderAll() {
  renderKpiGroups();
  renderRanking();
  renderSmallMultiples();
}

document.addEventListener('DOMContentLoaded', () => {
  // Wait for Chart.js to load
  const boot = () => {
    if (!window.Chart) return requestAnimationFrame(boot);
    initTeamCombobox();
    initPeriodSegmented();
    initRankingTabs();
    initEvolutionControls();
    initDrawer();
    updateAppliedFilters();
    renderAll();
    trackEvent('dashboard_viewed', { period: state.period });
  };
  boot();
});
