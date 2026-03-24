import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';

export const sprintsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/sprints',
  component: SprintsPage,
});

function SprintsPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-content-primary">
        Sprints
      </h1>

      <p className="mb-8 text-sm text-content-secondary">
        Sprint overview with commitment, completion rate, scope changes, and burndown.
      </p>

      {/* Sprint summary cards */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-4">
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
      </div>

      {/* Burndown chart placeholder */}
      <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
        <div className="mb-4 h-5 w-40 animate-pulse rounded bg-surface-tertiary" />
        <div className="h-64 w-full animate-pulse rounded bg-surface-tertiary" />
      </div>
    </div>
  );
}
