import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCard, MetricCardSkeleton } from '@/components/charts/MetricCard';
import { useLeanMetrics } from '@/hooks/useMetrics';
import { AlertCircle, AlertTriangle } from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ScatterChart,
  Scatter,
  ZAxis,
} from 'recharts';

export const leanRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/lean',
  component: LeanMetricsPage,
});

const CFD_COLORS = {
  done: '#10B981',
  review: '#3B82F6',
  inProgress: '#6366F1',
  todo: '#F59E0B',
  backlog: '#9CA3AF',
};

function ChartSkeleton() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
      <div className="mb-4 h-5 w-56 animate-pulse rounded bg-surface-tertiary" />
      <div className="h-72 w-full animate-pulse rounded bg-surface-tertiary" />
    </div>
  );
}

function LeanMetricsPage() {
  const { data, isLoading, isError, error } = useLeanMetrics();

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load Lean metrics</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  const wipOverLimit = data ? data.wipCount > data.wipLimit : false;

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-content-primary">Lean &amp; Flow</h1>
      <p className="mb-8 text-sm text-content-secondary">
        Cumulative Flow Diagram, Work In Progress, and Lead Time Distribution.
      </p>

      {/* WIP + Lead Time cards */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-3">
        {isLoading || !data ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            {/* WIP Card with threshold */}
            <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-medium text-content-secondary">Work In Progress</h3>
                {wipOverLimit && (
                  <AlertTriangle className="h-4 w-4 text-status-warning" />
                )}
              </div>
              <div className="mb-3 flex items-baseline gap-1">
                <span className="text-3xl font-bold text-content-primary">{data.wipCount}</span>
                <span className="text-sm text-content-tertiary">/ {data.wipLimit} limit</span>
              </div>
              {/* Progress bar */}
              <div className="mb-2 h-2 w-full overflow-hidden rounded-badge bg-surface-tertiary">
                <div
                  className={`h-full rounded-badge transition-all ${wipOverLimit ? 'bg-status-warning' : 'bg-brand-primary'}`}
                  style={{ width: `${Math.min((data.wipCount / data.wipLimit) * 100, 100)}%` }}
                />
              </div>
              {wipOverLimit && (
                <p className="text-xs text-status-warning">
                  WIP exceeds limit by {data.wipCount - data.wipLimit} items
                </p>
              )}
              {data.wipAgingItems > 0 && (
                <p className="mt-1 text-xs text-content-secondary">
                  {data.wipAgingItems} aging item{data.wipAgingItems > 1 ? 's' : ''} (&gt; 14 days)
                </p>
              )}
            </div>

            <MetricCard
              label="Lead Time P50"
              value={data.leadTimeP50Days}
              unit="days"
              trend={{ direction: 'flat', percentage: 0, isPositive: true }}
              tooltipContent="50th percentile lead time"
            />
            <MetricCard
              label="Lead Time P85"
              value={data.leadTimeP85Days}
              unit="days"
              trend={{ direction: 'flat', percentage: 0, isPositive: true }}
              tooltipContent="85th percentile lead time"
            />
          </>
        )}
      </div>

      {/* Cumulative Flow Diagram */}
      {isLoading || !data ? (
        <div className="mb-8">
          <ChartSkeleton />
        </div>
      ) : data.cfdData.length === 0 ? (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">Cumulative Flow Diagram</h2>
          <p className="py-12 text-center text-sm text-content-secondary">No data available for this period.</p>
        </div>
      ) : (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">Cumulative Flow Diagram</h2>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data.cfdData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis dataKey="week" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-default)',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 12,
                }}
              />
              <Area type="monotone" dataKey="done" stackId="1" fill={CFD_COLORS.done} stroke={CFD_COLORS.done} fillOpacity={0.8} />
              <Area type="monotone" dataKey="review" stackId="1" fill={CFD_COLORS.review} stroke={CFD_COLORS.review} fillOpacity={0.8} />
              <Area type="monotone" dataKey="inProgress" stackId="1" fill={CFD_COLORS.inProgress} stroke={CFD_COLORS.inProgress} fillOpacity={0.8} />
              <Area type="monotone" dataKey="todo" stackId="1" fill={CFD_COLORS.todo} stroke={CFD_COLORS.todo} fillOpacity={0.8} />
              <Area type="monotone" dataKey="backlog" stackId="1" fill={CFD_COLORS.backlog} stroke={CFD_COLORS.backlog} fillOpacity={0.8} />
            </AreaChart>
          </ResponsiveContainer>
          <div className="mt-3 flex flex-wrap justify-center gap-4">
            {Object.entries(CFD_COLORS).map(([key, color]) => (
              <div key={key} className="flex items-center gap-1.5 text-xs text-content-secondary">
                <div className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
                <span className="capitalize">{key === 'inProgress' ? 'In Progress' : key}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Lead Time Distribution */}
      {isLoading || !data ? (
        <div className="mb-8">
          <ChartSkeleton />
        </div>
      ) : data.scatterplotData.length === 0 ? (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">Lead Time Scatterplot</h2>
          <p className="py-12 text-center text-sm text-content-secondary">No data available for this period.</p>
        </div>
      ) : (
        <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">Lead Time Scatterplot</h2>
          <ResponsiveContainer width="100%" height={300}>
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis
                dataKey="closedAt"
                name="Closed"
                tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }}
              />
              <YAxis
                dataKey="leadTimeDays"
                name="Lead Time"
                unit=" days"
                tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }}
              />
              <ZAxis range={[40, 40]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-default)',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 12,
                }}
                formatter={(value: number, name: string) => {
                  if (name === 'Lead Time') return [`${value} days`, name];
                  return [value, name];
                }}
              />
              <ReferenceLine
                y={data.leadTimeP50Days}
                stroke="#10B981"
                strokeDasharray="4 4"
                label={{ value: `P50: ${data.leadTimeP50Days}d`, fontSize: 11, fill: '#10B981' }}
              />
              <ReferenceLine
                y={data.leadTimeP85Days}
                stroke="#F59E0B"
                strokeDasharray="4 4"
                label={{ value: `P85: ${data.leadTimeP85Days}d`, fontSize: 11, fill: '#F59E0B' }}
              />
              <ReferenceLine
                y={data.leadTimeP95Days}
                stroke="#EF4444"
                strokeDasharray="4 4"
                label={{ value: `P95: ${data.leadTimeP95Days}d`, fontSize: 11, fill: '#EF4444' }}
              />
              <Scatter
                data={data.scatterplotData}
                fill="var(--chart-1)"
                fillOpacity={0.6}
              />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
