/**
 * Flow Health section — redesign v2 (squad-first).
 *
 * Primary surface: a single card listing every squad with Flow metrics
 * (WIP, At-Risk, %Risco, Flow Efficiency, Intensidade). Click → side
 * drawer with the squad's KPIs + the list of in-progress items.
 *
 * States (all 6 from spec §6):
 *   loading, empty, healthy, degraded (at_risk > 0), error, partial (FE insufficient_data).
 *
 * The old tenant-level AgingWip / FlowEfficiency cards are retired; their
 * semantics now live per-squad in the drawer (see design decisions note in
 * the redesign PR).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, Info } from 'lucide-react';
import { useFlowHealth } from '@/hooks/useFlowHealth';
import { useFilterStore } from '@/stores/filterStore';
import type {
  AgingWipItem,
  FlowHealthResponse,
  SquadFlowSummary,
  SquadSortKey,
} from '@/types/flowHealth';
import { SquadListCard } from './SquadListCard';
import { SquadDetailDrawer } from './SquadDetailDrawer';
import { AtRiskSparkline, synthAtRiskSeries } from './AtRiskSparkline';
import { trackEvent } from '@/lib/analytics';

const PERIOD_LABEL: Record<string, string> = {
  '7d': 'últimos 7 dias',
  '30d': 'últimos 30 dias',
  '60d': 'últimos 60 dias',
  '90d': 'últimos 90 dias',
  '120d': 'últimos 120 dias',
};

export function FlowHealthSection() {
  const { period } = useFilterStore();
  const q = useFlowHealth();

  const [selectedSquad, setSelectedSquad] = useState<SquadFlowSummary | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [atRiskOnly, setAtRiskOnly] = useState(false);
  // Remember the trigger element so we can return focus on close (WCAG 2.4.3).
  const lastTriggerRef = useRef<HTMLElement | null>(null);

  const data: FlowHealthResponse | undefined = q.data;

  // Totals (tenant-wide) — used for the top callout + disclaimer.
  const totals = useMemo(() => {
    if (!data) return { wip: 0, atRisk: 0, squads: 0 };
    return {
      wip: data.squads.reduce((acc, s) => acc + s.wip_count, 0),
      atRisk: data.squads.reduce((acc, s) => acc + s.at_risk_count, 0),
      squads: data.squads.length,
    };
  }, [data]);

  // Fire `flow_health_viewed` once per successful load.
  const lastEventKey = useRef<string | null>(null);
  useEffect(() => {
    if (!data) return;
    const key = `${data.squad_key ?? 'tenant'}:${data.period}:${totals.wip}:${totals.atRisk}`;
    if (lastEventKey.current === key) return;
    lastEventKey.current = key;
    trackEvent('flow_health_viewed', {
      squad_count: totals.squads,
      total_wip: totals.wip,
      total_at_risk: totals.atRisk,
      period: data.period,
    });
  }, [data, totals.squads, totals.wip, totals.atRisk]);

  const handleSquadClick = (squad: SquadFlowSummary) => {
    lastTriggerRef.current = document.activeElement as HTMLElement | null;
    setSelectedSquad(squad);
    setDrawerOpen(true);
    trackEvent('squad_card_clicked', {
      squad_key: squad.squad_key,
      at_risk_count: squad.at_risk_count,
      risk_pct: squad.risk_pct,
    });
    trackEvent('squad_drawer_opened', {
      squad_key: squad.squad_key,
      items_count: squad.wip_count,
    });
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    // Return focus to originating squad card.
    queueMicrotask(() => lastTriggerRef.current?.focus?.());
  };

  const handleItemClick = (item: AgingWipItem) => {
    trackEvent('squad_drawer_item_clicked', {
      issue_key: item.issue_key,
      age_days: item.age_days,
      is_at_risk: item.is_at_risk,
    });
  };

  const handleSortChange = (key: SquadSortKey) => {
    trackEvent('squad_list_sorted', { sort_by: key });
  };

  const handleSearch = (queryLength: number) => {
    // Never forward the query content — length only, PII-safe.
    trackEvent('squad_list_searched', { query_length: queryLength });
  };

  const handlePageChange = (page: number, totalPages: number) => {
    trackEvent('squad_list_paginated', { page, total_pages: totalPages });
  };

  const handleAtRiskToggle = () => {
    const next = !atRiskOnly;
    setAtRiskOnly(next);
    trackEvent('flow_health_at_risk_filter_toggled', { active: next });
  };

  const periodLabel = PERIOD_LABEL[period] ?? period;

  return (
    <section
      aria-labelledby="fh-section-title"
      className="mb-8 flex flex-col gap-3"
    >
      {/* Section header */}
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2
            id="fh-section-title"
            className="text-[11px] font-semibold uppercase tracking-wide text-content-secondary"
          >
            Flow Health
          </h2>
          <p className="mt-0.5 text-xs text-content-secondary">
            Saúde do fluxo Kanban · {periodLabel}
          </p>
        </div>
        {data?.flow_efficiency.formula_disclaimer && (
          <FeDisclaimerTooltip text={data.flow_efficiency.formula_disclaimer} />
        )}
      </header>

      {/* Body — error | loading | empty | content */}
      {q.isError ? (
        <FlowHealthError onRetry={() => q.refetch()} />
      ) : q.isLoading || !data ? (
        <FlowHealthSkeleton />
      ) : data.squads.length === 0 ? (
        <FlowHealthEmpty />
      ) : (
        <>
          {/* Global at-risk callout (degraded state) */}
          {totals.atRisk > 0 && (
            <AtRiskCallout
              atRiskTotal={totals.atRisk}
              atRiskOnly={atRiskOnly}
              onToggle={handleAtRiskToggle}
            />
          )}
          <SquadListCard
            squads={data.squads}
            atRiskOnly={atRiskOnly}
            onSquadClick={handleSquadClick}
            onSortChange={handleSortChange}
            onSearch={handleSearch}
            onPageChange={handlePageChange}
          />
        </>
      )}

      {/* Drawer */}
      {data && (
        <SquadDetailDrawer
          open={drawerOpen}
          squad={selectedSquad}
          allItems={data.aging_wip_items}
          // When backend narrowed the payload to one squad (squad_key filter),
          // aging_wip_items is already scoped.
          payloadScopedToSquad={Boolean(data.squad_key)}
          onClose={handleDrawerClose}
          onItemClick={handleItemClick}
        />
      )}
    </section>
  );
}

