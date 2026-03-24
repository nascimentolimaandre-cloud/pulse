import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';

export const doraRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/dora',
  component: DoraMetricsPage,
});

function DoraMetricsPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-content-primary">
        DORA Metrics
      </h1>

      <p className="mb-8 text-sm text-content-secondary">
        Deployment Frequency, Lead Time for Changes, Change Failure Rate, and Mean Time to
        Restore.
      </p>

      {/* DORA classification badges placeholder */}
      <div className="mb-8 flex items-center gap-4">
        <div className="h-8 w-24 animate-pulse rounded-badge bg-surface-tertiary" />
        <div className="h-8 w-24 animate-pulse rounded-badge bg-surface-tertiary" />
        <div className="h-8 w-24 animate-pulse rounded-badge bg-surface-tertiary" />
        <div className="h-8 w-24 animate-pulse rounded-badge bg-surface-tertiary" />
      </div>

      {/* MetricCard grid */}
      <div className="grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-4">
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
      </div>
    </div>
  );
}
