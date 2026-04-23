/**
 * Squad list card — primary view of Flow Health.
 *
 * Shows one row per squad with: friendly name, WIP, at_risk, %risk, flow
 * efficiency, intensity (throughput_30d). Client-side search + sort +
 * pagination (8/page). Click → opens SquadDetailDrawer.
 *
 * Anti-surveillance: renders only aggregate counts and the squad's human
 * name (already scrubbed of PII by backend, coming from jira_project_catalog).
 */
import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, Search } from 'lucide-react';
import type { SquadFlowSummary, SquadSortKey } from '@/types/flowHealth';
import { formatAge, formatPct } from './formatters';
import { riskTone } from './issueType';

interface SquadListCardProps {
  squads: SquadFlowSummary[];
  /** When true, hide squads whose at_risk_count is 0 (global toggle). */
  atRiskOnly: boolean;
  onSquadClick: (squad: SquadFlowSummary) => void;
  onSortChange?: (key: SquadSortKey) => void;
  onSearch?: (queryLength: number) => void;
  onPageChange?: (page: number, totalPages: number) => void;
}

const PAGE_SIZE = 8;

const SORT_OPTIONS: Array<{ v: SquadSortKey; label: string }> = [
  { v: 'at_risk', label: 'At-Risk (maior)' },
  { v: 'risk_pct', label: '% Risco (maior)' },
  { v: 'flow_efficiency', label: 'Flow Efficiency (pior)' },
  { v: 'wip', label: 'WIP (maior)' },
  { v: 'intensity', label: 'Intensidade (maior)' },
  { v: 'name', label: 'Nome (A–Z)' },
];

function compare(a: SquadFlowSummary, b: SquadFlowSummary, key: SquadSortKey): number {
  switch (key) {
    case 'at_risk':
      return b.at_risk_count - a.at_risk_count || b.wip_count - a.wip_count;
    case 'risk_pct':
      return b.risk_pct - a.risk_pct;
    case 'flow_efficiency': {
      // Worst (lowest) first; null (insufficient) → bottom.
      const av = a.flow_efficiency ?? Number.POSITIVE_INFINITY;
      const bv = b.flow_efficiency ?? Number.POSITIVE_INFINITY;
      return av - bv;
    }
    case 'wip':
      return b.wip_count - a.wip_count;
    case 'intensity':
      return b.intensity_throughput_30d - a.intensity_throughput_30d;
    case 'name':
      return a.squad_name.localeCompare(b.squad_name, 'pt-BR');
  }
}

export function SquadListCard({
  squads,
  atRiskOnly,
  onSquadClick,
  onSortChange,
  onSearch,
  onPageChange,
}: SquadListCardProps) {
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SquadSortKey>('at_risk');
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let rows = squads;
    if (atRiskOnly) rows = rows.filter((s) => s.at_risk_count > 0);
    if (q) {
      rows = rows.filter(
        (s) =>
          (s.squad_name ?? '').toLowerCase().includes(q) ||
          s.squad_key.toLowerCase().includes(q),
      );
    }
    return [...rows].sort((a, b) => compare(a, b, sortKey));
  }, [squads, search, sortKey, atRiskOnly]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const handleSort = (v: SquadSortKey) => {
    setSortKey(v);
    setPage(1);
    onSortChange?.(v);
  };

  const handleSearch = (v: string) => {
    setSearch(v);
    setPage(1);
    onSearch?.(v.trim().length);
  };

  const goTo = (next: number) => {
    const clamped = Math.max(1, Math.min(totalPages, next));
    if (clamped === safePage) return;
    setPage(clamped);
    onPageChange?.(clamped, totalPages);
  };

  return (
    <article
      className="flex flex-col gap-3 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card"
      aria-labelledby="fh-squads-title"
    >
      {/* Header — title + count + controls */}
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3
            id="fh-squads-title"
            className="text-[15px] font-semibold text-content-primary"
          >
            Squads
          </h3>
          <p className="mt-0.5 text-xs text-content-secondary">
            {squads.length} squad{squads.length === 1 ? '' : 's'} no tenant
            {filtered.length !== squads.length && (
              <> · {filtered.length} após filtros</>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary"
              aria-hidden="true"
            />
            <input
              type="search"
              value={search}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder="Buscar squad…"
              aria-label="Buscar squad por nome"
              className="h-8 w-[200px] rounded-button border border-border-default bg-surface-primary pl-8 pr-2.5 text-[13px] text-content-primary focus:border-brand-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-primary"
            />
          </label>
          <label className="flex items-center gap-1.5 text-[11px] text-content-secondary">
            <span>Ordenar:</span>
            <select
              value={sortKey}
              onChange={(e) => handleSort(e.target.value as SquadSortKey)}
              aria-label="Ordenar squads"
              className="h-8 rounded-button border border-border-default bg-surface-primary px-2 text-[13px] text-content-primary focus:border-brand-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-primary"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.v} value={o.v}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      {/* List */}
      {pageItems.length === 0 ? (
        <div className="py-10 text-center text-xs text-content-secondary">
          {search.trim() || atRiskOnly
            ? 'Nenhum squad corresponde aos filtros.'
            : 'Nenhum squad com fluxo ativo detectado.'}
        </div>
      ) : (
        <ul className="flex flex-col gap-2" role="list">
          {pageItems.map((squad) => (
            <SquadRow key={squad.squad_key} squad={squad} onClick={() => onSquadClick(squad)} />
          ))}
        </ul>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <footer className="flex items-center justify-between border-t border-border-subtle pt-3 text-xs text-content-secondary">
          <span aria-live="polite">
            Página <span className="font-mono tabular-nums">{safePage}</span> de{' '}
            <span className="font-mono tabular-nums">{totalPages}</span>
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => goTo(safePage - 1)}
              disabled={safePage <= 1}
              aria-label="Página anterior"
              className="inline-flex h-7 items-center gap-1 rounded-button border border-border-default px-2 text-[12px] text-content-primary hover:border-brand-primary hover:text-brand-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-default disabled:hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-1"
            >
              <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
              Anterior
            </button>
            <button
              type="button"
              onClick={() => goTo(safePage + 1)}
              disabled={safePage >= totalPages}
              aria-label="Próxima página"
              className="inline-flex h-7 items-center gap-1 rounded-button border border-border-default px-2 text-[12px] text-content-primary hover:border-brand-primary hover:text-brand-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-default disabled:hover:text-content-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-1"
            >
              Próxima
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </footer>
      )}
    </article>
  );
}

