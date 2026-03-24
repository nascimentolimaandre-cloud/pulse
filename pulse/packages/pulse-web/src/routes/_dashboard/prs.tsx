import { useState, useMemo } from 'react';
import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../__root';
import { usePullRequests } from '@/hooks/useMetrics';
import { AlertCircle, ArrowUpDown, ExternalLink } from 'lucide-react';
import type { PullRequest } from '@/types/metrics';

export const prsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/prs',
  component: OpenPullRequestsPage,
});

type SortKey = 'title' | 'author' | 'repository' | 'ageDays' | 'size' | 'status';
type SortDir = 'asc' | 'desc';

const SIZE_ORDER: Record<string, number> = { XS: 1, S: 2, M: 3, L: 4, XL: 5 };

function ageColor(days: number): string {
  if (days > 7) return 'bg-red-50 text-status-danger';
  if (days >= 3) return 'bg-amber-50 text-status-warning';
  return 'bg-emerald-50 text-status-success';
}

function sizeColor(size: string): string {
  if (size === 'XL' || size === 'L') return 'text-status-danger';
  if (size === 'M') return 'text-status-warning';
  return 'text-status-success';
}

function TableSkeleton() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card">
      <div className="flex gap-4 border-b border-border-default p-card-padding">
        {[48, 24, 32, 20, 16].map((w, i) => (
          <div key={i} className={`h-4 w-${w} animate-pulse rounded bg-surface-tertiary`} />
        ))}
      </div>
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="flex gap-4 border-b border-border-subtle p-card-padding last:border-b-0">
          {[48, 24, 32, 20, 16].map((w, j) => (
            <div key={j} className={`h-4 w-${w} animate-pulse rounded bg-surface-tertiary`} />
          ))}
        </div>
      ))}
    </div>
  );
}

function OpenPullRequestsPage() {
  const { data, isLoading, isError, error } = usePullRequests();
  const [sortKey, setSortKey] = useState<SortKey>('ageDays');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const sorted = useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'title':
          cmp = a.title.localeCompare(b.title);
          break;
        case 'author':
          cmp = a.author.localeCompare(b.author);
          break;
        case 'repository':
          cmp = a.repository.localeCompare(b.repository);
          break;
        case 'ageDays':
          cmp = a.ageDays - b.ageDays;
          break;
        case 'size':
          cmp = (SIZE_ORDER[a.size] ?? 0) - (SIZE_ORDER[b.size] ?? 0);
          break;
        case 'status':
          cmp = a.status.localeCompare(b.status);
          break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load pull requests</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold text-content-primary">Open Pull Requests</h1>
      <p className="mb-8 text-sm text-content-secondary">
        Active pull requests across all monitored repositories. Sortable by age, size, and review status.
      </p>

      {isLoading ? (
        <TableSkeleton />
      ) : !data || data.length === 0 ? (
        <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
          <p className="py-12 text-center text-sm text-content-secondary">
            No open pull requests found for the selected filters.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border-default bg-surface-primary shadow-card">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border-default bg-surface-secondary">
                <SortHeader label="Title" sortKey="title" currentKey={sortKey} dir={sortDir} onSort={toggleSort} className="min-w-[280px]" />
                <SortHeader label="Author" sortKey="author" currentKey={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="Repository" sortKey="repository" currentKey={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="Age" sortKey="ageDays" currentKey={sortKey} dir={sortDir} onSort={toggleSort} />
                <SortHeader label="Size" sortKey="size" currentKey={sortKey} dir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3 font-medium text-content-secondary">Reviewers</th>
                <SortHeader label="Status" sortKey="status" currentKey={sortKey} dir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {sorted.map((pr) => (
                <tr key={pr.id} className="transition-colors hover:bg-surface-secondary">
                  <td className="max-w-[320px] truncate px-4 py-3 font-medium text-content-primary">
                    {pr.title}
                  </td>
                  <td className="px-4 py-3 text-content-secondary">{pr.author}</td>
                  <td className="px-4 py-3 text-content-secondary">{pr.repository}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-badge px-2 py-0.5 text-xs font-semibold ${ageColor(pr.ageDays)}`}>
                      {pr.ageDays}d
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold ${sizeColor(pr.size)}`}>
                      {pr.size}
                    </span>
                    <span className="ml-1 text-xs text-content-tertiary">
                      +{pr.linesAdded}/-{pr.linesDeleted}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {pr.reviewers.length === 0 ? (
                      <span className="text-xs text-content-tertiary">None</span>
                    ) : (
                      <span className="text-xs text-content-secondary">
                        {pr.reviewers.join(', ')}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={pr.status} />
                  </td>
                  <td className="px-4 py-3">
                    <a
                      href={pr.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-content-tertiary hover:text-brand-primary"
                      title="Open in browser"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SortHeader({
  label,
  sortKey: key,
  currentKey,
  dir,
  onSort,
  className = '',
}: {
  label: string;
  sortKey: SortKey;
  currentKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  className?: string;
}) {
  const isActive = currentKey === key;
  return (
    <th className={`px-4 py-3 ${className}`}>
      <button
        onClick={() => onSort(key)}
        className="flex items-center gap-1 font-medium text-content-secondary hover:text-content-primary"
      >
        {label}
        <ArrowUpDown className={`h-3.5 w-3.5 ${isActive ? 'text-brand-primary' : 'text-content-tertiary'}`} />
        {isActive && (
          <span className="text-xs text-brand-primary">{dir === 'asc' ? '\u2191' : '\u2193'}</span>
        )}
      </button>
    </th>
  );
}

function StatusBadge({ status }: { status: PullRequest['status'] }) {
  const styles: Record<string, string> = {
    open: 'bg-emerald-50 text-status-success',
    draft: 'bg-surface-tertiary text-content-tertiary',
    review_requested: 'bg-blue-50 text-status-info',
  };
  const labels: Record<string, string> = {
    open: 'Open',
    draft: 'Draft',
    review_requested: 'Review',
  };
  return (
    <span className={`inline-block rounded-badge px-2 py-0.5 text-xs font-semibold ${styles[status] ?? ''}`}>
      {labels[status] ?? status}
    </span>
  );
}
