import { createRoute } from '@tanstack/react-router';
import { useMemo, useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { rootRoute } from '../__root';
import { useFilterStore } from '@/stores/filterStore';
import {
  useHomeMetrics,
  useMetricsByTeam,
  useMetricsByTeamEvolution,
  usePipelineTeamsList,
  useTeamDetail,
} from '@/hooks/useMetrics';
import { KpiGroup } from '@/components/dashboard/KpiGroup';
import { KpiCard, KpiCardSkeleton } from '@/components/dashboard/KpiCard';
import { FreshnessBanner } from '@/components/dashboard/FreshnessBanner';
import { TeamRankingSection } from '@/components/dashboard/TeamRankingSection';
import { MetricEvolutionGrid } from '@/components/dashboard/MetricEvolutionGrid';
import { TeamDetailDrawer } from '@/components/dashboard/TeamDetailDrawer';
import { FlowHealthSection } from '@/components/dashboard/FlowHealth';
import { formatDuration } from '@/lib/dashboard/formatDuration';
import type { DashboardMetric } from '@/stores/filterStore';

export const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
});

// Static tooltip copy for each KPI card. Centralized here so they survive
// component re-renders without recompiling. Coverage values are appended
// dynamically for the Lead Time (DORA) card. See FDD-DSH-083.
const TOOLTIP: Record<string, string> = {
  deployFreq:
    'Frequência de deploys em produção.\n' +
    'Fórmula: deployments_prod / período_em_dias\n' +
    'Dados: eng_deployments onde environment=production no período\n' +
    'DORA 2023: Elite ≥1/dia · High 1/sem–1/dia · Medium 1/mês–1/sem · Low <1/mês',
  changeFailure:
    '% de deploys em produção que resultaram em falha.\n' +
    'Fórmula: deploys_falhos / deploys_totais\n' +
    'Dados: eng_deployments com is_failure=true (Jenkins FAILURE/UNSTABLE em production)\n' +
    'DORA 2023: Elite ≤5% · High ≤10% · Medium ≤15% · Low >15%',
  timeToRestore:
    'Mediana de tempo entre falha em produção e o próximo deploy bem-sucedido.\n' +
    'Fórmula: mediana(next_success_at − failure_at) por (repo, environment=production)\n' +
    'Dados: eng_deployments — pareamento failure→success em janela de 7 dias\n' +
    'Filtros: descarta recoveries < 5min (re-trigger de teste flaky); n ≥ 5 incidentes\n' +
    'DORA 2023: Elite <1h · High <24h · Medium <1sem · Low ≥1sem (FDD-DSH-050)',
  cycleTimeP50:
    'Tempo do primeiro commit até o merge do PR — metade dos PRs são mais rápidos que isso.\n' +
    'Fórmula: mediana(merged_at − first_commit_at)\n' +
    'Dados: eng_pull_requests com is_merged=true no período\n' +
    'PULSE benchmark: <2h Elite · <24h High · <72h Medium',
  cycleTimeP85:
    'Tempo em que 85% dos PRs são concluídos — mede previsibilidade.\n' +
    'Fórmula: percentil 85 de (merged_at − first_commit_at)\n' +
    'Dados: mesmo conjunto do P50\n' +
    'Uso: quanto menor, mais confiável a entrega. Mais robusto que o P50 a auto-merges.',
  wip:
    'Itens Jira em progresso (não concluídos nem no backlog).\n' +
    'Fórmula: count(issues) com status_category ∈ {in_progress, in_review}\n' +
    'Dados: eng_issues no estado atual\n' +
    "Little's Law: WIP × Lead Time ≈ Throughput — use para validar consistência",
  throughput:
    'Total de PRs merged no período.\n' +
    'Fórmula: count(PRs) onde merged_at no período e is_merged=true\n' +
    'Dados: eng_pull_requests\n' +
    "Uso: tendência de entrega. Combine com Cycle Time (Little's Law).",
};

function buildLeadTimeTooltip(coverage: { covered: number; total: number; pct: number } | null): string {
  const base =
    'Tempo do primeiro commit até chegar em produção.\n' +
    'Fórmula: mediana(deployed_at − first_commit_at)\n' +
    'Dados: eng_pull_requests com deployed_at populado (link deploy↔PR)\n' +
    'DORA 2023: Elite <24h · High <1sem · Medium <1mês · Low ≥1mês';
  if (!coverage || coverage.total === 0) return base;
  const pctTxt = Math.round(coverage.pct * 100);
  return (
    base +
    `\nCobertura: ${coverage.covered} de ${coverage.total} PRs (${pctTxt}% têm deploy linkado)`
  );
}

