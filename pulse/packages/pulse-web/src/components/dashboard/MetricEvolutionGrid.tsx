import { memo } from 'react';
import type { DashboardMetric } from '@/stores/filterStore';
import type { DoraClassification } from '@/types/metrics';
import type { TeamEvolutionSeries } from '@/lib/dashboard/mockDerive';
import { METRIC_META } from '@/lib/dashboard/classify';

interface MetricEvolutionGridProps {
  activeMetric: DashboardMetric;
  series: TeamEvolutionSeries[];
  isLoading: boolean;
  onTileClick: (teamId: string) => void;
}

const STROKE: Record<DoraClassification, string> = {
  elite: 'var(--color-dora-elite)',
  high: 'var(--color-dora-high)',
  medium: 'var(--color-dora-medium)',
  low: 'var(--color-dora-low)',
};

function MiniSpark({ points, classification }: { points: number[]; classification: DoraClassification }) {
  if (points.length < 2) return null;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const w = 140;
  const h = 36;
  const stepX = w / (points.length - 1);
  const d = points
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${(i * stepX).toFixed(1)} ${(h - ((v - min) / range) * h).toFixed(1)}`)
    .join(' ');
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path d={d} fill="none" stroke={STROKE[classification]} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

const Tile = memo(function Tile({
  s,
  unit,
  onClick,
}: {
  s: TeamEvolutionSeries;
  unit: string;
  onClick: (teamId: string) => void;
}) {
  const sign = s.deltaPct >= 0 ? '+' : '';
  const formattedCurrent = Number.isInteger(s.current) ? s.current.toString() : s.current.toFixed(1);
  return (
    <button
      type="button"
      onClick={() => onClick(s.teamId)}
      aria-label={`${s.name}: ${formattedCurrent} ${unit}, variação ${sign}${s.deltaPct.toFixed(1)}% em 12 semanas`}
      className="group flex flex-col gap-1.5 rounded-[8px] border border-border-subtle bg-surface-secondary p-2.5 text-left transition-all hover:-translate-y-0.5 hover:border-brand-primary focus:-translate-y-0.5 focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1 motion-reduce:hover:translate-y-0 motion-reduce:focus:translate-y-0"
    >
      <div className="flex items-center justify-between gap-1">
        <span className="truncate text-xs font-medium text-content-primary">{s.name}</span>
        <span className="text-[9px] font-semibold uppercase tracking-widest text-content-tertiary">
          {s.tribe}
        </span>
      </div>
      <div className="h-[36px]">
        <MiniSpark points={s.points} classification={s.classification} />
      </div>
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[13px] font-semibold tabular-nums text-content-primary">
          {formattedCurrent} <span className="text-[10px] text-content-tertiary">{unit}</span>
        </span>
        <span
          className={`text-[11px] font-medium tabular-nums ${
            s.deltaPct >= 0 ? 'text-status-success' : 'text-status-danger'
          }`}
        >
          {sign}
          {s.deltaPct.toFixed(1)}%
        </span>
      </div>
    </button>
  );
});

export function MetricEvolutionGrid({
  activeMetric,
  series,
  isLoading,
  onTileClick,
}: MetricEvolutionGridProps) {
  const meta = METRIC_META[activeMetric];

  // Group by tribe
  const grouped = series.reduce<Record<string, TeamEvolutionSeries[]>>((acc, s) => {
    const key = s.tribe || '—';
    if (!acc[key]) acc[key] = [];
    acc[key].push(s);
    return acc;
  }, {});
  const tribes = Object.keys(grouped).sort();

  return (
    <section aria-labelledby="evolution-title" className="mb-8">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="evolution-title" className="text-base font-semibold text-content-primary">
            Evolução por squad
          </h2>
          <p className="text-xs text-content-secondary">
            Tendência de 12 semanas · sincronizada com o ranking acima ({meta.label})
          </p>
        </div>
      </div>

      <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
        {isLoading ? (
          <EvolutionGridSkeleton />
        ) : series.length === 0 ? (
          <div className="rounded-button border border-dashed border-border-default p-10 text-center">
            <h3 className="text-sm font-semibold text-content-primary">Sem histórico disponível</h3>
            <p className="mt-1 text-xs text-content-secondary">
              Os dados de evolução aparecerão assim que o pipeline processar a janela completa.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {tribes.map((tribe) => (
              <div key={tribe}>
                <div className="mb-2 border-b border-border-subtle pb-1 text-[11px] font-semibold uppercase tracking-widest text-content-tertiary">
                  {tribe} · {grouped[tribe]!.length} squads
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
                  {grouped[tribe]!.map((s) => (
                    <Tile key={s.teamId} s={s} unit={meta.unit} onClick={onTileClick} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function EvolutionGridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 12 }).map((_, i) => (
        <div
          key={i}
          className="flex h-[108px] animate-pulse flex-col justify-between rounded-[8px] border border-border-subtle bg-surface-secondary p-2.5"
        >
          <div className="h-3 w-20 rounded bg-surface-tertiary" />
          <div className="h-[36px] rounded bg-surface-tertiary" />
          <div className="h-3 w-16 rounded bg-surface-tertiary" />
        </div>
      ))}
    </div>
  );
}
