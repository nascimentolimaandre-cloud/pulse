/* ============================================================
   PULSE · Flow Health section — runtime (ES module)
   Renders concepts A/B/C + states (healthy/critical/empty/loading)
   ============================================================ */

// ---------- MOCK DATA (Webmotors-scale) ----------

const SQUADS = [
  'DESK', 'BG', 'SECOM', 'CHECKOUT', 'SEARCH', 'PLATFORM', 'DATA', 'MOBILE',
  'BILLING', 'ONBOARD', 'RECS', 'CATALOG', 'INVENTORY', 'PRICING', 'GROWTH',
  'RISK', 'CS', 'ADS', 'FLEET', 'PHOTOS', 'SEO', 'CRM', 'DEVEX', 'QA',
  'SRE', 'INFRA', 'DOCS',
];

// Deterministic PRNG so concepts stay comparable across reloads
function rng(seed) { let s = seed >>> 0; return () => (s = (s * 1664525 + 1013904223) >>> 0, s / 0xFFFFFFFF); }

function buildAgingItems(count = 633, state = 'healthy') {
  const r = rng(42);
  const items = [];
  for (let i = 0; i < count; i++) {
    // 70% healthy ≤ p85, 20% watch, 10% at_risk
    const bucket = r();
    let age;
    if (bucket < 0.70) age = r() * 22;          // 0–22d (≤ P85)
    else if (bucket < 0.90) age = 22 + r() * 22; // 22–44d (watch)
    else age = 44 + r() * 90;                    // 44–134d (at_risk)
    const squad = SQUADS[Math.floor(r() * SQUADS.length)];
    const status = r() < 0.65 ? 'in_progress' : 'in_review';
    const num = Math.floor(r() * 50000);
    items.push({
      issue_key: `${squad}-${num}`,
      age_days: +age.toFixed(1),
      status_category: status,
      status_name: status === 'in_progress' ? 'In Progress' : 'In Review',
      squad_key: squad,
      is_at_risk: age > 44.6,
    });
  }
  // Critical state: concentrate 24 at_risk in DESK
  if (state === 'critical') {
    for (let i = 0; i < 24; i++) {
      items.push({
        issue_key: `DESK-${40000 + i}`,
        age_days: +(45 + Math.random() * 90).toFixed(1),
        status_category: 'in_progress',
        status_name: 'In Progress',
        squad_key: 'DESK',
        is_at_risk: true,
      });
    }
  }
  return items.sort((a, b) => b.age_days - a.age_days);
}

const STATE_DATA = {
  healthy: {
    aging_wip: { count: 633, p50_days: 6.5, p85_days: 22.3, at_risk_count: 67, at_risk_threshold_days: 44.6 },
    fe: { value: 0.42, trend_pp: -3, sample_size: 2145, insufficient_data: false },
  },
  critical: {
    aging_wip: { count: 657, p50_days: 7.1, p85_days: 24.8, at_risk_count: 91, at_risk_threshold_days: 49.6 },
    fe: { value: 0.34, trend_pp: -8, sample_size: 2018, insufficient_data: false },
  },
  empty: {
    aging_wip: { count: 0, p50_days: 0, p85_days: 0, at_risk_count: 0, at_risk_threshold_days: 0 },
    fe: { value: null, trend_pp: 0, sample_size: 0, insufficient_data: true },
  },
};

// ---------- STATE ----------
let currentConcept = 'A';
let currentState = 'healthy';

// ---------- FORMATTERS ----------
const fmtPct = (v) => `${Math.round(v * 100)}%`;
const fmtDays = (v) => `${v.toFixed(1).replace('.', ',')}d`;
const fmtNum = (v) => v.toLocaleString('pt-BR');

// ---------- RENDERERS — each concept ----------

