import { useState, useCallback } from 'react';
import { createRoute } from '@tanstack/react-router';
import {
  Search,
  Download,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Settings,
  Play,
  Pause,
  Ban,
  RotateCcw,
  AlertTriangle,
  ShieldAlert,
} from 'lucide-react';
import { jiraSettingsRoute } from './jira';
import { useJiraAuditQuery } from '@/hooks/useJiraAdmin';
import type { JiraAuditEventType, JiraDiscoveryAuditEntry, JiraAuditQuery } from '@pulse/shared';

export const jiraAuditRoute = createRoute({
  getParentRoute: () => jiraSettingsRoute,
  path: '/audit',
  component: JiraAuditTab,
});

const PAGE_SIZE = 25;

// ---------------------------------------------------------------------------
// Event type config
// ---------------------------------------------------------------------------

interface EventTypeMeta {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  color: string;
}

const EVENT_TYPE_META: Record<JiraAuditEventType, EventTypeMeta> = {
  discovery_run: { icon: RefreshCw, label: 'Descoberta executada', color: 'text-status-info' },
  mode_changed: { icon: Settings, label: 'Modo alterado', color: 'text-brand-primary' },
  project_activated: { icon: Play, label: 'Projeto ativado', color: 'text-status-success' },
  project_paused: { icon: Pause, label: 'Projeto pausado', color: 'text-status-warning' },
  project_blocked: { icon: Ban, label: 'Projeto bloqueado', color: 'text-status-danger' },
  project_resumed: { icon: RotateCcw, label: 'Projeto retomado', color: 'text-status-info' },
  project_auto_paused: {
    icon: AlertTriangle,
    label: 'Auto-pausado (falhas)',
    color: 'text-status-warning',
  },
  project_cap_enforced: {
    icon: ShieldAlert,
    label: 'Cap aplicado',
    color: 'text-status-danger',
  },
  project_pii_flagged: {
    icon: ShieldAlert,
    label: 'Nome sensível detectado',
    color: 'text-status-warning',
  },
  project_pii_gated: {
    icon: Ban,
    label: 'Ativação bloqueada (PII)',
    color: 'text-status-danger',
  },
};

