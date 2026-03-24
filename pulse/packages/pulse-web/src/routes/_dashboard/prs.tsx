import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../__root';

export const prsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/prs',
  component: OpenPullRequestsPage,
});

function OpenPullRequestsPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-content-primary">
        Open Pull Requests
      </h1>

      <p className="mb-8 text-sm text-content-secondary">
        Active pull requests across all monitored repositories. Sortable by age, size, and
        review status.
      </p>

      {/* Table skeleton */}
      <div className="rounded-card border border-border-default bg-surface-primary shadow-card">
        {/* Table header skeleton */}
        <div className="flex gap-4 border-b border-border-default p-card-padding">
          <div className="h-4 w-48 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-24 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-32 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-20 animate-pulse rounded bg-surface-tertiary" />
          <div className="h-4 w-16 animate-pulse rounded bg-surface-tertiary" />
        </div>

        {/* Table rows skeleton */}
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-4 border-b border-border-subtle p-card-padding last:border-b-0"
          >
            <div className="h-4 w-48 animate-pulse rounded bg-surface-tertiary" />
            <div className="h-4 w-24 animate-pulse rounded bg-surface-tertiary" />
            <div className="h-4 w-32 animate-pulse rounded bg-surface-tertiary" />
            <div className="h-4 w-20 animate-pulse rounded bg-surface-tertiary" />
            <div className="h-4 w-16 animate-pulse rounded bg-surface-tertiary" />
          </div>
        ))}
      </div>
    </div>
  );
}