/* ── At-risk callout ── */

function AtRiskCallout({
  atRiskTotal,
  atRiskOnly,
  onToggle,
}: {
  atRiskTotal: number;
  atRiskOnly: boolean;
  onToggle: () => void;
}) {
  const sparkData = synthAtRiskSeries(atRiskTotal, 14);
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-card border border-status-danger/40 bg-status-dangerBg px-4 py-2.5 text-[13px] text-status-dangerText"
    >
      <AlertTriangle className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
      <span className="flex-1">
        <strong className="font-semibold tabular-nums">{atRiskTotal}</strong>{' '}
        {atRiskTotal === 1 ? 'item at-risk no total' : 'itens at-risk no total'}
      </span>
      <AtRiskSparkline data={sparkData} tone="danger" />
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={atRiskOnly}
        className="inline-flex h-7 items-center rounded-button border border-status-danger/40 bg-surface-primary px-2.5 text-[12px] font-medium text-status-dangerText hover:bg-status-dangerBg focus:outline-none focus-visible:ring-2 focus-visible:ring-status-danger focus-visible:ring-offset-1"
      >
        {atRiskOnly ? '✓ Filtrando só at-risk' : 'Filtrar só at-risk'}
      </button>
    </div>
  );
}

/* ── FE disclaimer in header (tooltip style) ── */

function FeDisclaimerTooltip({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        aria-label="Sobre Flow Efficiency"
        className="inline-flex items-center gap-1 rounded-button px-2 py-1 text-[11px] font-medium text-content-tertiary hover:bg-surface-tertiary hover:text-content-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-1"
      >
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
        Sobre Flow Efficiency
      </button>
      {open && (
        <div
          role="tooltip"
          className="absolute right-0 top-full z-10 mt-1 w-[320px] rounded-card border border-border-default bg-surface-primary p-3 text-[12px] leading-relaxed text-content-secondary shadow-elevated"
        >
          {text}
        </div>
      )}
    </div>
  );
}

/* ── States ── */

function FlowHealthSkeleton() {
  return (
    <div
      role="status"
      aria-label="Carregando Flow Health"
      className="flex animate-pulse flex-col gap-3 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card"
    >
      <div className="flex items-center justify-between">
        <div className="h-4 w-32 rounded bg-surface-tertiary" />
        <div className="h-8 w-48 rounded bg-surface-tertiary" />
      </div>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-[10px] border border-border-subtle bg-surface-secondary/40 p-3">
          <div className="h-4 w-40 rounded bg-surface-tertiary" />
          <div className="h-3 w-full rounded bg-surface-tertiary" />
          <div className="h-1.5 w-full rounded bg-surface-tertiary" />
        </div>
      ))}
    </div>
  );
}

function FlowHealthEmpty() {
  return (
    <div className="rounded-card border border-dashed border-border-default bg-surface-primary p-10 text-center">
      <h3 className="text-sm font-semibold text-content-primary">
        Nenhum squad com fluxo ativo detectado
      </h3>
      <p className="mx-auto mt-1 max-w-md text-xs text-content-secondary">
        Aumente o período ou verifique se os projetos Jira Kanban estão sincronizados.
      </p>
    </div>
  );
}

function FlowHealthError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-border-default bg-surface-primary p-8 text-center shadow-card">
      <AlertCircle className="h-8 w-8 text-status-danger" aria-hidden="true" />
      <div>
        <h3 className="text-sm font-semibold text-content-primary">
          Não foi possível carregar Flow Health
        </h3>
        <p className="mt-1 text-xs text-content-secondary">Tente novamente em instantes.</p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-button border border-border-default bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-primary hover:border-brand-primary hover:text-brand-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-1"
      >
        Tentar novamente
      </button>
    </div>
  );
}