function renderConceptA(items, summary) {
  // Outlier-first: top 8 at_risk in ranked table
  const atRisk = items.filter((i) => i.is_at_risk).slice(0, 8);
  if (atRisk.length === 0) return renderEmpty();
  const maxAge = atRisk[0].age_days;
  const rows = atRisk.map((it) => {
    const pct = Math.min(100, (it.age_days / maxAge) * 100);
    const isExtreme = it.age_days > summary.at_risk_threshold_days * 1.5;
    return `
      <tr tabindex="0" data-issue="${it.issue_key}">
        <td><span class="outlier-table__key">${it.issue_key}</span></td>
        <td>
          <span class="outlier-table__squad">${it.squad_key}</span>
        </td>
        <td>
          <span class="outlier-table__status outlier-table__status--${it.status_category === 'in_review' ? 'review' : 'prog'}">
            <span class="outlier-table__status-dot" aria-hidden="true"></span>${it.status_name}
          </span>
        </td>
        <td>
          <div class="outlier-bar" role="img" aria-label="Idade relativa ao máximo">
            <div class="outlier-bar__fill ${isExtreme ? '' : 'outlier-bar__fill--warn'}" style="width:${pct}%"></div>
          </div>
        </td>
        <td class="outlier-table__age">${fmtDays(it.age_days)}</td>
      </tr>`;
  }).join('');

  return `
    <table class="outlier-table" aria-label="Top itens em risco">
      <thead>
        <tr>
          <th scope="col">Issue</th>
          <th scope="col">Squad</th>
          <th scope="col">Status</th>
          <th scope="col" aria-label="Gráfico de idade">Idade</th>
          <th scope="col" style="text-align:right">Dias</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="outlier-foot">
      <span>Mostrando 8 de ${summary.at_risk_count} em risco</span>
      <a href="#" class="outlier-foot__link" data-action="open-drawer">Ver lista completa →</a>
    </div>`;
}

function renderConceptB(items, summary) {
  // Distribution-first: histogram of age buckets + squad chips
  if (items.length === 0) return renderEmpty();
  const buckets = [
    { label: '0–7d', min: 0, max: 7, color: 'info', count: 0 },
    { label: '7–14d', min: 7, max: 14, color: 'info', count: 0 },
    { label: '14–22d', min: 14, max: 22.3, color: 'info', count: 0 },
    { label: '22–45d', min: 22.3, max: 44.6, color: 'warning', count: 0 },
    { label: '> 45d (at risk)', min: 44.6, max: Infinity, color: 'danger', count: 0 },
  ];
  items.forEach((it) => {
    const b = buckets.find((x) => it.age_days >= x.min && it.age_days < x.max);
    if (b) b.count++;
  });

  // Top 5 squads with most at_risk
  const squadRisk = {};
  items.filter((i) => i.is_at_risk).forEach((i) => { squadRisk[i.squad_key] = (squadRisk[i.squad_key] || 0) + 1; });
  const topSquads = Object.entries(squadRisk).sort((a, b) => b[1] - a[1]).slice(0, 6);

  return `
    <div class="dist-wrap">
      <div class="dist-chart-shell">
        <canvas id="dist-chart" height="180" aria-label="Histograma de idade dos itens em progresso"></canvas>
      </div>
      <div class="dist-legend" aria-hidden="true">
        <span class="dist-legend__item"><span class="dist-legend__swatch dist-legend__swatch--healthy"></span>≤ P85 (22d) · saudável</span>
        <span class="dist-legend__item"><span class="dist-legend__swatch dist-legend__swatch--watch"></span>22–45d · atenção</span>
        <span class="dist-legend__item"><span class="dist-legend__swatch dist-legend__swatch--risk"></span>&gt; 45d · em risco</span>
      </div>
      <div class="dist-squad-chips" role="list" aria-label="Squads com mais itens em risco">
        ${topSquads.map(([sq, n]) => `<button type="button" class="dist-squad-chip" data-squad="${sq}" role="listitem">${sq} <span class="fh-mono">${n}</span></button>`).join('')}
        ${topSquads.length === 6 ? `<button type="button" class="dist-squad-chip" style="background:var(--color-bg-tertiary);color:var(--color-text-secondary)" data-action="open-drawer">ver todas →</button>` : ''}
      </div>
    </div>`;
}

