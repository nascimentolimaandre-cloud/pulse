import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';

export const throughputRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/throughput',
  component: ThroughputPage,
});

function ThroughputPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-content-primary">
        Throughput
      </h1>

      <p className="mb-8 text-sm text-content-secondary">
        Pull request volume, merge rate, and PR analytics (size, review time, reviewers).
      </p>

      {/* Chart placeholder */}
      <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
        <div className="mb-4 h-5 w-48 animate-pulse rounded bg-surface-tertiary" />
        <div className="h-64 w-full animate-pulse rounded bg-surface-tertiary" />
      </div>

      {/* PR analytics cards */}
      <div className="grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-4">
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
      </div>
    </div>
  );
}
