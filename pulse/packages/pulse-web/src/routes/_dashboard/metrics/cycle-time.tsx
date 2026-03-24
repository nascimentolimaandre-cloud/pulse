import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';

export const cycleTimeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/cycle-time',
  component: CycleTimePage,
});

function CycleTimePage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-content-primary">
        Cycle Time
      </h1>

      <p className="mb-8 text-sm text-content-secondary">
        Breakdown of time spent in each phase: Coding, Pickup, Review, Merge, and Deploy.
      </p>

      {/* Cycle time breakdown bar placeholder */}
      <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
        <div className="mb-4 h-5 w-48 animate-pulse rounded bg-surface-tertiary" />
        <div className="h-12 w-full animate-pulse rounded bg-surface-tertiary" />
      </div>

      {/* Per-phase cards */}
      <div className="grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-5">
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
      </div>
    </div>
  );
}