function renderConceptC(items, summary) {
  // Squad × age heatmap — top 12 squads by WIP count
  if (items.length === 0) return renderEmpty();
  const byS = {};
  items.forEach((it) => {
    if (!byS[it.squad_key]) byS[it.squad_key] = { total: 0, b0: 0, b1: 0, b2: 0, b3: 0, risk: 0 };
    const s = byS[it.squad_key];
    s.total++;
    if (it.age_days < 7) s.b0++;
    else if (it.age_days < 14) s.b1++;
    else if (it.age_days < 22.3) s.b2++;
    else if (it.age_days < 44.6) s.b3++;
    if (it.is_at_risk) s.risk++;
  });
  const squads = Object.entries(byS)
    .sort((a, b) => b[1].risk - a[1].risk || b[1].total - a[1].total)
    .slice(0, 12);

  const maxCount = Math.max(1, ...squads.flatMap(([, v]) => [v.b0, v.b1, v.b2, v.b3]));
  const maxRisk = Math.max(1, ...squads.map(([, v]) => v.risk));

  function intensity(v, max) {
    if (v === 0) return 0;
    const r = v / max;
    if (r < 0.25) return 1;
    if (r < 0.5) return 2;
    if (r < 0.75) return 3;
    return 4;
  }

  const rows = squads.map(([sq, v]) => `
    <div class="heatmap__row-label" title="${sq}">${sq}</div>
    <div class="heatmap__cell" data-intensity="${intensity(v.b0, maxCount)}" title="0–7d: ${v.b0} itens">${v.b0 || '·'}</div>
    <div class="heatmap__cell" data-intensity="${intensity(v.b1, maxCount)}" title="7–14d: ${v.b1} itens">${v.b1 || '·'}</div>
    <div class="heatmap__cell" data-intensity="${intensity(v.b2, maxCount)}" title="14–22d: ${v.b2} itens">${v.b2 || '·'}</div>
    <div class="heatmap__cell heatmap__cell--risk" data-intensity="${v.risk >= 20 ? 4 : intensity(v.risk, maxRisk)}" title="Em risco (>45d): ${v.risk} itens" tabindex="0" data-squad="${sq}">${v.risk || '·'}</div>
    <div class="heatmap__cell heatmap__cell--risk" data-intensity="${v.risk > 30 ? 4 : 0}" title="% do WIP do squad em risco">${Math.round((v.risk / v.total) * 100)}%</div>
    <div class="heatmap__total">${v.total}</div>
  `).join('');

  return `
    <div class="heatmap" role="table" aria-label="Heatmap de idade por squad">
      <div class="heatmap__hdr heatmap__hdr--squad">Squad</div>
      <div class="heatmap__hdr">0–7d</div>
      <div class="heatmap__hdr">7–14d</div>
      <div class="heatmap__hdr">14–22d</div>
      <div class="heatmap__hdr">Em risco (&gt;45d)</div>
      <div class="heatmap__hdr">% risco</div>
      <div class="heatmap__hdr">Total</div>
      ${rows}
    </div>
    <div class="heatmap-foot">
      <span>Top 12 squads por volume em risco · ${SQUADS.length - 12} squads restantes com fluxo saudável</span>
      <a href="#" class="outlier-foot__link" data-action="open-drawer">Ver todas as squads →</a>
    </div>`;
}

function renderEmpty() {
  return `
    <div class="fh-empty" role="status">
      <strong>Nenhum item em progresso no momento.</strong>
      <span>Quando squads iniciarem trabalho, a idade dos itens aparece aqui. Pipeline de ingestão atualiza a cada 5 min.</span>
    </div>`;
}

