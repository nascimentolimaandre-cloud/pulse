import { createRoute, Link } from '@tanstack/react-router';
import { rootRoute } from '../__root';
import { MetricCard, MetricCardSkeleton } from '@/components/charts/MetricCard';
import { useHomeMetrics } from '@/hooks/useMetrics';
import { AlertCircle, ExternalLink } from 'lucide-react';

export const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
});

function prAgeColor(ageDays: number): string {
  if (ageDays > 7) return 'text-status-danger';
  if (ageDays >= 3) return 'text-status-warning';
  return 'text-status-success';
}

function HomePage() {
  const { data, isLoading, isError, error } = useHomeMetrics();

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load dashboard</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-content-primary">
        PULSE Dashboard
      </h1>
      <p className="mb-8 text-sm text-content-secondary">
        Engineering intelligence at a glance. Select a team and period to explore metrics.
      </p>

      {/* Metric cards grid */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-3">
        {isLoading || !data ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            <MetricCard
              label={data.deploymentFrequency.label}
              value={data.deploymentFrequency.value}
              unit={data.deploymentFrequency.unit}
              trend={data.deploymentFrequency.trend}
              sparklineData={data.deploymentFrequency.sparklineData}
              classification={data.deploymentFrequency.classification}
              benchmarks={data.deploymentFrequency.benchmarks}
              tooltipContent="How often your team deploys to production"
            />
            <MetricCard
              label={data.leadTimeForChanges.label}
              value={data.leadTimeForChanges.value}
              unit={data.leadTimeForChanges.unit}
              trend={data.leadTimeForChanges.trend}
              sparklineData={data.leadTimeForChanges.sparklineData}
              classification={data.leadTimeForChanges.classification}
              benchmarks={data.leadTimeForChanges.benchmarks}
              tooltipContent="Time from commit to production deploy"
            />
            <MetricCard
              label={data.changeFailureRate.label}
              value={data.changeFailureRate.value}
              unit={data.changeFailureRate.unit}
              trend={data.changeFailureRate.trend}
              sparklineData={data.changeFailureRate.sparklineData}
              classification={data.changeFailureRate.classification}
              benchmarks={data.changeFailureRate.benchmarks}
              tooltipContent="Percentage of deployments causing failures"
            />
            <MetricCard
              label={data.cycleTime.label}
              value={data.cycleTime.value}
              unit={data.cycleTime.unit}
              trend={data.cycleTime.trend}
              sparklineData={data.cycleTime.sparklineData}
              classification={data.cycleTime.classification}
              benchmarks={data.cycleTime.benchmarks}
              tooltipContent="Median time from first commit to merge"
            />
            <MetricCard
              label={data.wipCount.label}
              value={data.wipCount.value}
              unit={data.wipCount.unit}
              trend={data.wipCount.trend}
              sparklineData={data.wipCount.sparklineData}
              classification={data.wipCount.classification}
              benchmarks={data.wipCount.benchmarks}
              tooltipContent="Items currently in progress"
            />
            <MetricCard
              label={data.throughput.label}
              value={data.throughput.value}
              unit={data.throughput.unit}
              trend={data.throughput.trend}
              sparklineData={data.throughput.sparklineData}
              classification={data.throughput.classification}
              benchmarks={data.throughput.benchmarks}
              tooltipContent="PRs merged per week"
            />
          </>
        )}
      </div>

      {/* PRs Needing Attention */}
      <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-content-primary">PRs Needing Attention</h2>
          <Link
            to="/prs"
            className="flex items-center gap-1 text-sm font-medium text-brand-primary hover:text-brand-primary-hover"
          >
            View all <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </div>

        {isLoading || !data ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="h-4 w-64 animate-pulse rounded bg-surface-tertiary" />
                <div className="h-4 w-20 animate-pulse rounded bg-surface-tertiary" />
                <div className="h-4 w-16 animate-pulse rounded bg-surface-tertiary" />
              </div>
            ))}
          </div>
        ) : data.prsNeedingAttention.length === 0 ? (
          <p className="py-6 text-center text-sm text-content-secondary">
            No open pull requests need attention right now.
          </p>
        ) : (
          <div className="divide-y divide-border-subtle">
            {data.prsNeedingAttention.slice(0, 5).map((pr) => (
              <div key={pr.id} className="flex items-center gap-4 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1">
                  <a
                    href={pr.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="truncate text-sm font-medium text-content-primary hover:text-brand-primary"
                  >
                    {pr.title}
                  </a>
                  <p className="text-xs text-content-secondary">
                    {pr.repository} &middot; {pr.author}
                  </p>
                </div>
                <span className={`shrink-0 text-sm font-medium ${prAgeColor(pr.ageDays)}`}>
                  {pr.ageDays}d
                </span>
                <span className="shrink-0 rounded-badge bg-surface-tertiary px-2 py-0.5 text-xs font-medium text-content-secondary">
                  {pr.size}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
