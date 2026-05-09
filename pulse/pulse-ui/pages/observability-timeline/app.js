/* ============================================================
   PULSE · Deploy Health Timeline (Carlos persona)
   FDD-OBS-001 PR 4b — vanilla JS + SVG (no chart lib needed)

   Backed by fixture JSON in prototype mode. Replace `_load`
   with `fetch('/data/v1/obs/timeline?squad_key=...')` once R1
   auth lands.
   ============================================================ */

(() => {
  'use strict';

  const STATE = {
    timeline: null,
    squad: 'ANCR',
    windowHours: 168,
  };

  const SEVERITY_LABEL = {
    0: 'OK',
    1: 'Warn',
    2: 'Alert',
    3: 'No Data',
  };
  const SEVERITY_CLASS = {
    0: 'bar--ok',
    1: 'bar--warn',
    2: 'bar--alert',
    3: 'bar--nodata',
  };

  document.addEventListener('DOMContentLoaded', async () => {
    await _load();
    _renderKpis();
    _renderChart();
    _renderDeploysTable();
    _wireEvents();
  });

  async function _load() {
    try {
      const res = await fetch('./fixtures/timeline.json');
      STATE.timeline = await res.json();
    } catch (err) {
      console.error('Timeline fixture load failed', err);
      STATE.timeline = null;
    }
  }

  // -------------------------------------------------
  // KPIs
  // -------------------------------------------------
  function _renderKpis() {
    const t = STATE.timeline;
    if (!t) return;
    document.getElementById('kpi-services').textContent = String(t.services_in_squad);
    document.getElementById('kpi-buckets').textContent = String(t.buckets.length);
    document.getElementById('kpi-deploys').textContent = String(t.deploys.length);
    if (t.buckets.length === 0) {
      document.getElementById('kpi-avg-severity').textContent = '—';
      return;
    }
    const avg = t.buckets.reduce((acc, b) => acc + b.severity, 0) / t.buckets.length;
    document.getElementById('kpi-avg-severity').textContent = avg.toFixed(2);
  }

  // -------------------------------------------------
  // Chart (SVG)
  // -------------------------------------------------
  function _renderChart() {
    const svg = document.getElementById('timeline-chart');
    svg.innerHTML = '';

    const t = STATE.timeline;
    if (!t || t.buckets.length === 0) {
      _appendText(svg, 600, 120, 'Sem data acumulada para a janela atual.', 'axis-label', 'middle');
      return;
    }

    // Build a continuous hour grid between since/until so gaps are
    // visible (not implicit). Webmotors example: rollup may have
    // missed some hours during partial-coverage cycles.
    const start = new Date(t.since).getTime();
    const end = new Date(t.until).getTime();
    const hours = Math.max(1, Math.round((end - start) / 3_600_000));
    const W = 1200;
    const H = 240;
    const PAD = { left: 36, right: 12, top: 16, bottom: 28 };
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;
    const barW = innerW / hours;

    // Y axis (severity 0..3 from top to bottom)
    const yFor = (sev) => PAD.top + (sev / 3) * innerH;

    // Y-axis grid lines + labels
    [0, 1, 2, 3].forEach((sev) => {
      const y = yFor(sev);
      _appendLine(svg, PAD.left, y, W - PAD.right, y, 'axis-grid');
      _appendText(svg, PAD.left - 6, y + 3, SEVERITY_LABEL[sev], 'axis-label', 'end');
    });

    // Build a quick lookup of bucket by hour index
    const bucketByHour = new Map();
    t.buckets.forEach((b) => {
      const ts = new Date(b.hour_bucket).getTime();
      const idx = Math.floor((ts - start) / 3_600_000);
      bucketByHour.set(idx, b);
    });

    // Draw bars (hours without data → grey low-opacity placeholder)
    for (let h = 0; h < hours; h++) {
      const bucket = bucketByHour.get(h);
      const x = PAD.left + h * barW;
      if (bucket) {
        const barH = ((bucket.severity + 0.05) / 3) * innerH; // tiny floor so OK is visible
        const y = PAD.top + innerH - barH;
        const cls = SEVERITY_CLASS[Math.round(bucket.severity)] || 'bar--nodata';
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('class', `bar ${cls}`);
        rect.setAttribute('x', x);
        rect.setAttribute('y', y);
        rect.setAttribute('width', Math.max(barW - 1, 1));
        rect.setAttribute('height', Math.max(barH, 2));
        rect.dataset.bucket = JSON.stringify(bucket);
        rect.addEventListener('mouseenter', _onBucketHover);
        rect.addEventListener('mouseleave', _hideTooltip);
        svg.appendChild(rect);
      } else {
        // gap rendering — thin grey strip on baseline
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('class', 'bar bar--nodata');
        rect.setAttribute('x', x);
        rect.setAttribute('y', PAD.top + innerH - 2);
        rect.setAttribute('width', Math.max(barW - 1, 1));
        rect.setAttribute('height', 2);
        rect.setAttribute('opacity', '0.25');
        svg.appendChild(rect);
      }
    }

    // X-axis labels — show ~6 evenly spaced ticks
    const tickCount = 6;
    for (let i = 0; i <= tickCount; i++) {
      const t0 = start + (i / tickCount) * (end - start);
      const x = PAD.left + (i / tickCount) * innerW;
      const lbl = _formatTick(new Date(t0));
      _appendText(svg, x, H - 8, lbl, 'axis-label', 'middle');
    }

    // Deploy markers (vertical dashed line + triangle)
    t.deploys.forEach((d) => {
      const ts = new Date(d.deployed_at).getTime();
      if (ts < start || ts > end) return;
      const x = PAD.left + ((ts - start) / (end - start)) * innerW;
      _appendLine(
        svg, x, PAD.top, x, H - PAD.bottom,
        d.is_failure ? 'deploy-line deploy-line--fail' : 'deploy-line',
      );
      const tri = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      const triClass = d.is_failure ? 'deploy-tri deploy-tri--fail' : 'deploy-tri';
      tri.setAttribute('class', triClass);
      tri.setAttribute(
        'points',
        `${x - 5},${PAD.top - 2} ${x + 5},${PAD.top - 2} ${x},${PAD.top + 6}`,
      );
      tri.dataset.deploy = JSON.stringify(d);
      tri.addEventListener('mouseenter', _onDeployHover);
      tri.addEventListener('mouseleave', _hideTooltip);
      svg.appendChild(tri);
    });
  }

  // -------------------------------------------------
  // Tooltip
  // -------------------------------------------------
  function _onBucketHover(e) {
    const b = JSON.parse(e.target.dataset.bucket);
    const lines = [
      `<div class="tooltip__title">${SEVERITY_LABEL[Math.round(b.severity)]}</div>`,
      `<div class="tooltip__line">${_formatHour(b.hour_bucket)}</div>`,
      `<div class="tooltip__line">Severidade: ${b.severity.toFixed(2)}</div>`,
      `<div class="tooltip__line">Aggregated from ${b.samples_count} monitor(s)</div>`,
    ];
    _showTooltip(e, lines.join(''));
  }

  function _onDeployHover(e) {
    const d = JSON.parse(e.target.dataset.deploy);
    const lines = [
      `<div class="tooltip__title">${d.is_failure ? '⚠️ Failed deploy' : 'Deploy'}</div>`,
      `<div class="tooltip__line">${_formatHour(d.deployed_at)}</div>`,
      `<div class="tooltip__line">${_escape(d.repo)} · ${_escape(d.environment || '?')}</div>`,
      `<div class="tooltip__line">SHA: ${_escape(d.sha || '?').substring(0, 8)}</div>`,
    ];
    _showTooltip(e, lines.join(''));
  }

  function _showTooltip(e, html) {
    const t = document.getElementById('tooltip');
    t.innerHTML = html;
    t.hidden = false;
    const rect = t.getBoundingClientRect();
    let left = e.clientX + 12;
    let top = e.clientY + 12;
    if (left + rect.width > window.innerWidth - 8) left = window.innerWidth - rect.width - 8;
    if (top + rect.height > window.innerHeight - 8) top = e.clientY - rect.height - 12;
    t.style.left = `${left}px`;
    t.style.top = `${top}px`;
  }

  function _hideTooltip() {
    document.getElementById('tooltip').hidden = true;
  }

  // -------------------------------------------------
  // Deploys table
  // -------------------------------------------------
  function _renderDeploysTable() {
    const tbody = document.getElementById('deploys-tbody');
    const t = STATE.timeline;
    if (!t || t.deploys.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="6" class="table__empty">Sem deploys no período.</td></tr>';
      return;
    }
    tbody.innerHTML = t.deploys.map(_renderDeployRow).join('');
  }

  function _renderDeployRow(d) {
    const status = d.is_failure
      ? '<span class="status-fail">✗ Failed</span>'
      : '<span class="status-ok">✓ OK</span>';
    return `
      <tr>
        <td>${_formatHour(d.deployed_at)}</td>
        <td><span class="repo-cell">${_escape(d.repo)}</span></td>
        <td>${d.environment ? `<span class="env-cell">${_escape(d.environment)}</span>` : '—'}</td>
        <td>${d.sha ? `<span class="sha-cell">${_escape(d.sha).substring(0, 8)}</span>` : '—'}</td>
        <td>${status}</td>
        <td>${d.url ? `<a href="${_escape(d.url)}" target="_blank" rel="noopener">link</a>` : '—'}</td>
      </tr>
    `;
  }

  // -------------------------------------------------
  // Events
  // -------------------------------------------------
  function _wireEvents() {
    document.getElementById('filter-squad').addEventListener('change', (e) => {
      STATE.squad = e.target.value;
      // Live: would re-fetch /timeline with new squad. Prototype reuses
      // the same fixture but updates the squad label.
      _renderKpis();
    });
    document.getElementById('filter-window').addEventListener('change', (e) => {
      STATE.windowHours = parseInt(e.target.value, 10);
      _renderKpis();
      _renderChart();
    });
    document.getElementById('btn-refresh').addEventListener('click', async () => {
      await _load();
      _renderKpis();
      _renderChart();
      _renderDeploysTable();
    });
  }

  // -------------------------------------------------
  // SVG helpers
  // -------------------------------------------------
  function _appendLine(svg, x1, y1, x2, y2, cls) {
    const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    ln.setAttribute('x1', x1);
    ln.setAttribute('y1', y1);
    ln.setAttribute('x2', x2);
    ln.setAttribute('y2', y2);
    ln.setAttribute('class', cls);
    if (cls === 'axis-grid') {
      ln.setAttribute('stroke', '#E5E7EB');
      ln.setAttribute('stroke-width', '1');
      ln.setAttribute('stroke-dasharray', '2 4');
    }
    svg.appendChild(ln);
    return ln;
  }

  function _appendText(svg, x, y, text, cls, anchor) {
    const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('x', x);
    t.setAttribute('y', y);
    t.setAttribute('class', cls);
    if (anchor) t.setAttribute('text-anchor', anchor);
    t.textContent = text;
    svg.appendChild(t);
    return t;
  }

  // -------------------------------------------------
  // Formatters
  // -------------------------------------------------
  function _formatHour(iso) {
    const d = new Date(iso);
    const dd = String(d.getUTCDate()).padStart(2, '0');
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    const hh = String(d.getUTCHours()).padStart(2, '0');
    const mi = String(d.getUTCMinutes()).padStart(2, '0');
    return `${dd}/${mm} ${hh}:${mi}Z`;
  }

  function _formatTick(d) {
    const dd = String(d.getUTCDate()).padStart(2, '0');
    const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
    const hh = String(d.getUTCHours()).padStart(2, '0');
    return `${dd}/${mm} ${hh}h`;
  }

  function _escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
})();
