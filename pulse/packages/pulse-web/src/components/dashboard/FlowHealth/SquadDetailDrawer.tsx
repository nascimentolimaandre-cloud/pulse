/**
 * Squad detail drawer — non-modal side panel.
 *
 * Header: close + squad friendly name.
 * Body: 6-tile KPI grid (WIP, At-Risk, %Risco, FE, Intensidade, + idade P85)
 *       followed by a filterable list of in-progress items.
 * Items render title (never issue_key as primary), type pill, age, truncated
 * description and status — anti-surveillance: no assignee/author/reporter.
 *
 * A11y: focus trap + Esc close + return-focus-to-trigger managed by parent.
 * Virtualises item list with react-window when > VIRTUALIZE_THRESHOLD.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Search, X } from 'lucide-react';
import { List, type RowComponentProps } from 'react-window';
import type {
  AgingWipItem,
  IssueType,
  SquadFlowSummary,
  StatusCategory,
} from '@/types/flowHealth';
import { formatAge, formatPct } from './formatters';
import { issueTypeMeta, riskTone } from './issueType';

interface SquadDetailDrawerProps {
  open: boolean;
  squad: SquadFlowSummary | null;
  /** All aging WIP items from the Flow Health payload (unfiltered). */
  allItems: AgingWipItem[];
  /**
   * When the payload is scoped to a single squad (squad_key filter), this
   * prop is true and we render whatever is in allItems. Otherwise we filter
   * items by squad.squad_key client-side.
   */
  payloadScopedToSquad: boolean;
  onClose: () => void;
  onItemClick?: (item: AgingWipItem) => void;
}

const ROW_HEIGHT = 108; // title + description + meta row
const VIRTUALIZE_THRESHOLD = 100;

type StatusFilter = '' | StatusCategory;
type TypeFilter = '' | IssueType;