function buildLeadTimeEmptyTooltip(coverage: { covered: number; total: number; pct: number } | null): string {
  const eligible = coverage?.covered ?? 0;
  return (
    'Lead Time DORA requer ao menos 5 PRs com deploy vinculado para um P50 confiável.\n' +
    `Squad tem ${eligible} PR(s) com deploy linkado no período.\n` +
    'Aumente o período (ex: 90d/120d) ou aguarde mais ingestão de deploys.'
  );
}

const PERIOD_LABEL: Record<string, string> = {
  '7d': 'últimos 7 dias',
  '30d': 'últimos 30 dias',
  '60d': 'últimos 60 dias',
  '90d': 'últimos 90 dias',
  '120d': 'últimos 120 dias',
};

/**
 * PULSE Dashboard — Diagnostic-first redesign.
 * See: pulse/docs/ux-specs/dashboard-impl-spec.md
 */
function HomePage() {
  // Filter state is now owned by the global TopBar. Home reads the values
  // to drive its own data hooks and reacts-only to them.
  const { teamId, period, startDate, endDate, activeMetric, setActiveMetric } =
    useFilterStore();

  const [drawerTeamId, setDrawerTeamId] = useState<string | null>(null);

  // ── Data hooks ──────────────────────────────────────────
  const homeMetricsQ = useHomeMetrics();
  const teamsQ = usePipelineTeamsList();
  const rankingQ = useMetricsByTeam(activeMetric);
  const evolutionQ = useMetricsByTeamEvolution(activeMetric);
  const drawerDetail = useTeamDetail(drawerTeamId);

  const teams = teamsQ.data ?? [];
  const isLoadingGlobal = homeMetricsQ.isLoading;
  const isLoadingTeams = teamsQ.isLoading;

  // Filter ranking/evolution when a specific team is selected
  const filteredRanking = useMemo(() => {
    if (teamId === 'default') return rankingQ.data;
    return rankingQ.data.filter((r) => r.teamId === teamId);
  }, [rankingQ.data, teamId]);

  const filteredEvolution = useMemo(() => {
    if (teamId === 'default') return evolutionQ.data;
    return evolutionQ.data.filter((s) => s.teamId === teamId);
  }, [evolutionQ.data, teamId]);

  // Count low performers per group (TODO: real API should provide this)
  const doraLowCount = useMemo(() => {
    if (!rankingQ.data) return 0;
    // Approximate: count low classifications on the current active DORA-aligned metric.
    // Real impl would aggregate across all 4 DORA metrics.
    if (activeMetric === 'cycleTime' || activeMetric === 'wip' || activeMetric === 'throughput') return 0;
    return rankingQ.data.filter((r) => r.classification === 'low').length;
  }, [rankingQ.data, activeMetric]);

  // ── Applied filters copy ────────────────────────────────
  const scopeLabel =
    teamId === 'default'
      ? `todas as ${teams.length || ''} squads`.trim()
      : teams.find((t) => t.id === teamId)?.name ?? 'squad';

  const periodLabel =
    period === 'custom'
      ? `${startDate ?? '—'} a ${endDate ?? '—'}`
      : PERIOD_LABEL[period] ?? period;

  // ── Error state ─────────────────────────────────────────
  if (homeMetricsQ.isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" aria-hidden="true" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">
          Não foi possível carregar o dashboard
        </h2>
        <p className="mb-4 max-w-md text-sm text-content-secondary">
          {homeMetricsQ.error instanceof Error
            ? homeMetricsQ.error.message
            : 'Erro inesperado.'}
        </p>
        <button
          type="button"
          onClick={() => homeMetricsQ.refetch()}
          className="rounded-button border border-border-default bg-surface-primary px-4 py-2 text-sm font-medium text-content-primary hover:border-brand-primary hover:text-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1"
        >
          Tentar novamente
        </button>
      </div>
    );
  }

  // ── Empty state (no squads at all) ──────────────────────
  const showEmpty = !isLoadingTeams && teams.length === 0;

  // ── Degraded state (derived) ───────────────────────────
  // TODO(pulse-data-engineer): freshness flag should come from /metrics/home
  // or a dedicated /pipeline/freshness endpoint. Derived here from team health.
  const degradedTeams = teams.filter((t) => t.health === 'degraded' || t.health === 'error').length;

  return (
    <div>
      <a
        href="#dashboard-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-button focus:bg-brand-primary focus:px-3 focus:py-1.5 focus:text-sm focus:text-white"
      >
        Pular para o conteúdo
      </a>

      {/* Page head */}
      <div className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight text-content-primary">
          PULSE Dashboard
        </h1>
        <p className="mt-1 max-w-[60ch] text-sm text-content-secondary">
          Visão de engenharia por time em DORA e Flow. Selecione squad e período para explorar.
        </p>
      </div>

      {/* Applied filters strip — filter controls moved to the global TopBar */}
      <div
        aria-live="polite"
        className="mb-6 inline-flex items-center rounded-button border border-dashed border-border-default bg-surface-primary px-3 py-1.5 text-xs text-content-secondary"
      >
        Exibindo <strong className="mx-1 text-content-primary">{scopeLabel}</strong> ·
        <strong className="ml-1 text-content-primary">{periodLabel}</strong>
      </div>

      {/* Freshness banner */}
      {degradedTeams > 0 && (
        <FreshnessBanner
          severity="degraded"
          message={`${degradedTeams} fonte(s) com atraso. Alguns gráficos podem estar parciais.`}
        />
      )}

      <main id="dashboard-main">
        {showEmpty ? (
          <EmptyDashboard />
        ) : (
          <>
            {/* KPI groups */}
            <div className="mb-8 grid grid-cols-1 gap-section-gap xl:grid-cols-2">
              <KpiGroup
                id="grp-dora"
                title="DORA Metrics"
                hint="Baseline DORA 2023"
                dotColor="dora"
                warningCount={doraLowCount > 0 ? { label: `squad${doraLowCount > 1 ? 's' : ''} em Low`, count: doraLowCount } : undefined}
              >
                {isLoadingGlobal || !homeMetricsQ.data ? (
                  <>
                    <KpiCardSkeleton />
                    <KpiCardSkeleton />
                    <KpiCardSkeleton />
                    <KpiCardSkeleton />
                  </>
                ) : (
                  <>
                    <KpiCard
                      label="Deploy Freq"
                      value={homeMetricsQ.data.deploymentFrequency.value}
                      unit={homeMetricsQ.data.deploymentFrequency.unit}
                      trend={homeMetricsQ.data.deploymentFrequency.trend}
                      classification={homeMetricsQ.data.deploymentFrequency.classification}
                      infoTooltip={TOOLTIP.deployFreq}
                    />
                    {(() => {
                      const ltStrict = homeMetricsQ.data.leadTimeStrict;
                      const ltInclusive = homeMetricsQ.data.leadTimeForChanges;
                      const strictFmt = formatDuration(ltStrict.value);
                      const inclusiveFmt =
                        ltInclusive && ltInclusive.value != null
                          ? formatDuration(ltInclusive.value)
                          : null;
                      return (
                        <KpiCard
                          label="Lead Time"
                          value={strictFmt.primary}
                          valueSecondary={strictFmt.secondary}
                          unit=""
                          trend={ltStrict.trend}
                          classification={ltStrict.classification}
                          coveragePct={homeMetricsQ.data.leadTimeCoverage?.pct ?? null}
                          extraNote={
                            inclusiveFmt ? `Inclusivo: ${inclusiveFmt.primary}` : null
                          }
                          infoTooltip={
                            ltStrict.value === null
                              ? buildLeadTimeEmptyTooltip(homeMetricsQ.data.leadTimeCoverage)
                              : buildLeadTimeTooltip(homeMetricsQ.data.leadTimeCoverage)
                          }
                          pendingLabel={ltStrict.value === null ? 'Sem dado' : undefined}
                        />
                      );
                    })()}
                    <KpiCard
                      label="Change Failure"
                      value={homeMetricsQ.data.changeFailureRate.value}
                      unit={homeMetricsQ.data.changeFailureRate.unit}
                      trend={homeMetricsQ.data.changeFailureRate.trend}
                      classification={homeMetricsQ.data.changeFailureRate.classification}
                      infoTooltip={TOOLTIP.changeFailure}
                    />
                    {(() => {
                      const ttr = homeMetricsQ.data.timeToRestore;
                      const fmt = formatDuration(ttr.value);
                      // FDD-DSH-050: render incident counts as a subline so users
                      // can judge the value's representativeness ("n=73 resolved · 3 open").
                      const resolved = ttr.incidentCount;
                      const open = ttr.openIncidentCount;
                      const noteParts: string[] = [];
                      if (typeof resolved === 'number' && resolved > 0) {
                        noteParts.push(`n=${resolved} resolvidos`);
                      }
                      if (typeof open === 'number' && open > 0) {
                        noteParts.push(`${open} em aberto`);
                      }
                      const extraNote = noteParts.length > 0 ? noteParts.join(' · ') : null;
                      const isEmpty = ttr.value === null;
                      return (
                        <KpiCard
                          label="Time to Restore"
                          value={fmt.primary}
                          valueSecondary={fmt.secondary}
                          unit=""
                          trend={ttr.trend}
                          classification={ttr.classification}
                          infoTooltip={TOOLTIP.timeToRestore}
                          extraNote={extraNote}
                          // Render "Sem dado" when below sample threshold (n<5 resolved
                          // or no incidents in window). The MTTR backend (FDD-DSH-050)
                          // shipped 2026-04-29; the only reason value=null now is
                          // genuinely insufficient data, not "feature pending".
                          pendingLabel={isEmpty ? 'Sem dado' : undefined}
                        />
                      );
                    })()}
                  </>
                )}
              </KpiGroup>

              <KpiGroup
                id="grp-flow"
                title="Flow & Management"
                hint="Little's Law · P50"
                dotColor="flow"
              >
                {isLoadingGlobal || !homeMetricsQ.data ? (
                  <>
                    <KpiCardSkeleton />
                    <KpiCardSkeleton />
                    <KpiCardSkeleton />
                    <KpiCardSkeleton />
                  </>
                ) : (
                  <>
                    {(() => {
                      const ct = homeMetricsQ.data.cycleTime;
                      const fmt = formatDuration(ct.value);
                      return (
                        <KpiCard
                          label="Cycle Time P50"
                          value={fmt.primary}
                          valueSecondary={fmt.secondary}
                          unit=""
                          trend={ct.trend}
                          classification={ct.classification}
                          infoTooltip={TOOLTIP.cycleTimeP50}
                        />
                      );
                    })()}
                    {(() => {
                      const ct85 = homeMetricsQ.data.cycleTimeP85;
                      const fmt = formatDuration(ct85.value);
                      return (
                        <KpiCard
                          label="Cycle Time P85"
                          value={fmt.primary}
                          valueSecondary={fmt.secondary}
                          unit=""
                          trend={ct85.trend}
                          classification={ct85.classification}
                          infoTooltip={TOOLTIP.cycleTimeP85}
                        />
                      );
                    })()}
                    <KpiCard
                      label="WIP"
                      value={homeMetricsQ.data.wipCount.value}
                      unit={homeMetricsQ.data.wipCount.unit}
                      trend={homeMetricsQ.data.wipCount.trend}
                      classification={homeMetricsQ.data.wipCount.classification}
                      infoTooltip={TOOLTIP.wip}
                    />
                    <KpiCard
                      label="Throughput"
                      value={homeMetricsQ.data.throughput.value}
                      unit={homeMetricsQ.data.throughput.unit}
                      trend={homeMetricsQ.data.throughput.trend}
                      classification={homeMetricsQ.data.throughput.classification}
                      infoTooltip={TOOLTIP.throughput}
                    />
                  </>
                )}
              </KpiGroup>
            </div>

            {/* Flow Health section — Aging WIP + Flow Efficiency (FDD-KB-003/004) */}
            <FlowHealthSection />

            {/* Ranking section */}
            <TeamRankingSection
              activeMetric={activeMetric}
              onMetricChange={(m: DashboardMetric) => setActiveMetric(m)}
              rows={filteredRanking}
              isLoading={rankingQ.isLoading}
              onRowClick={(id) => setDrawerTeamId(id)}
            />

            {/* Evolution small multiples */}
            <MetricEvolutionGrid
              activeMetric={activeMetric}
              series={filteredEvolution}
              isLoading={evolutionQ.isLoading}
              onTileClick={(id) => setDrawerTeamId(id)}
            />
          </>
        )}
      </main>

      {/* Drawer */}
      <TeamDetailDrawer
        data={drawerDetail.data}
        activeMetric={activeMetric}
        open={drawerTeamId !== null && drawerDetail.data !== null}
        onClose={() => setDrawerTeamId(null)}
      />
    </div>
  );
}

function EmptyDashboard() {
  return (
    <div className="rounded-card border border-dashed border-border-default bg-surface-primary p-12 text-center">
      <h2 className="mb-2 text-lg font-semibold text-content-primary">
        Nenhuma squad cadastrada ainda
      </h2>
      <p className="mx-auto max-w-md text-sm text-content-secondary">
        Conecte as fontes de dados (DevLake, GitHub, Jenkins, Jira) para começar a visualizar as
        métricas de engenharia.
      </p>
    </div>
  );
}
