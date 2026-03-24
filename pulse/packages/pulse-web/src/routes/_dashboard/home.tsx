import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../__root';
import { MetricCardSkeleton } from '@/components/charts/MetricCard';

export const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: HomePage,
});

function HomePage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-content-primary">
        PULSE Dashboard
      </h1>

      <p className="mb-8 text-sm text-content-secondary">
        Engineering intelligence at a glance. Select a team and period to explore metrics.
      </p>

      {/* MetricCard grid placeholder */}
      <div className="grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-4">
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
        <MetricCardSkeleton />
      </div>
    </div>
  );
}