const EVENT_TYPE_OPTIONS: JiraAuditEventType[] = [
  'discovery_run',
  'mode_changed',
  'project_activated',
  'project_paused',
  'project_blocked',
  'project_resumed',
  'project_auto_paused',
  'project_cap_enforced',
  'project_pii_flagged',
  'project_pii_gated',
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

function JiraAuditTab() {
  const [eventTypeFilter, setEventTypeFilter] = useState<JiraAuditEventType | ''>('');
  const [projectKeyFilter, setProjectKeyFilter] = useState('');
  const [offset, setOffset] = useState(0);

  const query: JiraAuditQuery = {
    eventType: eventTypeFilter || undefined,
    projectKey: projectKeyFilter || undefined,
    limit: PAGE_SIZE,
    offset,
  };

  const { data, isLoading, isError, error } = useJiraAuditQuery(query);

  const total = data?.total ?? 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // CSV export from current page data
  const handleExport = useCallback(() => {
    if (!data || data.items.length === 0) return;

    const headers = ['Data', 'Tipo', 'Projeto', 'Ator', 'Antes', 'Depois', 'Motivo'];
    const rows = data.items.map((e) => [
      new Date(e.createdAt).toISOString(),
      e.eventType,
      e.projectKey ?? '',
      e.actor,
      JSON.stringify(e.beforeValue ?? ''),
      JSON.stringify(e.afterValue ?? ''),
      e.reason ?? '',
    ]);

    const csv = [headers, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `jira-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [data]);

  if (isError) {
    return (
      <div className="py-12 text-center">
        <p className="text-sm text-status-danger">
          Falha ao carregar auditoria: {error instanceof Error ? error.message : 'Erro desconhecido'}
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={eventTypeFilter}
          onChange={(e) => {
            setEventTypeFilter(e.target.value as JiraAuditEventType | '');
            setOffset(0);
          }}
          className="h-8 rounded-button border border-border-default bg-surface-primary px-2 text-xs text-content-primary"
          aria-label="Filtrar por tipo de evento"
        >
          <option value="">Todos os tipos</option>
          {EVENT_TYPE_OPTIONS.map((et) => (
            <option key={et} value={et}>
              {EVENT_TYPE_META[et].label}
            </option>
          ))}
        </select>

        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
          <input
            type="text"
            placeholder="Filtrar por projeto..."
            value={projectKeyFilter}
            onChange={(e) => {
              setProjectKeyFilter(e.target.value);
              setOffset(0);
            }}
            className="h-8 w-44 rounded-button border border-border-default bg-surface-primary pl-8 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none"
            aria-label="Filtrar por chave do projeto"
          />
        </div>

        <button
          type="button"
          onClick={handleExport}
          disabled={!data || data.items.length === 0}
          className="ml-auto inline-flex items-center gap-1.5 rounded-button border border-border-default px-3 py-1.5 text-xs font-medium text-content-primary transition-colors hover:bg-surface-tertiary disabled:opacity-40"
          aria-label="Exportar auditoria como CSV"
        >
          <Download className="h-3.5 w-3.5" />
          Exportar CSV
        </button>
      </div>

      {/* Timeline */}
      {isLoading ? (
        <AuditSkeleton />
      ) : !data || data.items.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-sm text-content-secondary">Nenhum evento de auditoria encontrado.</p>
        </div>
      ) : (
        <div className="space-y-0">
          {data.items.map((entry) => (
            <AuditTimelineItem key={entry.id} entry={entry} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between">
          <span className="text-xs text-content-secondary">
            {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} de {total}
          </span>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0}
              className="rounded-button p-1.5 text-content-secondary hover:bg-surface-tertiary disabled:opacity-30"
              aria-label="Pagina anterior"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="flex items-center px-2 text-xs text-content-secondary">
              {currentPage} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total}
              className="rounded-button p-1.5 text-content-secondary hover:bg-surface-tertiary disabled:opacity-30"
              aria-label="Proxima pagina"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Timeline item
// ---------------------------------------------------------------------------

function AuditTimelineItem({ entry }: { entry: JiraDiscoveryAuditEntry }) {
  const meta = EVENT_TYPE_META[entry.eventType];
  const Icon = meta.icon;

  return (
    <div className="flex gap-3 border-l-2 border-border-default py-3 pl-4">
      <div
        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-tertiary ${meta.color}`}
      >
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-sm font-medium text-content-primary">{meta.label}</span>
          {entry.projectKey && (
            <span className="font-mono text-xs font-semibold text-brand-primary">
              {entry.projectKey}
            </span>
          )}
          <span className="text-xs text-content-tertiary">
            {new Date(entry.createdAt).toLocaleString()}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-content-secondary">
          <span>por {entry.actor}</span>
          {entry.reason && <span>- {entry.reason}</span>}
        </div>
        {/* Before/After diff */}
        {(entry.beforeValue != null || entry.afterValue != null) && (
          <div className="mt-1 flex gap-2 text-xs">
            {entry.beforeValue != null && (
              <span className="rounded bg-red-50 px-1.5 py-0.5 text-status-danger">
                {formatValue(entry.beforeValue)}
              </span>
            )}
            {entry.beforeValue != null && entry.afterValue != null && (
              <span className="text-content-tertiary">&rarr;</span>
            )}
            {entry.afterValue != null && (
              <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-status-success">
                {formatValue(entry.afterValue)}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function formatValue(val: unknown): string {
  if (typeof val === 'string') return val;
  if (typeof val === 'number' || typeof val === 'boolean') return String(val);
  return JSON.stringify(val);
}

function AuditSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex gap-3 border-l-2 border-border-default py-3 pl-4">
          <div className="h-7 w-7 animate-pulse rounded-full bg-surface-tertiary" />
          <div className="flex-1 space-y-1.5">
            <div className="h-4 w-48 animate-pulse rounded bg-surface-tertiary" />
            <div className="h-3 w-32 animate-pulse rounded bg-surface-tertiary" />
          </div>
        </div>
      ))}
    </div>
  );
}
