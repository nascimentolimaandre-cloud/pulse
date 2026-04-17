import { createRoute, Link } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';
import { useSprintMetrics, usePipelineTeamsList } from '@/hooks/useMetrics';
import { useTenantCapabilities } from '@/hooks/useTenantCapabilities';
import { useFilterStore } from '@/stores/filterStore';
import { AlertCircle, TrendingUp, TrendingDown, Minus, Workflow, ArrowRight } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
} from 'recharts';

export const sprintsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/sprints',
  component: SprintsRoute,
});

/**
 * Top-level route component. When the active squad has no sprints (or, with
 * "Todas as squads" selected, the whole tenant has none), renders a friendly
 * empty state instead of the sprint dashboard. We only hide AFTER capabilities
 * resolve — during loading we show the normal page to avoid flicker.
 *
 * FDD-DSH-091 Phase 2: the capability call is scoped per-squad. FID / PTURB
 * return has_sprints=true; the other 25 squads return false and see the
 * Kanban-redirect empty state instead.
 */
function SprintsRoute() {
  const teamId = useFilterStore((s) => s.teamId);
  const { data: teams } = usePipelineTeamsList();

  // The home filter stores either 'default' (all squads), a squad key, or a
  // team UUID. We only treat it as a squad key when it's not 'default' and
  // matches the shape a Jira project key takes (backend guards the rest).
  const squadKey = teamId !== 'default' ? teamId : undefined;
  const squadName = squadKey
    ? teams?.find((t) => t.id === teamId || t.squadKey.toLowerCase() === teamId.toLowerCase())?.name ?? squadKey.toUpperCase()
    : null;

  const { data: capabilities, isSuccess } = useTenantCapabilities(squadKey);

  if (isSuccess && capabilities && !capabilities.hasSprints) {
    return <SprintsEmptyState squadName={squadName} />;
  }
  return <SprintsPage />;
}

interface SprintsEmptyStateProps {
  /** Optional squad display name — drives the copy ('a squad X' vs tenant-wide). */
  squadName?: string | null;
}

