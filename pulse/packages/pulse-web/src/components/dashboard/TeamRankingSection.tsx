import type { DashboardMetric } from '@/stores/filterStore';
import type { DoraClassification } from '@/types/metrics';
import type { TeamRankingRow } from '@/lib/dashboard/mockDerive';
import { METRIC_META, classifLabel } from '@/lib/dashboard/classify';

interface TeamRankingSectionProps {
  activeMetric: DashboardMetric;
  onMetricChange: (m: DashboardMetric) => void;
  rows: TeamRankingRow[];
  isLoading: boolean;
  onRowClick: (teamId: string) => void;
}

const METRICS: DashboardMetric[] = [
  'deployFreq',
  'leadTime',
  'cfr',
  'cycleTime',
  'wip',
  'throughput',
];

const FILL_BG: Record<DoraClassification, string> = {
  elite: 'bg-dora-elite',
  high: 'bg-dora-high',
  medium: 'bg-dora-medium',
  low: 'bg-dora-low',
};

const BADGE_BG: Record<DoraClassification, string> = {
  elite: 'bg-dora-elite-bg text-emerald-800',
  high: 'bg-dora-high-bg text-blue-800',
  medium: 'bg-dora-medium-bg text-amber-800',
  low: 'bg-dora-low-bg text-red-800',
};

function formatValue(v: number): string {
  if (Number.isInteger(v)) return v.toString();
  return v.toFixed(1);
}

export function TeamRankingSection({
  activeMetric,
  onMetricChange,
  rows,
  isLoading,
  onRowClick,
}: TeamRankingSectionProps) {
  const meta = METRIC_META[activeMetric]!;

  const sorted = [...rows].sort((a, b) =>
    meta.sortDir === 'desc' ? b.value - a.value : a.value - b.value,
  );
  const max = sorted.length > 0 ? Math.max(...sorted.map((r) => r.value)) : 1;

  return (
    <section aria-labelledby="ranking-title" className="mb-8">
      <div className="mb-3">
        <h2 id="ranking-title" className="text-base font-semibold text-content-primary">
          Comparativo por squad
        </h2>
        <p className="text-xs text-content-secondary">
          Ordenado por desempenho. Clique em uma squad para abrir o detalhe lateral.
        </p>
      </div>

      {/* Metric tabs */}
      <div
        role="tablist"
        aria-label="Métrica do ranking"
        className="mb-3 flex gap-1 overflow-x-auto rounded-card border border-border-default bg-surface-primary p-1"
      >
        {METRICS.map((m) => {
          const active = m === activeMetric;
          return (
            <button
              key={m}
              role="tab"
              aria-selected={active}
              onClick={() => onMetricChange(m)}
              className={`h-[34px] min-w-[128px] flex-1 whitespace-nowrap rounded-[8px] px-3 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1 ${
                active
                  ? 'bg-brand-light text-brand-primary-hover'
                  : 'text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
              }`}
            >
              {METRIC_META[m]!.label}
            </button>
          );
        })}
      </div>

      {/* Ranking card */}
      <div
        role="tabpanel"
        aria-labelledby="ranking-title"
        className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card"
      >
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-[15px] font-semibold text-content-primary">{meta.title}</h3>
            <p className="text-xs text-content-secondary">{meta.sub}</p>
          </div>
          <div className="flex flex-wrap gap-3" aria-label="Legenda DORA">
            {(['elite', 'high', 'medium', 'low'] as const).map((c) => (
              <span key={c} className="inline-flex items-center gap-1.5 text-xs text-content-secondary">
                <span className={`h-2 w-2 rounded-full ${FILL_BG[c]}`} aria-hidden="true" />
                {classifLabel(c)}
              </span>
            ))}
          </div>
        </header>

        {isLoading ? (
          <TeamRankingSkeleton />
        ) : sorted.length === 0 ? (
          <EmptyRanking />
        ) : (
          <div
            role="list"
            aria-label="Ranking de squads"
            className="flex max-h-[620px] flex-col gap-0.5 overflow-y-auto pr-1"
          >
            {sorted.map((row, idx) => {
              const pct = max > 0 ? (row.value / max) * 100 : 0;
              return (
                <button
                  key={row.teamId}
                  role="listitem"
                  onClick={() => onRowClick(row.teamId)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      onRowClick(row.teamId);
                    }
                  }}
                  aria-label={`${row.name}: ${formatValue(row.value)} ${meta.unit}`}
                  className="grid w-full grid-cols-[28px_minmax(120px,180px)_1fr_64px_60px] items-center gap-3 rounded-md p-1.5 text-left transition-colors hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-brand-primary"
                >
                  <span className="text-right font-mono text-xs tabular-nums text-content-tertiary">
                    {idx + 1}
                  </span>
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate text-[13px] font-medium text-content-primary">
                      {row.name}
                    </span>
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-content-tertiary">
                      {row.tribe}
                      {row.status === 'backfilling' && (
                        <span className="ml-1.5 rounded-badge bg-status-idleBg px-1.5 py-0.5 text-[9px] font-medium normal-case tracking-normal text-status-idleText">
                          backfill
                        </span>
                      )}
                    </span>
                  </span>
                  <span
                    className="relative h-5 overflow-hidden rounded bg-surface-tertiary"
                    aria-hidden="true"
                  >
                    <span
                      className={`absolute inset-y-0 left-0 rounded transition-[width] duration-300 ease-out ${FILL_BG[row.classification]}`}
                      style={{ width: `${pct}%` }}
                    />
                  </span>
                  <span className="text-right font-mono text-xs tabular-nums text-content-primary">
                    {formatValue(row.value)}
                    <span className="ml-0.5 text-[10px] text-content-tertiary">{meta.unit}</span>
                  </span>
                  <span
                    className={`justify-self-end rounded-badge px-2 py-0.5 text-[10px] font-semibold ${BADGE_BG[row.classification]}`}
                  >
                    {classifLabel(row.classification)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function TeamRankingSkeleton() {
  return (
    <div className="flex flex-col gap-1">
      {Array.from({ length: 10 }).map((_, i) => (
        <div
          key={i}
          className="grid animate-pulse grid-cols-[28px_minmax(120px,180px)_1fr_64px_60px] items-center gap-3 p-1.5"
        >
          <div className="h-3 w-4 rounded bg-surface-tertiary" />
          <div className="flex flex-col gap-1">
            <div className="h-3 w-28 rounded bg-surface-tertiary" />
            <div className="h-2 w-10 rounded bg-surface-tertiary" />
          </div>
          <div className="h-5 rounded bg-surface-tertiary" />
          <div className="h-3 w-10 justify-self-end rounded bg-surface-tertiary" />
          <div className="h-4 w-12 rounded-badge bg-surface-tertiary" />
        </div>
      ))}
    </div>
  );
}

function EmptyRanking() {
  return (
    <div className="rounded-button border border-dashed border-border-default p-10 text-center">
      <h3 className="text-sm font-semibold text-content-primary">Sem squads para exibir</h3>
      <p className="mt-1 text-xs text-content-secondary">
        Nenhuma squad ativa no período selecionado.
      </p>
    </div>
  );
}