function renderLoading() {
  return `
    <div aria-busy="true">
      ${Array.from({ length: 6 }).map(() => `<div class="fh-skeleton-row"></div>`).join('')}
    </div>`;
}

// ---------- RENDER ORCHESTRATION ----------

let distChart = null;

function renderSection() {
  const data = STATE_DATA[currentState];
  const viewport = document.getElementById('aging-viewport');
  const callout = document.getElementById('aging-callout');
  const subEl = document.getElementById('aging-sub');
  const arc = document.getElementById('fe-arc');
  const feValueEl = document.getElementById('fe-value');
  const feTrendEl = document.getElementById('fe-trend');
  const atRiskCountEl = document.getElementById('aging-atrisk-count');
  const thresholdEl = document.getElementById('aging-threshold');

  // Loading — overrides everything
  if (currentState === 'loading') {
    viewport.innerHTML = renderLoading();
    callout.hidden = true;
    subEl.textContent = 'Carregando…';
    return;
  }

  // Update chrome
  const agg = data.aging_wip;
  subEl.textContent = agg.count === 0
    ? 'Sem itens em progresso no momento'
    : `${fmtNum(agg.count)} itens em progresso · P50 ${fmtDays(agg.p50_days)} · P85 ${fmtDays(agg.p85_days)}`;

  if (agg.at_risk_count > 0) {
    callout.hidden = false;
    atRiskCountEl.textContent = fmtNum(agg.at_risk_count);
    thresholdEl.textContent = fmtDays(agg.at_risk_threshold_days);
  } else {
    callout.hidden = true;
  }

  // FE update
  if (data.fe.insufficient_data) {
    feValueEl.textContent = '—';
    feTrendEl.innerHTML = 'dados insuficientes';
    arc.setAttribute('stroke-dashoffset', '326.73');
  } else {
    feValueEl.textContent = fmtPct(data.fe.value);
    const circ = 2 * Math.PI * 52; // 326.73
    arc.setAttribute('stroke-dasharray', circ.toFixed(2));
    arc.setAttribute('stroke-dashoffset', (circ * (1 - data.fe.value)).toFixed(2));
    const trendSign = data.fe.trend_pp >= 0 ? '+' : '';
    feTrendEl.innerHTML = `
      <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="${data.fe.trend_pp >= 0 ? 'M1 7l4-4 4 4' : 'M1 3l4 4 4-4'}" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/></svg>
      ${trendSign}${data.fe.trend_pp}pp vs 60d anteriores`;
    feTrendEl.className = 'fe-gauge__trend ' + (data.fe.trend_pp >= 0 ? 'fe-gauge__trend--up' : 'fe-gauge__trend--down');
  }

  // Viewport by concept
  const items = buildAgingItems(agg.count, currentState);
  let html = '';
  if (currentState === 'empty') html = renderEmpty();
  else if (currentConcept === 'A') html = renderConceptA(items, agg);
  else if (currentConcept === 'B') html = renderConceptB(items, agg);
  else html = renderConceptC(items, agg);

  viewport.innerHTML = html;

  // Draw chart for concept B
  if (currentConcept === 'B' && currentState !== 'empty') {
    drawDistChart(items);
  }

  bindViewportHandlers();
}

