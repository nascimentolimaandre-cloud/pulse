import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';

export const leanRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/lean',
  component: LeanMetricsPage,
});

function LeanMetricsPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-content-primary">
        Lean & Flow
      </h1>

      <p className="mb-8 text-sm text-content-secondary">
        Cumulative Flow Diagram, Work In Progress, and Lead Time Distribution.
      </p>

      {/* WIP monitor placeholder */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-3">
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
      </div>

      {/* CFD chart placeholder */}
      <div className="mb-8 rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
        <div className="mb-4 h-5 w-56 animate-pulse rounded bg-surface-tertiary" />
        <div className="h-72 w-full animate-pulse rounded bg-surface-tertiary" />
      </div>

      {/* Scatterplot placeholder */}
      <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
        <div className="mb-4 h-5 w-48 animate-pulse rounded bg-surface-tertiary" />
        <div className="h-72 w-full animate-pulse rounded bg-surface-tertiary" />
      </div>
    </div>
  );
}