export function SquadDetailDrawer({
  open,
  squad,
  allItems,
  payloadScopedToSquad,
  onClose,
  onItemClick,
}: SquadDetailDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('');

  // Reset filters whenever the squad changes (re-opening the drawer).
  useEffect(() => {
    setSearch('');
    setTypeFilter('');
    setStatusFilter('');
  }, [squad?.squad_key]);

  // Items of this squad only (unless payload is already squad-scoped).
  const squadItems = useMemo(() => {
    if (!squad) return [];
    if (payloadScopedToSquad) return allItems;
    return allItems.filter((it) => it.squad_key === squad.squad_key);
  }, [allItems, squad, payloadScopedToSquad]);

  const availableTypes = useMemo(() => {
    const set = new Set<string>();
    for (const it of squadItems) if (it.issue_type) set.add(it.issue_type);
    return [...set].sort();
  }, [squadItems]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return squadItems
      .filter((it) => {
        if (statusFilter && it.status_category !== statusFilter) return false;
        if (typeFilter && (it.issue_type ?? '') !== typeFilter) return false;
        if (q) {
          const hay = `${it.title ?? ''} ${it.description ?? ''}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      })
      .sort((a, b) => {
        if (a.is_at_risk !== b.is_at_risk) return a.is_at_risk ? -1 : 1;
        return b.age_days - a.age_days;
      });
  }, [squadItems, search, typeFilter, statusFilter]);

  /* Focus trap + Esc */
  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'Tab' && drawerRef.current) {
        const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
          'button, [tabindex]:not([tabindex="-1"]), a[href], input, select, textarea',
        );
        if (focusable.length === 0) return;
        const first = focusable[0]!;
        const last = focusable[focusable.length - 1]!;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [open, onClose],
  );

  useEffect(() => {
    if (!open) return;
    document.addEventListener('keydown', handleKey);
    queueMicrotask(() => closeBtnRef.current?.focus());
    return () => document.removeEventListener('keydown', handleKey);
  }, [open, handleKey]);

  if (!open || !squad) return null;

  const useVirtual = filtered.length > VIRTUALIZE_THRESHOLD;
  const displayName = squad.squad_name || squad.squad_key;
  const tone = riskTone(squad.risk_pct);
  const riskColor =
    tone === 'danger'
      ? 'text-status-danger'
      : tone === 'warning'
        ? 'text-status-warning'
        : 'text-status-success';

  return (
    <aside
      ref={drawerRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby="squad-drawer-title"
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[560px] flex-col border-l border-border-default bg-surface-primary shadow-elevated"
    >
      {/* Head */}
      <header className="flex items-start justify-between gap-3 border-b border-border-default px-5 py-4">
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-content-tertiary">
            Squad
          </p>
          <h2
            id="squad-drawer-title"
            className="mt-0.5 truncate text-lg font-semibold text-content-primary"
            title={displayName}
          >
            {displayName}
          </h2>
          <p className="mt-0.5 font-mono text-[11px] text-content-tertiary">
            {squad.squad_key}
          </p>
        </div>
        <button
          ref={closeBtnRef}
          type="button"
          onClick={onClose}
          aria-label={`Fechar detalhes de ${displayName}`}
          className="inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-button text-content-secondary hover:bg-surface-tertiary hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-1"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </header>

      {/* KPI grid */}
      <div className="border-b border-border-default px-5 py-4">
        <dl className="grid grid-cols-3 gap-2 sm:gap-2.5">
          <KpiTile label="WIP" value={squad.wip_count.toString()} />
          <KpiTile
            label="At-Risk"
            value={squad.at_risk_count.toString()}
            emphasis={squad.at_risk_count > 0 ? 'danger' : undefined}
          />
          <KpiTile
            label="% Risco"
            value={`${Math.round(squad.risk_pct * 100)}%`}
            valueClassName={riskColor}
          />
          <KpiTile
            label="Flow Eff."
            value={squad.flow_efficiency === null ? '—' : formatPct(squad.flow_efficiency)}
            hint={
              squad.flow_efficiency === null
                ? `Amostra insuficiente (${squad.fe_sample_size})`
                : `${squad.fe_sample_size} concluídos`
            }
          />
          <KpiTile
            label="Intensidade"
            value={squad.intensity_throughput_30d.toString()}
            hint="itens/30d"
          />
          <KpiTile
            label="Idade P85"
            value={formatAge(squad.p85_age_days)}
            hint={
              squad.p50_age_days !== null ? `P50 ${formatAge(squad.p50_age_days)}` : undefined
            }
          />
        </dl>
      </div>

      {/* Items header + filters */}
      <div className="border-b border-border-default px-5 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-content-secondary">
            Itens em progresso
          </h3>
          <span className="font-mono text-[12px] tabular-nums text-content-tertiary">
            {filtered.length}
            {filtered.length !== squadItems.length && <> / {squadItems.length}</>}
          </span>
        </div>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto]">
          <label className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary"
              aria-hidden="true"
            />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar título ou descrição…"
              aria-label="Buscar item"
              className="h-8 w-full rounded-button border border-border-default bg-surface-primary pl-8 pr-2.5 text-[13px] text-content-primary focus:border-brand-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-primary"
            />
          </label>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
            aria-label="Filtrar por tipo"
            className="h-8 rounded-button border border-border-default bg-surface-primary px-2.5 text-[13px] text-content-primary focus:border-brand-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-primary"
          >
            <option value="">Todos tipos</option>
            {availableTypes.map((t) => (
              <option key={t} value={t}>
                {issueTypeMeta(t).label}
              </option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            aria-label="Filtrar por status"
            className="h-8 rounded-button border border-border-default bg-surface-primary px-2.5 text-[13px] text-content-primary focus:border-brand-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-primary"
          >
            <option value="">Todos status</option>
            <option value="in_progress">Em Progresso</option>
            <option value="in_review">Em Review</option>
          </select>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-hidden">
        {filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center p-6 text-center text-sm text-content-secondary">
            {squadItems.length === 0
              ? 'Sem itens em progresso para esta squad.'
              : 'Nenhum item corresponde aos filtros.'}
          </div>
        ) : useVirtual ? (
          <List
            rowCount={filtered.length}
            rowHeight={ROW_HEIGHT}
            rowComponent={VirtualRow}
            rowProps={{ items: filtered, onItemClick }}
            style={{ height: '100%', width: '100%' }}
          />
        ) : (
          <div className="h-full overflow-y-auto">
            {filtered.map((item) => (
              <ItemRow key={item.issue_key} item={item} onItemClick={onItemClick} />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

/* ── KPI tile ── */

function KpiTile({
  label,
  value,
  hint,
  emphasis,
  valueClassName,
}: {
  label: string;
  value: string;
  hint?: string;
  emphasis?: 'danger';
  valueClassName?: string;
}) {
  const baseValue =
    valueClassName ??
    (emphasis === 'danger' ? 'text-status-danger' : 'text-content-primary');
  return (
    <div className="rounded-[8px] border border-border-subtle bg-surface-secondary/50 px-2.5 py-2">
      <dt className="text-[10px] font-medium uppercase tracking-wider text-content-tertiary">
        {label}
      </dt>
      <dd className={`mt-1 font-mono text-[18px] font-bold tabular-nums leading-none ${baseValue}`}>
        {value}
      </dd>
      {hint && (
        <div className="mt-1 truncate text-[10px] text-content-tertiary" title={hint}>
          {hint}
        </div>
      )}
    </div>
  );
}

/* ── Item row ── */

interface RowData {
  items: AgingWipItem[];
  onItemClick?: (item: AgingWipItem) => void;
}

function VirtualRow({ index, items, onItemClick, style }: RowComponentProps<RowData>) {
  const item = items[index];
  if (!item) return null;
  return (
    <div style={style}>
      <ItemRow item={item} onItemClick={onItemClick} />
    </div>
  );
}

function ItemRow({
  item,
  onItemClick,
}: {
  item: AgingWipItem;
  onItemClick?: (item: AgingWipItem) => void;
}) {
  const clickable = Boolean(onItemClick);
  const type = issueTypeMeta(item.issue_type);
  const title = item.title?.trim() || 'Item sem título';

  return (
    <div
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? () => onItemClick!(item) : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onItemClick!(item);
              }
            }
          : undefined
      }
      style={{ minHeight: ROW_HEIGHT }}
      className={`flex flex-col gap-1.5 border-b border-border-subtle px-5 py-3 outline-none ${
        clickable
          ? 'cursor-pointer hover:bg-surface-secondary focus-visible:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-primary'
          : ''
      }`}
    >
      {/* Top: type + age */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`inline-flex flex-shrink-0 items-center rounded-badge px-1.5 py-0.5 text-[10px] font-medium ${type.className}`}
          >
            {type.label}
          </span>
          <span
            className={`inline-flex items-center gap-1 font-mono text-[12px] font-medium tabular-nums ${
              item.is_at_risk ? 'text-status-danger' : 'text-content-secondary'
            }`}
          >
            {item.is_at_risk && (
              <AlertTriangle className="h-3 w-3" aria-label="Em risco" />
            )}
            {formatAge(item.age_days)}
          </span>
        </div>
        <StatusPill category={item.status_category} label={item.status} />
      </div>

      {/* Title */}
      <h4
        className="line-clamp-2 text-[13px] font-semibold text-content-primary"
        title={title}
      >
        {title}
      </h4>

      {/* Description (truncated — backend cuts ~300 chars, we clamp 3 lines) */}
      {item.description && item.description.trim().length > 0 && (
        <p className="line-clamp-3 text-[12px] text-content-secondary">
          {item.description}
        </p>
      )}
    </div>
  );
}

function StatusPill({ category, label }: { category: StatusCategory; label: string }) {
  const dot = category === 'in_review' ? 'bg-chart-2' : 'bg-status-info';
  return (
    <span
      className="inline-flex flex-shrink-0 items-center gap-1.5 text-[11px] text-content-secondary"
      title={label}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
      <span className="truncate max-w-[140px]">{label}</span>
    </span>
  );
}