function drawDistChart(items) {
  const ctx = document.getElementById('dist-chart');
  if (!ctx || !window.Chart) return;
  const buckets = [
    { label: '0–7d', min: 0, max: 7, color: '#3B82F6', count: 0 },
    { label: '7–14d', min: 7, max: 14, color: '#60A5FA', count: 0 },
    { label: '14–22d', min: 14, max: 22.3, color: '#93C5FD', count: 0 },
    { label: '22–45d', min: 22.3, max: 44.6, color: '#F59E0B', count: 0 },
    { label: '> 45d', min: 44.6, max: Infinity, color: '#EF4444', count: 0 },
  ];
  items.forEach((it) => {
    const b = buckets.find((x) => it.age_days >= x.min && it.age_days < x.max);
    if (b) b.count++;
  });
  if (distChart) distChart.destroy();
  distChart = new window.Chart(ctx, {
    type: 'bar',
    data: {
      labels: buckets.map((b) => b.label),
      datasets: [{
        data: buckets.map((b) => b.count),
        backgroundColor: buckets.map((b) => b.color),
        borderRadius: 6,
        borderSkipped: false,
        barPercentage: 0.75,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#fff', borderColor: '#E5E7EB', borderWidth: 1,
          titleColor: '#111827', bodyColor: '#111827',
          callbacks: {
            label: (ctx) => `${ctx.parsed.y} itens (${Math.round(ctx.parsed.y / items.length * 100)}%)`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#6B7280', font: { size: 11 } } },
        y: { beginAtZero: true, grid: { color: '#F3F4F6' }, ticks: { color: '#9CA3AF', font: { size: 11 }, precision: 0 } },
      },
    },
  });
}

// ---------- DRAWER ----------

function openDrawer() {
  const d = document.getElementById('fh-drawer');
  d.hidden = false;
  const items = buildAgingItems(STATE_DATA[currentState].aging_wip.count, currentState)
    .filter((i) => i.is_at_risk);
  const body = document.getElementById('fh-drawer-body');
  body.innerHTML = `
    <table class="outlier-table" aria-label="Lista completa de itens em risco">
      <thead>
        <tr>
          <th>Issue</th><th>Squad</th><th>Status</th><th style="text-align:right">Dias</th>
        </tr>
      </thead>
      <tbody>
        ${items.slice(0, 200).map((it) => `
          <tr>
            <td><span class="outlier-table__key">${it.issue_key}</span></td>
            <td><span class="outlier-table__squad">${it.squad_key}</span></td>
            <td><span class="outlier-table__status outlier-table__status--${it.status_category === 'in_review' ? 'review' : 'prog'}"><span class="outlier-table__status-dot"></span>${it.status_name}</span></td>
            <td class="outlier-table__age">${fmtDays(it.age_days)}</td>
          </tr>`).join('')}
      </tbody>
    </table>
    ${items.length > 200 ? `<p class="fh-empty"><span>Mostrando 200 de ${items.length}. Use os filtros acima.</span></p>` : ''}
  `;
  document.getElementById('fh-drawer-close').focus();
}
function closeDrawer() { document.getElementById('fh-drawer').hidden = true; }

function bindViewportHandlers() {
  document.querySelectorAll('[data-action="open-drawer"]').forEach((el) => {
    el.addEventListener('click', (e) => { e.preventDefault(); openDrawer(); });
  });
  document.querySelectorAll('.outlier-table tbody tr').forEach((tr) => {
    tr.addEventListener('click', () => openDrawer());
  });
  document.querySelectorAll('.heatmap__cell--risk[data-squad]').forEach((c) => {
    c.addEventListener('click', () => openDrawer());
  });
}

// ---------- SWITCHER ----------

function bindSwitcher() {
  document.querySelectorAll('[data-concept]').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('[data-concept]').forEach((x) => x.classList.remove('is-active'));
      b.classList.add('is-active');
      currentConcept = b.dataset.concept;
      renderSection();
    });
  });
  document.querySelectorAll('[data-state]').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('[data-state]').forEach((x) => x.classList.remove('is-active'));
      b.classList.add('is-active');
      currentState = b.dataset.state;
      renderSection();
    });
  });

  document.getElementById('aging-view-list').addEventListener('click', openDrawer);
  document.getElementById('fh-drawer-close').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeDrawer();
  });
}

// ---------- BOOT ----------
document.addEventListener('DOMContentLoaded', () => {
  bindSwitcher();
  renderSection();
});