function SprintsEmptyState({ squadName }: SprintsEmptyStateProps) {
  const isSquadSpecific = Boolean(squadName);
  const heading = isSquadSpecific
    ? `A squad ${squadName} trabalha com fluxo contínuo`
    : 'Sua organização trabalha com fluxo contínuo';
  const subline = isSquadSpecific
    ? 'Esta squad não possui sprints ativos no Jira. Para acompanhá-la, use as métricas Kanban.'
    : 'As métricas de sprint aparecem automaticamente quando o PULSE detectar sprints ativos no seu Jira — mínimo de 3 nos últimos 6 meses.';

  return (
    <div
      className="flex min-h-[60vh] items-center justify-center"
      role="region"
      aria-labelledby="sprints-empty-heading"
    >
      <div className="max-w-xl rounded-card border border-border-default bg-surface-primary p-8 text-center shadow-card">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-brand-light">
          <Workflow className="h-6 w-6 text-brand-primary" aria-hidden="true" />
        </div>
        <h1 id="sprints-empty-heading" className="mb-2 text-xl font-semibold text-content-primary">
          {heading}
        </h1>
        <p className="mb-2 text-sm text-content-secondary">{subline}</p>
        <p className="mb-6 text-sm text-content-secondary">
          Para times Kanban, recomendamos acompanhar <strong>Lead Time</strong>,{' '}
          <strong>Throughput</strong> e <strong>WIP</strong> em Lean &amp; Flow.
        </p>
        <Link
          to="/metrics/lean"
          className="inline-flex items-center gap-2 rounded-button bg-brand-primary px-4 py-2 text-sm font-medium text-content-inverse transition-colors hover:bg-brand-primary-hover focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-2"
        >
          Ver Lean &amp; Flow
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}

const VELOCITY_ICONS = {
  improving: TrendingUp,
  stable: Minus,
  declining: TrendingDown,
};

const VELOCITY_STYLES = {
  improving: 'text-status-success bg-emerald-50',
  stable: 'text-content-tertiary bg-surface-tertiary',
  declining: 'text-status-danger bg-red-50',
};

function SprintsPage() {
  const { data, isLoading, isError, error } = useSprintMetrics();

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load Sprint data</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  const current = data?.current;
  const scopeCreep =
    current && current.metrics.committed > 0
      ? ((current.metrics.added / current.metrics.committed) * 100).toFixed(0)
      : '0';

  const VelocityIcon = data ? VELOCITY_ICONS[data.velocityTrend] : Minus;
  const velocityStyle = data ? VELOCITY_STYLES[data.velocityTrend] : '';

  return (
    <div>
      <div className="mb-2 flex items-center gap-4">
        <h1 className="text-2xl font-semibold text-content-primary">Sprints</h1>
        {data && (
          <span className={`inline-flex items-center gap-1 rounded-badge px-3 py-1 text-xs font-semibold ${velocityStyle}`}>
            <VelocityIcon className="h-3.5 w-3.5" />
            Velocity {data.velocityTrend}
          </span>
        )}
      </div>
      <p className="mb-8 text-sm text-content-secondary">
        Sprint overview with commitment, completion rate, scope changes, and burndown.
      </p>

      {/* Sprint summary cards */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-5">
        {isLoading || !data || !current ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            <SprintStatCard label="Committed" value={current.metrics.committed} color="text-content-primary" />
            <SprintStatCard label="Added (Scope Creep)" value={current.metrics.added} subtext={`${scopeCreep}%`} color="text-status-warning" />
            <SprintStatCard label="Completed" value={current.metrics.completed} color="text-status-success" />
            <SprintStatCard label="Carry Over" value={current.metrics.carryOver} color="text-status-danger" />
            <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
              <h3 className="mb-1 text-sm font-medium text-content-secondary">Completion Rate</h3>
              <span className="text-3xl font-bold text-content-primary">
                {current.metrics.completionRate}
              </span>
              <span className="ml-1 text-sm text-content-tertiary">%</span>
              {/* Progress bar */}
              <div className="mt-3 h-2 w-full overflow-hidden rounded-badge bg-surface-tertiary">
                <div
                  className="h-full rounded-badge bg-status-success transition-all"
                  style={{ width: `${Math.min(current.metrics.completionRate, 100)}%` }}
                />
              </div>
            </div>
          </>
        )}
      </div>

      {/* Burndown chart */}
      {isLoading || !data || !current ? (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <div className="mb-4 h-5 w-40 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-64 w-full animate-pulse rounded bg-surface-tertiary" />
        </div>
      ) : current.burndownData.length === 0 ? (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">
            Burndown: {current.name}
          </h2>
          <p className="py-12 text-center text-sm text-content-secondary">No burndown data available.</p>
        </div>
      ) : (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">
            Burndown: {current.name}
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={current.burndownData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis dataKey="day" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-default)',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 12,
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="ideal"
                name="Ideal"
                stroke="var(--color-text-tertiary)"
                strokeDasharray="5 5"
                strokeWidth={1.5}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="actual"
                name="Actual"
                stroke="var(--chart-1)"
                strokeWidth={2}
                dot={{ r: 3, fill: 'var(--chart-1)' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Sprint Comparison */}
      {data && data.comparison.length > 0 && (
        <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">Sprint Comparison</h2>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data.comparison}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis dataKey="sprintName" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-default)',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 12,
                }}
              />
              <Legend />
              <Bar dataKey="committed" name="Committed" fill="var(--chart-1)" radius={[4, 4, 0, 0]} barSize={24} />
              <Bar dataKey="completed" name="Completed" fill="var(--chart-5)" radius={[4, 4, 0, 0]} barSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function SprintStatCard({
  label,
  value,
  subtext,
  color,
}: {
  label: string;
  value: number;
  subtext?: string;
  color: string;
}) {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
      <h3 className="mb-1 text-sm font-medium text-content-secondary">{label}</h3>
      <div className="flex items-baseline gap-1">
        <span className={`text-3xl font-bold ${color}`}>{value}</span>
        <span className="text-sm text-content-tertiary">pts</span>
      </div>
      {subtext && (
        <p className="mt-1 text-xs text-content-secondary">{subtext}</p>
      )}
    </div>
  );
}