/* ── Row ── */

function SquadRow({
  squad,
  onClick,
}: {
  squad: SquadFlowSummary;
  onClick: () => void;
}) {
  const tone = riskTone(squad.risk_pct);
  const riskColor =
    tone === 'danger'
      ? 'text-status-danger'
      : tone === 'warning'
        ? 'text-status-warning'
        : 'text-status-success';
  const barColor =
    tone === 'danger'
      ? 'bg-status-danger'
      : tone === 'warning'
        ? 'bg-status-warning'
        : 'bg-status-success';
  const riskPctText = Math.round(squad.risk_pct * 100);
  const displayName = squad.squad_name || squad.squad_key;
  const feText = squad.flow_efficiency === null ? '—' : formatPct(squad.flow_efficiency);

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-label={`Abrir detalhes de ${displayName}: ${squad.wip_count} WIP, ${squad.at_risk_count} em risco, ${riskPctText}% de risco`}
        className="group flex w-full flex-col gap-2 rounded-[10px] border border-border-subtle bg-surface-secondary/40 p-3 text-left transition-all hover:border-border-default hover:bg-surface-secondary hover:shadow-card focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-1"
      >
        {/* Top row — name + risk % badge */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h4 className="truncate text-[14px] font-semibold text-content-primary">
              {displayName}
            </h4>
            <p className="mt-0.5 font-mono text-[11px] text-content-tertiary">
              {squad.squad_key}
            </p>
          </div>
          <div className="flex flex-shrink-0 items-baseline gap-1">
            <span
              className={`font-mono text-[18px] font-bold tabular-nums leading-none ${riskColor}`}
            >
              {riskPctText}%
            </span>
            <span className="text-[10px] font-medium uppercase tracking-wider text-content-tertiary">
              risco
            </span>
          </div>
        </div>

        {/* Inline metrics row */}
        <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-content-secondary">
          <MetricPair label="WIP" value={squad.wip_count.toString()} />
          <MetricPair
            label="At-Risk"
            value={squad.at_risk_count.toString()}
            emphasis={squad.at_risk_count > 0 ? 'danger' : undefined}
          />
          <MetricPair label="FE" value={feText} />
          <MetricPair
            label="Intensidade"
            value={`${squad.intensity_throughput_30d}`}
            suffix="itens/30d"
          />
          {squad.p85_age_days !== null && (
            <MetricPair label="Idade P85" value={formatAge(squad.p85_age_days)} />
          )}
        </dl>

        {/* Risk bar */}
        <div
          role="img"
          aria-label={`Barra de risco ${riskPctText}%`}
          className="h-1.5 w-full overflow-hidden rounded-full bg-surface-tertiary"
        >
          <div
            className={`h-full ${barColor} transition-all`}
            style={{ width: `${Math.max(2, Math.min(100, riskPctText))}%` }}
          />
        </div>
      </button>
    </li>
  );
}

function MetricPair({
  label,
  value,
  suffix,
  emphasis,
}: {
  label: string;
  value: string;
  suffix?: string;
  emphasis?: 'danger';
}) {
  // Use <div> (not <span>) so we are a valid direct child of <dl> per HTML5
  // spec. axe-core `definition-list` rule requires <dl> to contain only
  // <dt>/<dd> groups or <div> wrappers. `inline-flex` keeps the visual
  // baseline layout identical.
  return (
    <div className="inline-flex items-baseline gap-1">
      <dt className="text-[10px] font-medium uppercase tracking-wider text-content-tertiary">
        {label}
      </dt>
      <dd
        className={`font-mono text-[12px] font-medium tabular-nums ${
          emphasis === 'danger' ? 'text-status-danger' : 'text-content-primary'
        }`}
      >
        {value}
        {suffix && (
          <span className="ml-1 text-[10px] font-normal text-content-tertiary">{suffix}</span>
        )}
      </dd>
    </div>
  );
}
