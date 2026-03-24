import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';
import { useSprintMetrics } from '@/hooks/useMetrics';
import { AlertCircle, TrendingUp, TrendingDown, Minus } from 'lucide-react';
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
  component: SprintsPage,
});

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
