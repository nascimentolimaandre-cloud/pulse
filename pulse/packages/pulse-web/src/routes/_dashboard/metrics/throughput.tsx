import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCard, MetricCardSkeleton } from '@/components/charts/MetricCard';
import { useThroughputMetrics } from '@/hooks/useMetrics';
import { AlertCircle } from 'lucide-react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart as RechartsBarChart,
} from 'recharts';

export const throughputRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/throughput',
  component: ThroughputPage,
});

function ThroughputPage() {
  const { data, isLoading, isError, error } = useThroughputMetrics();

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load Throughput data</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  // Compute moving average for trend line
  const chartData =
    data?.weeklyData.map((point, i, arr) => {
      const windowSize = Math.min(4, i + 1);
      const window = arr.slice(i - windowSize + 1, i + 1);
      const movingAvg = window.reduce((sum, p) => sum + p.merged, 0) / windowSize;
      return { ...point, movingAvg: parseFloat(movingAvg.toFixed(1)) };
    }) ?? [];

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-content-primary">Throughput</h1>
      <p className="mb-8 text-sm text-content-secondary">
        Pull request volume, merge rate, and PR analytics (size, review time, reviewers).
      </p>

      {/* PR Merged per week chart */}
      {isLoading || !data ? (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <div className="mb-4 h-5 w-48 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-64 w-full animate-pulse rounded bg-surface-tertiary" />
        </div>
      ) : data.weeklyData.length === 0 ? (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">PRs Merged per Week</h2>
          <p className="py-12 text-center text-sm text-content-secondary">No data available for this period.</p>
        </div>
      ) : (
        <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-base font-semibold text-content-primary">PRs Merged per Week</h2>
            <span className="text-sm text-content-secondary">
              Avg: {data.averageMergedPerWeek} / week
            </span>
          </div>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={chartData}>
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
              <Bar dataKey="merged" name="Merged" fill="var(--chart-1)" radius={[4, 4, 0, 0]} barSize={28} />
              <Bar dataKey="opened" name="Opened" fill="var(--chart-6)" radius={[4, 4, 0, 0]} barSize={28} opacity={0.4} />
              <Line
                type="monotone"
                dataKey="movingAvg"
                name="4-wk Avg"
                stroke="var(--chart-3)"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* PR Analytics cards */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-4">
        {isLoading || !data ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            <MetricCard
              label="Avg Merged / Week"
              value={data.averageMergedPerWeek}
              unit="PRs"
              trend={data.trend}
              sparklineData={data.sparklineData}
              tooltipContent="Average PRs merged per week"
            />
            <MetricCard
              label="Avg PR Size"
              value={data.analytics.avgPrSize}
              unit="lines"
              trend={{ direction: 'flat', percentage: 0, isPositive: true }}
              tooltipContent="Average lines changed per PR"
            />
            <MetricCard
              label="Avg First Review"
              value={data.analytics.avgFirstReviewTimeHours.toFixed(1)}
              unit="hours"
              trend={{ direction: 'flat', percentage: 0, isPositive: true }}
              tooltipContent="Average time to first review"
            />
            <MetricCard
              label="Avg Review Turnaround"
              value={data.analytics.avgReviewTurnaroundHours.toFixed(1)}
              unit="hours"
              trend={{ direction: 'flat', percentage: 0, isPositive: true }}
              tooltipContent="Average total review turnaround time"
            />
          </>
        )}
      </div>

      {/* PR Size Distribution */}
      {data && data.analytics.prSizeDistribution.length > 0 && (
        <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <h2 className="mb-4 text-base font-semibold text-content-primary">PR Size Distribution</h2>
          <ResponsiveContainer width="100%" height={220}>
            <RechartsBarChart data={data.analytics.prSizeDistribution}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
              <XAxis dataKey="size" tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <YAxis tick={{ fontSize: 12, fill: 'var(--color-text-secondary)' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-default)',
                  borderRadius: 'var(--radius-card)',
                  fontSize: 12,
                }}
              />
              <Bar dataKey="count" name="PRs" fill="var(--chart-2)" radius={[4, 4, 0, 0]} barSize={40} />
            </RechartsBarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
