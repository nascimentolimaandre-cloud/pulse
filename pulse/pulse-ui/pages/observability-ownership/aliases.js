/* ============================================================
   PULSE · Team Aliases page (FDD-OBS-001 PR 3.5)
   Backed by fixture JSON in prototype; swap for fetch() against
   the live admin API once R1 auth lands.
   ============================================================ */

(() => {
  'use strict';

  const STATE = {
    aliases: [],
    suggestions: [],
    qualifiedSquads: [],
    activeAlias: null,
  };

  // ----------------------------------------------------------------
  // Boot
  // ----------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', async () => {
    await Promise.all([_loadAliases(), _loadSquads()]);
    _renderSuggestions();
    _renderTable();
    _wireEvents();
  });

  // ----------------------------------------------------------------
  // Data loaders
  // ----------------------------------------------------------------

  async function _loadAliases() {
    try {
      const res = await fetch('./fixtures/aliases.json');
      const data = await res.json();
      STATE.aliases = data.aliases || [];
      STATE.suggestions = data.suggestions || [];
    } catch (err) {
      console.error('Failed to load aliases fixture', err);
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
  // Suggestions banner
  // ----------------------------------------------------------------

  function _renderSuggestions() {
    const section = document.getElementById('suggestions-section');
    if (!STATE.suggestions || STATE.suggestions.length === 0) {
      section.hidden = true;
      return;
    }
    section.hidden = false;
    document.getElementById('suggestions-count').textContent =
      String(STATE.suggestions.length);
    const list = document.getElementById('suggestions-list');
    list.innerHTML = STATE.suggestions
      .map((t) => `<li>${_escape(t)}</li>`)
      .join('');
  }

  // ----------------------------------------------------------------
  // Aliases table
  // ----------------------------------------------------------------

  function _renderTable(filterText) {
    const tbody = document.getElementById('aliases-tbody');
    const term = (filterText || '').trim().toLowerCase();
    const rows = STATE.aliases.filter((a) =>
      term
        ? a.vendor_team_value.toLowerCase().includes(term) ||
          a.squad_key.toLowerCase().includes(term)
        : true,
    );

    if (rows.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="5" class="table__empty">' +
        'Nenhum alias configurado. Use o paste mode ao lado pra começar.' +
        '</td></tr>';
      return;
    }

    tbody.innerHTML = rows.map(_renderRow).join('');
  }

  function _renderRow(alias) {
    return `
      <tr data-vendor="${_escape(alias.vendor_team_value)}">
        <td><span class="alias-vendor">${_escape(alias.vendor_team_value)}</span></td>
        <td><span class="alias-arrow">→</span></td>
        <td><span class="alias-squad">${_escape(alias.squad_key)}</span></td>
        <td><span class="alias-time">${_formatRelative(alias.updated_at)}</span></td>
        <td class="table__actions-col">
          <button class="btn btn--small" type="button" data-action="edit"
                  data-vendor="${_escape(alias.vendor_team_value)}">
            Editar
          </button>
          <button class="btn btn--small btn--danger" type="button" data-action="delete"
                  data-vendor="${_escape(alias.vendor_team_value)}">
            Remover
          </button>
        </td>
      </tr>
    `;
  }

  function _formatRelative(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const diffMin = Math.round((Date.now() - d.getTime()) / 60000);
    if (diffMin < 1) return 'agora';
    if (diffMin < 60) return `há ${diffMin} min`;
    const hr = Math.round(diffMin / 60);
    if (hr < 24) return `há ${hr}h`;
    const day = Math.round(hr / 24);
    return `há ${day}d`;
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
    document.getElementById('filter').addEventListener('input', (e) => {
      _renderTable(e.target.value);
    });

    document.getElementById('aliases-tbody').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-action]');
      if (!btn) return;
      const vendor = btn.dataset.vendor;
      if (btn.dataset.action === 'edit') {
        const alias = STATE.aliases.find((a) => a.vendor_team_value === vendor);
        if (alias) _openEditModal(alias);
      } else if (btn.dataset.action === 'delete') {
        if (confirm(`Remover alias para "${vendor}"?`)) _doDelete(vendor);
      }
    });

    document.querySelectorAll('[data-modal-close]').forEach((el) => {
      el.addEventListener('click', _closeModal);
    });

    document
      .getElementById('btn-save-edit')
      .addEventListener('click', _doSaveEdit);

    document
      .getElementById('btn-import')
      .addEventListener('click', _doBulkImport);
    document.getElementById('btn-clear').addEventListener('click', () => {
      document.getElementById('bulk-input').value = '';
      document.getElementById('bulk-result').hidden = true;
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') _closeModal();
    });
  }

  function _doDelete(vendor) {
    // Live: DELETE /aliases/{vendor}
    STATE.aliases = STATE.aliases.filter((a) => a.vendor_team_value !== vendor);
    _renderTable(document.getElementById('filter').value);
  }

  function _doSaveEdit() {
    const select = document.getElementById('edit-squad-select');
    const newSquad = select.value;
    const alias = STATE.activeAlias;
    if (!alias || !newSquad) return _closeModal();

    // Live: PUT /aliases/{vendor}
    alias.squad_key = newSquad;
    alias.updated_at = new Date().toISOString();
    _renderTable(document.getElementById('filter').value);
    _closeModal();
  }

  function _doBulkImport() {
    const text = document.getElementById('bulk-input').value;
    const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
    let inserted = 0,
      updated = 0,
      rejectedSquad = 0,
      rejectedEmpty = 0;
    const qualifiedSet = new Set(STATE.qualifiedSquads.map((q) => q.key));

    lines.forEach((line) => {
      const parts = line.split(',').map((p) => p.trim());
      if (parts.length !== 2 || !parts[0] || !parts[1]) {
        rejectedEmpty += 1;
        return;
      }
      const [vendor, squad] = parts;
      const lower = vendor.toLowerCase();
      if (!qualifiedSet.has(squad)) {
        rejectedSquad += 1;
        return;
      }
      const existing = STATE.aliases.find((a) => a.vendor_team_value === lower);
      if (existing) {
        existing.squad_key = squad;
        existing.updated_at = new Date().toISOString();
        updated += 1;
      } else {
        STATE.aliases.push({
          vendor_team_value: lower,
          squad_key: squad,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
        inserted += 1;
      }
      // Mark this vendor as no longer "unmapped"
      STATE.suggestions = STATE.suggestions.filter((t) => t !== lower);
    });

    const result = document.getElementById('bulk-result');
    result.hidden = false;
    const total = lines.length;
    const applied = inserted + updated;
    if (applied > 0 && rejectedSquad === 0 && rejectedEmpty === 0) {
      result.className = 'bulk__result bulk__result--ok';
      result.textContent = `Importadas ${applied} de ${total} (${inserted} novas, ${updated} atualizadas).`;
    } else if (applied > 0) {
      result.className = 'bulk__result bulk__result--warn';
      result.textContent =
        `Importadas ${applied} de ${total}. ` +
        `${rejectedSquad} squad inválido, ${rejectedEmpty} vazias.`;
    } else {
      result.className = 'bulk__result bulk__result--warn';
      result.textContent = `Nenhuma linha aplicada (${rejectedSquad} squad inválido, ${rejectedEmpty} vazias).`;
    }

    _renderSuggestions();
    _renderTable(document.getElementById('filter').value);
  }

  // ----------------------------------------------------------------
  // Edit modal
  // ----------------------------------------------------------------

  function _openEditModal(alias) {
    STATE.activeAlias = alias;
    document.getElementById('edit-vendor-name').textContent =
      alias.vendor_team_value;

    const select = document.getElementById('edit-squad-select');
    select.innerHTML = STATE.qualifiedSquads
      .map(
        (q) =>
          `<option value="${_escape(q.key)}">${_escape(q.key)} — ${_escape(q.name)}</option>`,
      )
      .join('');
    select.value = alias.squad_key;

    document.getElementById('edit-modal').hidden = false;
    select.focus();
  }

  function _closeModal() {
    document.getElementById('edit-modal').hidden = true;
    STATE.activeAlias = null;
  }
})();
