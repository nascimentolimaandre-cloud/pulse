import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../__root';
import { Info } from 'lucide-react';

export const integrationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/integrations',
  component: IntegrationsPage,
});

interface ConnectionCardSkeletonProps {
  className?: string;
}

function ConnectionCardSkeleton({ className = '' }: ConnectionCardSkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card ${className}`}
    >
      <div className="mb-3 flex items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-surface-tertiary" />
        <div>
          <div className="mb-1 h-4 w-24 rounded bg-surface-tertiary" />
          <div className="h-3 w-16 rounded bg-surface-tertiary" />
        </div>
      </div>
      <div className="mb-2 h-3 w-36 rounded bg-surface-tertiary" />
      <div className="h-3 w-28 rounded bg-surface-tertiary" />
    </div>
  );
}

function IntegrationsPage() {
  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-content-primary">Integrations</h1>
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-status-success" />
          <span className="text-sm text-content-secondary">All Active</span>
        </div>
      </div>

      <p className="mb-8 text-sm text-content-secondary">
        Status of configured data source connections. Connections are managed via
        connections.yaml.
      </p>

      {/* Connection cards grid */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-3">
        <ConnectionCardSkeleton />
        <ConnectionCardSkeleton />
        <ConnectionCardSkeleton />
        <ConnectionCardSkeleton />
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 rounded-card border border-border-default bg-surface-secondary p-card-padding">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-status-info" />
        <div>
          <p className="text-sm font-medium text-content-primary">
            Connections are configured via connections.yaml
          </p>
          <p className="mt-1 text-sm text-content-secondary">
            See documentation for setup instructions. Integration management UI will be
            available in a future release.
          </p>
        </div>
      </div>
    </div>
  );
}
