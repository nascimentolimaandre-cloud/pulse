import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';
import { useCycleTimeMetrics } from '@/hooks/useMetrics';
import { AlertCircle } from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  CartesianGrid,
} from 'recharts';

export const cycleTimeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/cycle-time',
  component: CycleTimePage,
});

const PHASE_COLORS: Record<string, string> = {
  Coding: '#6366F1',
  Pickup: '#8B5CF6',
  Review: '#EC4899',
  Merge: '#F59E0B',
  Deploy: '#10B981',
};

function CycleTimePage() {
  const { data, isLoading, isError, error } = useCycleTimeMetrics();

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load Cycle Time data</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  const bottleneck = data?.phases.find((p) => p.isBottleneck);
  const totalHours = data?.totalMedianHours ?? 0;

  // Build stacked bar data: one row with phases as keys
  const stackedBarData = data
    ? [
        data.phases.reduce(
          (acc, phase) => {
            acc[phase.name] = phase.medianHours;
            return acc;
          },
          { name: 'Cycle Time' } as Record<string, string | number>,
        ),
      ]
    : [];

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-content-primary">Cycle Time</h1>
      <p className="mb-8 text-sm text-content-secondary">
        Breakdown of time spent in each phase: Coding, Pickup, Review, Merge, and Deploy.
      </p>

      {/* Total + bottleneck summary */}
      {data && (
        <div className="mb-6 flex flex-wrap items-center gap-4">
          <div className="rounded-card border border-border-default bg-surface-primary px-4 py-2 shadow-card">
            <span className="text-sm text-content-secondary">Total Median: </span>
            <span className="text-lg font-bold text-content-primary">
              {totalHours < 24
                ? `${totalHours.toFixed(1)}h`
                : `${(totalHours / 24).toFixed(1)}d`}
            </span>
          </div>
          {bottleneck && (
            <div className="rounded-card border border-status-warning bg-amber-50 px-4 py-2 shadow-card">
              <span className="text-sm text-status-warning">Bottleneck: </span>
              <span className="text-sm font-semibold text-status-warning">
                {bottleneck.name} ({bottleneck.medianHours.toFixed(1)}h)
              </span>
            </div>
          )}
        </div>
      )}

      {/* Stacked horizontal bar */}
      {isLoading || !data ? (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <div className="mb-4 h-5 w-48 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-16 w-full animate-pulse rounded bg-surface-tertiary" />
        </div>
      ) : (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">Phase Breakdown</h2>
          <ResponsiveContainer width="100%" height={60}>
            <BarChart data={stackedBarData} layout="vertical" barSize={32}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="name" hide />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-default)',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 12,
                }}
                formatter={(value: number, name: string) => [`${value.toFixed(1)}h`, name]}
              />
              {data.phases.map((phase) => (
                <Bar
                  key={phase.name}
                  dataKey={phase.name}
                  stackId="a"
                  fill={PHASE_COLORS[phase.name] || phase.color}
                  radius={0}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-3 flex flex-wrap justify-center gap-4">
            {data.phases.map((phase) => (
              <div key={phase.name} className="flex items-center gap-1.5 text-xs text-content-secondary">
                <div
                  className="h-2.5 w-2.5 rounded-sm"
                  style={{ backgroundColor: PHASE_COLORS[phase.name] || phase.color }}
                />
                <span>
                  {phase.name}: {phase.medianHours.toFixed(1)}h
                  {phase.isBottleneck ? ' (bottleneck)' : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-phase cards */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-5">
        {isLoading || !data
          ? Array.from({ length: 5 }).map((_, i) => <MetricCardSkeleton key={i} />)
          : data.phases.map((phase) => (
              <div
                key={phase.name}
                className={`rounded-card border bg-surface-primary p-card-padding shadow-card ${
                  phase.isBottleneck ? 'border-status-warning' : 'border-border-default'
                }`}
              >
                <div className="mb-1 flex items-center gap-2">
                  <div
                    className="h-2.5 w-2.5 rounded-sm"
                    style={{ backgroundColor: PHASE_COLORS[phase.name] || phase.color }}
                  />
                  <h3 className="text-sm font-medium text-content-secondary">{phase.name}</h3>
                </div>
                <span className="text-2xl font-bold text-content-primary">
                  {phase.medianHours.toFixed(1)}
                </span>
                <span className="ml-1 text-sm text-content-tertiary">hours</span>
                {totalHours > 0 && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {((phase.medianHours / totalHours) * 100).toFixed(0)}% of total
                  </p>
                )}
              </div>
            ))}
      </div>

      {/* Trend line chart */}
      {data && data.sparklineData.length > 1 && (
        <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">Weekly P50 Cycle Time Trend</h2>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart
              data={data.sparklineData.map((val, i) => ({ week: `W${i + 1}`, hours: val }))}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis dataKey="week" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} unit="h" />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-default)',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 12,
                }}
                formatter={(value: number) => [`${value.toFixed(1)}h`, 'P50 Cycle Time']}
              />
              <Line
                type="monotone"
                dataKey="hours"
                stroke="var(--chart-1)"
                strokeWidth={2}
                dot={{ r: 3, fill: 'var(--chart-1)' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
