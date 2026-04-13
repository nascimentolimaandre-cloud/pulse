import { useState, useCallback } from 'react';
import { Search, ChevronLeft, ChevronRight, X, ArrowUpDown, ShieldAlert } from 'lucide-react';
import type {
  JiraProjectStatus,
  JiraProjectCatalogQuery,
  JiraProjectCatalogEntry,
} from '@pulse/shared';
import { useJiraProjectsQuery, useJiraProjectQuery, useBulkProjectActionMutation } from '@/hooks/useJiraAdmin';
import { ProjectRowActions } from './project-row-actions';

// ---------------------------------------------------------------------------
// Status chip
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<JiraProjectStatus, { bg: string; text: string; label: string }> = {
  discovered: { bg: 'bg-blue-50', text: 'text-status-info', label: 'Descoberto' },
  active: { bg: 'bg-emerald-50', text: 'text-status-success', label: 'Ativo' },
  paused: { bg: 'bg-amber-50', text: 'text-status-warning', label: 'Pausado' },
  blocked: { bg: 'bg-red-50', text: 'text-status-danger', label: 'Bloqueado' },
  archived: { bg: 'bg-gray-100', text: 'text-content-tertiary', label: 'Arquivado' },
};

function StatusChip({ status }: { status: JiraProjectStatus }) {
  const style = STATUS_STYLES[status];
  return (
    <span
      className={`inline-flex items-center rounded-badge px-2 py-0.5 text-xs font-medium ${style.bg} ${style.text}`}
    >
      {style.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Filter chips row
// ---------------------------------------------------------------------------

type FilterStatus = JiraProjectStatus | 'all';

const FILTER_OPTIONS: { value: FilterStatus; label: string }[] = [
  { value: 'all', label: 'Todos' },
  { value: 'discovered', label: 'Descobertos' },
  { value: 'active', label: 'Ativos' },
  { value: 'paused', label: 'Pausados' },
  { value: 'blocked', label: 'Bloqueados' },
  { value: 'archived', label: 'Arquivados' },
];

const SORT_OPTIONS: { value: NonNullable<JiraProjectCatalogQuery['sortBy']>; label: string }[] = [
  { value: 'project_key', label: 'Chave' },
  { value: 'pr_reference_count', label: 'PRs referenciando' },
  { value: 'issue_count', label: 'Issues' },
  { value: 'last_sync_at', label: 'Ultima sync' },
];

const PAGE_SIZE = 20;

// ---------------------------------------------------------------------------
// Side panel for project detail
// ---------------------------------------------------------------------------

function ProjectDetailPanel({
  projectKey,
  onClose,
}: {
  projectKey: string;
  onClose: () => void;
}) {
  const { data, isLoading } = useJiraProjectQuery(projectKey);

  return (
    <div
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border-default bg-surface-primary shadow-card"
      role="dialog"
      aria-modal="true"
      aria-label={`Detalhes do projeto ${projectKey}`}
    >
      <div className="flex items-center justify-between border-b border-border-default p-card-padding">
        <h3 className="text-base font-semibold text-content-primary">Projeto {projectKey}</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded-button p-1.5 text-content-secondary hover:bg-surface-tertiary hover:text-content-primary"
          aria-label="Fechar painel"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-card-padding">
        {isLoading || !data ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-4 w-full animate-pulse rounded bg-surface-tertiary" />
            ))}
          </div>
        ) : (
          <dl className="space-y-4">
            <DetailRow label="Nome" value={data.name ?? '-'} />
            <DetailRow label="Status">
              <StatusChip status={data.status} />
            </DetailRow>
            <DetailRow label="Tipo de projeto" value={data.projectType ?? '-'} />
            <DetailRow label="Fonte de ativacao" value={data.activationSource ?? '-'} />
            <DetailRow label="Issues" value={String(data.issueCount)} />
            <DetailRow label="PRs referenciando" value={String(data.prReferenceCount)} />
            <DetailRow
              label="Primeira vez visto"
              value={new Date(data.firstSeenAt).toLocaleString()}
            />
            <DetailRow
              label="Ultima sync"
              value={data.lastSyncAt ? new Date(data.lastSyncAt).toLocaleString() : 'Nunca'}
            />
            <DetailRow
              label="Status ultima sync"
              value={data.lastSyncStatus ?? '-'}
            />

            {data.consecutiveFailures > 0 && (
              <>
                <DetailRow
                  label="Falhas consecutivas"
                  value={String(data.consecutiveFailures)}
                />
                {data.lastError && (
                  <div>
                    <dt className="text-xs font-medium text-content-secondary">Ultimo erro</dt>
                    <dd className="mt-1 rounded bg-red-50 p-2 text-xs text-status-danger">
                      {data.lastError}
                    </dd>
                  </div>
                )}
              </>
            )}
          </dl>
        )}
      </div>
    </div>
  );
}

