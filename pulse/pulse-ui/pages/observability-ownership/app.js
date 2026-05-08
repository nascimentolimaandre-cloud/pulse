/* ============================================================
   PULSE · Service Ownership Map (Settings → Integrations)
   FDD-OBS-001 PR 3 — vanilla JS, prototype against fixture JSON.
   When wired to the live API, swap _loadFixture for fetch() to
   GET /data/v1/admin/integrations/datadog/ownership.
   ============================================================ */

(() => {
  'use strict';

  const STATE = {
    services: [],
    coveragePct: 0,
    qualifiedSquads: [],
    activeService: null,
  };

  // ----------------------------------------------------------------
  // Boot
  // ----------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', async () => {
    await Promise.all([_loadOwnership(), _loadSquads()]);
    _renderKpis();
    _renderTable();
    _wireEvents();
  });

  // ----------------------------------------------------------------
  // Data loaders (fixture for prototype; replace with fetch in PR 4+)
  // ----------------------------------------------------------------

  async function _loadOwnership() {
    try {
      const res = await fetch('./fixtures/ownership.json');
      const data = await res.json();
      STATE.services = data.services || [];
      STATE.coveragePct = data.coverage_pct || 0;
    } catch (err) {
      console.error('Failed to load ownership fixture', err);
      STATE.services = [];
    }
  }

  async function _loadSquads() {
    try {
      const res = await fetch('./fixtures/squads.json');
      const data = await res.json();
      STATE.qualifiedSquads = data.qualified_squads || [];
    } catch (err) {
      console.error('Failed to load squads fixture', err);
    }
  }

  // ----------------------------------------------------------------
  // KPI rendering
  // ----------------------------------------------------------------

  function _renderKpis() {
    const total = STATE.services.length;
    const inferredTag = STATE.services.filter(
      (s) => s.inferred_confidence === 'tag',
    ).length;
    const overrides = STATE.services.filter((s) => s.override_squad_key).length;

    document.getElementById('kpi-total').textContent = String(total);
    document.getElementById('kpi-coverage').textContent =
      total === 0 ? '—' : `${Math.round(STATE.coveragePct * 100)}%`;
    document.getElementById('kpi-tag').textContent = String(inferredTag);
    document.getElementById('kpi-override').textContent = String(overrides);

    const lastSync = _latestInferenceAt();
    document.getElementById('last-sync').textContent = lastSync
      ? `Última sync: ${_formatRelative(lastSync)}`
      : 'Nunca executado';
  }

  function _latestInferenceAt() {
    let max = null;
    for (const s of STATE.services) {
      const t = s.last_inference_at ? new Date(s.last_inference_at) : null;
      if (t && (!max || t > max)) max = t;
    }
    return max;
  }

  function _formatRelative(date) {
    const diffMs = Date.now() - date.getTime();
    const min = Math.round(diffMs / 60000);
    if (min < 1) return 'agora há pouco';
    if (min < 60) return `há ${min} min`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `há ${hr}h`;
    const day = Math.round(hr / 24);
    return `há ${day}d`;
  }

  // ----------------------------------------------------------------
  // Table rendering
  // ----------------------------------------------------------------

  function _renderTable(filterText) {
    const tbody = document.getElementById('ownership-tbody');
    const term = (filterText || '').trim().toLowerCase();
    const rows = STATE.services.filter((s) =>
      term ? s.service_name.toLowerCase().includes(term) : true,
    );

    if (rows.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="6" class="table__empty">Nenhum service encontrado.</td></tr>';
      return;
    }

    tbody.innerHTML = rows.map(_renderRow).join('');
  }

  function _renderRow(svc) {
    const inferredCell = svc.inferred_squad_key
      ? `<span class="squad-tag squad-tag--inferred">${_escape(
          svc.inferred_squad_key,
        )}</span>`
      : '<span class="squad-tag squad-tag--null">— sem tag —</span>';

    const overrideCell = svc.override_squad_key
      ? `<span class="squad-tag squad-tag--override">${_escape(
          svc.override_squad_key,
        )}</span>`
      : '<span class="squad-tag squad-tag--null">—</span>';

    const effectiveCell = svc.effective_squad_key
      ? `<span class="squad-tag">${_escape(svc.effective_squad_key)}</span>`
      : '<span class="squad-tag squad-tag--null">— sem dono —</span>';

    const status = _statusBadge(svc);

    const repo = svc.repo_url
      ? `<span class="svc-repo"><a href="${_escape(
          svc.repo_url,
        )}" target="_blank" rel="noopener">${_escape(svc.repo_url)}</a></span>`
      : '';

    return `
      <tr data-svc-id="${_escape(svc.service_external_id)}">
        <td>
          <span class="svc-name">${_escape(svc.service_name)}</span>
          ${repo}
        </td>
        <td>${inferredCell}</td>
        <td>${overrideCell}</td>
        <td>${effectiveCell}</td>
        <td>${status}</td>
        <td class="table__actions-col">
          <button class="btn btn--small" type="button" data-action="override"
                  data-svc-id="${_escape(svc.service_external_id)}">
            ${svc.override_squad_key ? 'Editar' : 'Definir'}
          </button>
        </td>
      </tr>
    `;
  }

  function _statusBadge(svc) {
    if (svc.is_qualified_squad) {
      return '<span class="badge badge--ok">qualificado</span>';
    }
    if (svc.effective_squad_key) {
      return '<span class="badge badge--warn">tag fora do tenant</span>';
    }
    if (svc.inferred_confidence === 'none') {
      return '<span class="badge badge--neutral">sem dono</span>';
    }
    return '<span class="badge badge--danger">sem effective</span>';
  }

  function _escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // ----------------------------------------------------------------
  // Events
  // ----------------------------------------------------------------

  function _wireEvents() {
    // Filter
    document.getElementById('filter').addEventListener('input', (e) => {
      _renderTable(e.target.value);
    });

    // Sync button (prototype-only — would call POST /sync in live)
    document.getElementById('btn-sync').addEventListener('click', _onSyncClick);

    // Override actions (delegated)
    document.getElementById('ownership-tbody').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-action="override"]');
      if (!btn) return;
      const svcId = btn.dataset.svcId;
      const svc = STATE.services.find((s) => s.service_external_id === svcId);
      if (svc) _openModal(svc);
    });

    // Modal close
    document.querySelectorAll('[data-modal-close]').forEach((el) => {
      el.addEventListener('click', _closeModal);
    });

    // Modal save
    document
      .getElementById('btn-save-override')
      .addEventListener('click', _onSaveOverride);

    // Esc closes modal
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') _closeModal();
    });
  }

  async function _onSyncClick() {
    const btn = document.getElementById('btn-sync');
    btn.disabled = true;
    btn.textContent = 'Running…';
    // In live: await fetch('/data/v1/admin/integrations/datadog/ownership/sync', {method:'POST'})
    await new Promise((r) => setTimeout(r, 600));
    document.getElementById('last-sync').textContent =
      'Última sync: agora há pouco';
    btn.disabled = false;
    btn.textContent = 'Run inference';
  }

  function _onSaveOverride() {
    const select = document.getElementById('modal-squad-select');
    const newKey = select.value || null;
    const svc = STATE.activeService;
    if (!svc) return;

    // Mutate the in-memory state (prototype). Live: PUT /override.
    svc.override_squad_key = newKey;
    svc.effective_squad_key = newKey || svc.inferred_squad_key;
    svc.is_qualified_squad =
      !!svc.effective_squad_key &&
      STATE.qualifiedSquads.some((q) => q.key === svc.effective_squad_key);

    // Recompute coverage
    const total = STATE.services.length;
    const qualified = STATE.services.filter((s) => s.is_qualified_squad).length;
    STATE.coveragePct = total === 0 ? 0 : qualified / total;

    _renderKpis();
    _renderTable(document.getElementById('filter').value);
    _closeModal();
  }

  // ----------------------------------------------------------------
  // Modal
  // ----------------------------------------------------------------

  function _openModal(svc) {
    STATE.activeService = svc;
    document.getElementById('modal-service-name').textContent = svc.service_name;
    document.getElementById('modal-inferred').textContent =
      svc.inferred_squad_key || '— sem tag —';

    const select = document.getElementById('modal-squad-select');
    select.innerHTML =
      '<option value="">— Manter inferência —</option>' +
      STATE.qualifiedSquads
        .map(
          (q) =>
            `<option value="${_escape(q.key)}">${_escape(q.key)} — ${_escape(
              q.name,
            )}</option>`,
        )
        .join('');
    select.value = svc.override_squad_key || '';

    document.getElementById('override-modal').hidden = false;
    select.focus();
  }

  function _closeModal() {
    document.getElementById('override-modal').hidden = true;
    STATE.activeService = null;
  }
})();