function DetailRow({
  label,
  value,
  children,
}: {
  label: string;
  value?: string;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-medium text-content-secondary">{label}</dt>
      <dd className="mt-0.5 text-sm text-content-primary">{children ?? value}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table skeleton
// ---------------------------------------------------------------------------

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 py-3">
          <div className="h-4 w-4 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-16 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-32 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-16 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-12 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-12 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-20 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-6 animate-pulse rounded bg-surface-tertiary" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main table
// ---------------------------------------------------------------------------

export function ProjectCatalogTable() {
  const [statusFilter, setStatusFilter] = useState<FilterStatus>('all');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<JiraProjectCatalogQuery['sortBy']>('pr_reference_count');
  const [sortDir, setSortDir] = useState<JiraProjectCatalogQuery['sortDir']>('desc');
  const [offset, setOffset] = useState(0);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [detailKey, setDetailKey] = useState<string | null>(null);

  const query: JiraProjectCatalogQuery = {
    status: statusFilter === 'all' ? undefined : statusFilter,
    search: search || undefined,
    sortBy,
    sortDir,
    limit: PAGE_SIZE,
    offset,
  };

  const { data, isLoading, isError, error } = useJiraProjectsQuery(query);
  const bulkAction = useBulkProjectActionMutation();

  const toggleSort = useCallback(
    (col: NonNullable<JiraProjectCatalogQuery['sortBy']>) => {
      if (sortBy === col) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortBy(col);
        setSortDir('desc');
      }
      setOffset(0);
    },
    [sortBy],
  );

  const toggleSelectAll = useCallback(() => {
    if (!data) return;
    const allKeys = new Set(data.items.map((p) => p.projectKey));
    setSelectedKeys((prev) => (prev.size === allKeys.size ? new Set() : allKeys));
  }, [data]);

  const toggleSelect = useCallback((key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const hasSelected = selectedKeys.size > 0;
  const total = data?.total ?? 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Error state
  if (isError) {
    return (
      <div className="py-12 text-center">
        <p className="text-sm text-status-danger">
          Falha ao carregar projetos: {error instanceof Error ? error.message : 'Erro desconhecido'}
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Filters row */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {/* Status chips */}
        <div className="flex flex-wrap gap-1.5">
          {FILTER_OPTIONS.map((opt) => {
            const isActive = statusFilter === opt.value;
            const count =
              opt.value === 'all'
                ? total
                : data?.counts[opt.value as JiraProjectStatus] ?? 0;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  setStatusFilter(opt.value);
                  setOffset(0);
                  setSelectedKeys(new Set());
                }}
                className={`inline-flex items-center gap-1 rounded-badge px-2.5 py-1 text-xs font-medium transition-colors ${
                  isActive
                    ? 'bg-brand-primary text-content-inverse'
                    : 'bg-surface-tertiary text-content-secondary hover:bg-surface-secondary'
                }`}
              >
                {opt.label}
                {!isLoading && <span className="opacity-70">({count})</span>}
              </button>
            );
          })}
        </div>

        {/* Search */}
        <div className="relative ml-auto">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
          <input
            type="text"
            placeholder="Buscar por chave ou nome..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
            className="h-8 w-56 rounded-button border border-border-default bg-surface-primary pl-8 pr-3 text-sm text-content-primary placeholder:text-content-tertiary focus:border-brand-primary focus:outline-none"
            aria-label="Buscar projetos"
          />
        </div>

        {/* Sort dropdown */}
        <select
          value={sortBy}
          onChange={(e) => {
            setSortBy(e.target.value as JiraProjectCatalogQuery['sortBy']);
            setOffset(0);
          }}
          className="h-8 rounded-button border border-border-default bg-surface-primary px-2 text-xs text-content-primary"
          aria-label="Ordenar por"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Bulk actions bar */}
      {hasSelected && (
        <div className="mb-3 flex items-center gap-2 rounded-card border border-brand-primary bg-brand-light px-4 py-2">
          <span className="text-sm font-medium text-content-primary">
            {selectedKeys.size} selecionados
          </span>
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={() =>
                bulkAction.mutate({
                  action: 'activate',
                  projectKeys: Array.from(selectedKeys),
                })
              }
              disabled={bulkAction.isPending}
              className="rounded-button bg-status-success px-3 py-1 text-xs font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
            >
              Ativar
            </button>
            <button
              type="button"
              onClick={() =>
                bulkAction.mutate({
                  action: 'pause',
                  projectKeys: Array.from(selectedKeys),
                })
              }
              disabled={bulkAction.isPending}
              className="rounded-button bg-status-warning px-3 py-1 text-xs font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
            >
              Pausar
            </button>
            <button
              type="button"
              onClick={() =>
                bulkAction.mutate({
                  action: 'block',
                  projectKeys: Array.from(selectedKeys),
                })
              }
              disabled={bulkAction.isPending}
              className="rounded-button bg-status-danger px-3 py-1 text-xs font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
            >
              Bloquear
            </button>
          </div>
        </div>
      )}

      {/* Table (desktop) */}
      {isLoading ? (
        <TableSkeleton />
      ) : !data || data.items.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-sm text-content-secondary">
            Nenhum projeto descoberto ainda. Clique em &ldquo;Descobrir agora&rdquo; para buscar.
          </p>
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border-default text-xs font-medium uppercase text-content-secondary">
                  <th className="w-8 py-2 pr-2">
                    <input
                      type="checkbox"
                      checked={selectedKeys.size === data.items.length && data.items.length > 0}
                      onChange={toggleSelectAll}
                      className="rounded"
                      aria-label="Selecionar todos"
                    />
                  </th>
                  <SortableHeader
                    label="Key"
                    col="project_key"
                    activeCol={sortBy}
                    dir={sortDir}
                    onSort={toggleSort}
                  />
                  <th className="py-2 px-2">Nome</th>
                  <th className="py-2 px-2">Status</th>
                  <SortableHeader
                    label="Issues"
                    col="issue_count"
                    activeCol={sortBy}
                    dir={sortDir}
                    onSort={toggleSort}
                  />
                  <SortableHeader
                    label="PRs ref."
                    col="pr_reference_count"
                    activeCol={sortBy}
                    dir={sortDir}
                    onSort={toggleSort}
                  />
                  <SortableHeader
                    label="Ultima sync"
                    col="last_sync_at"
                    activeCol={sortBy}
                    dir={sortDir}
                    onSort={toggleSort}
                  />
                  <th className="w-12 py-2 px-2">
                    <span className="sr-only">Acoes</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle">
                {data.items.map((project) => (
                  <ProjectRow
                    key={project.projectKey}
                    project={project}
                    selected={selectedKeys.has(project.projectKey)}
                    onToggleSelect={toggleSelect}
                    onViewDetail={setDetailKey}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card list */}
          <div className="space-y-3 md:hidden">
            {data.items.map((project) => (
              <ProjectCard
                key={project.projectKey}
                project={project}
                selected={selectedKeys.has(project.projectKey)}
                onToggleSelect={toggleSelect}
                onViewDetail={setDetailKey}
              />
            ))}
          </div>
        </>
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

      {/* Side panel */}
      {detailKey && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-30 bg-black/20"
            onClick={() => setDetailKey(null)}
            aria-hidden="true"
          />
          <ProjectDetailPanel projectKey={detailKey} onClose={() => setDetailKey(null)} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function SortableHeader({
  label,
  col,
  activeCol,
  dir,
  onSort,
}: {
  label: string;
  col: NonNullable<JiraProjectCatalogQuery['sortBy']>;
  activeCol: JiraProjectCatalogQuery['sortBy'];
  dir: JiraProjectCatalogQuery['sortDir'];
  onSort: (col: NonNullable<JiraProjectCatalogQuery['sortBy']>) => void;
}) {
  const isActive = activeCol === col;
  return (
    <th className="py-2 px-2">
      <button
        type="button"
        onClick={() => onSort(col)}
        className="inline-flex items-center gap-1 text-xs font-medium uppercase text-content-secondary hover:text-content-primary"
        aria-label={`Ordenar por ${label}`}
      >
        {label}
        <ArrowUpDown
          className={`h-3 w-3 ${isActive ? 'text-brand-primary' : 'text-content-tertiary'}`}
        />
        {isActive && <span className="sr-only">({dir === 'asc' ? 'crescente' : 'decrescente'})</span>}
      </button>
    </th>
  );
}

function ProjectRow({
  project,
  selected,
  onToggleSelect,
  onViewDetail,
}: {
  project: JiraProjectCatalogEntry;
  selected: boolean;
  onToggleSelect: (key: string) => void;
  onViewDetail: (key: string) => void;
}) {
  return (
    <tr className="group transition-colors hover:bg-surface-secondary">
      <td className="py-2.5 pr-2">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(project.projectKey)}
          className="rounded"
          aria-label={`Selecionar ${project.projectKey}`}
        />
      </td>
      <td className="py-2.5 px-2 font-mono text-xs font-semibold text-content-primary">
        <span className="inline-flex items-center gap-1">
          {project.projectKey}
          {project.metadata?.pii_flag && (
            <span className="group/pii relative" aria-label="Nome sensivel detectado - revisao manual necessaria">
              <ShieldAlert className="h-4 w-4 text-status-warning" aria-hidden="true" />
              <span
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1 -translate-x-1/2 whitespace-nowrap rounded bg-gray-900 px-2 py-1 text-xs font-normal text-white opacity-0 shadow-lg transition-opacity group-hover/pii:opacity-100"
              >
                Nome sens&#237;vel detectado &mdash; revis&#227;o manual necess&#225;ria
              </span>
            </span>
          )}
        </span>
      </td>
      <td className="py-2.5 px-2 text-sm text-content-primary">{project.name ?? '-'}</td>
      <td className="py-2.5 px-2">
        <StatusChip status={project.status} />
      </td>
      <td className="py-2.5 px-2 text-xs text-content-secondary tabular-nums">
        {project.issueCount.toLocaleString()}
      </td>
      <td className="py-2.5 px-2 text-xs text-content-secondary tabular-nums">
        {project.prReferenceCount.toLocaleString()}
      </td>
      <td className="py-2.5 px-2 text-xs text-content-secondary">
        {project.lastSyncAt ? new Date(project.lastSyncAt).toLocaleString() : 'Nunca'}
      </td>
      <td className="py-2.5 px-2">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onViewDetail(project.projectKey)}
            className="text-xs font-medium text-brand-primary opacity-0 transition-opacity hover:text-brand-primary-hover group-hover:opacity-100"
          >
            Detalhes
          </button>
          <ProjectRowActions projectKey={project.projectKey} status={project.status} />
        </div>
      </td>
    </tr>
  );
}

function ProjectCard({
  project,
  selected,
  onToggleSelect,
  onViewDetail,
}: {
  project: JiraProjectCatalogEntry;
  selected: boolean;
  onToggleSelect: (key: string) => void;
  onViewDetail: (key: string) => void;
}) {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
      <div className="mb-2 flex items-start justify-between">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(project.projectKey)}
            className="rounded"
            aria-label={`Selecionar ${project.projectKey}`}
          />
          <span className="inline-flex items-center gap-1 font-mono text-sm font-semibold text-content-primary">
            {project.projectKey}
            {project.metadata?.pii_flag && (
              <ShieldAlert
                className="h-4 w-4 text-status-warning"
                aria-label="Nome sensivel detectado - revisao manual necessaria"
              />
            )}
          </span>
          <StatusChip status={project.status} />
        </div>
        <ProjectRowActions projectKey={project.projectKey} status={project.status} />
      </div>
      {project.name && (
        <p className="mb-2 text-sm text-content-secondary">{project.name}</p>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-content-secondary">
        <span>Issues: {project.issueCount.toLocaleString()}</span>
        <span>PRs: {project.prReferenceCount.toLocaleString()}</span>
        <span>
          Sync: {project.lastSyncAt ? new Date(project.lastSyncAt).toLocaleString() : 'Nunca'}
        </span>
      </div>
      <button
        type="button"
        onClick={() => onViewDetail(project.projectKey)}
        className="mt-2 text-xs font-medium text-brand-primary hover:text-brand-primary-hover"
      >
        Ver detalhes
      </button>
    </div>
  );
}
