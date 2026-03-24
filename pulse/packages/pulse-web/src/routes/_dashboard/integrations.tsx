import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../__root';
import { useIntegrations } from '@/hooks/useMetrics';
import { Info, AlertCircle, CheckCircle2, Loader2, XCircle, MinusCircle } from 'lucide-react';
import type { Integration } from '@/types/metrics';

export const integrationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/integrations',
  component: IntegrationsPage,
});

const TYPE_ICONS: Record<string, string> = {
  github: 'GH',
  gitlab: 'GL',
  jira: 'JR',
  azure_devops: 'AZ',
};

const TYPE_LABELS: Record<string, string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  jira: 'Jira',
  azure_devops: 'Azure DevOps',
};

type StatusStyle = { icon: React.ComponentType<{ className?: string }>; color: string; label: string };

const STATUS_CONFIG: Record<Integration['status'], StatusStyle> = {
  active: { icon: CheckCircle2, color: 'text-status-success', label: 'Active' },
  syncing: { icon: Loader2, color: 'text-status-info', label: 'Syncing' },
  error: { icon: XCircle, color: 'text-status-danger', label: 'Error' },
  inactive: { icon: MinusCircle, color: 'text-content-tertiary', label: 'Inactive' },
};

function ConnectionCardSkeleton() {
  return (
    <div className="animate-pulse rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
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

function ConnectionCard({ integration }: { integration: Integration }) {
  const statusCfg = STATUS_CONFIG[integration.status] ?? STATUS_CONFIG.inactive;
  const StatusIcon = statusCfg.icon;

  const lastSync = integration.lastSyncAt
    ? new Date(integration.lastSyncAt).toLocaleString()
    : 'Never';

  return (
    <div className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
      <div className="mb-3 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-light text-sm font-bold text-brand-primary">
          {TYPE_ICONS[integration.type] ?? '??'}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-content-primary">{integration.name}</h3>
          <p className="text-xs text-content-secondary">{TYPE_LABELS[integration.type] ?? integration.type}</p>
        </div>
      </div>

      <div className="mb-2 flex items-center gap-2">
        <StatusIcon className={`h-4 w-4 ${statusCfg.color} ${integration.status === 'syncing' ? 'animate-spin' : ''}`} />
        <span className={`text-sm font-medium ${statusCfg.color}`}>{statusCfg.label}</span>
      </div>

      <p className="mb-1 text-xs text-content-secondary">
        Last sync: {lastSync}
      </p>
      <p className="text-xs text-content-secondary">
        Repos monitored: {integration.reposMonitored}
      </p>

      {integration.errorMessage && (
        <p className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-status-danger">
          {integration.errorMessage}
        </p>
      )}
    </div>
  );
}

function IntegrationsPage() {
  const { data, isLoading, isError, error } = useIntegrations();

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load integrations</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  const activeCount = data?.filter((i) => i.status === 'active').length ?? 0;
  const totalCount = data?.length ?? 0;
  const allActive = totalCount > 0 && activeCount === totalCount;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-content-primary">Integrations</h1>
        {data && (
          <div className="flex items-center gap-2">
            <div className={`h-2 w-2 rounded-full ${allActive ? 'bg-status-success' : 'bg-status-warning'}`} />
            <span className="text-sm text-content-secondary">
              {allActive ? 'All Active' : `${activeCount}/${totalCount} Active`}
            </span>
          </div>
        )}
      </div>

      <p className="mb-8 text-sm text-content-secondary">
        Status of configured data source connections. Connections are managed via connections.yaml.
      </p>

      {/* Connection cards grid */}
      <div className="mb-8 grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-3">
        {isLoading ? (
          <>
            <ConnectionCardSkeleton />
            <ConnectionCardSkeleton />
            <ConnectionCardSkeleton />
            <ConnectionCardSkeleton />
          </>
        ) : !data || data.length === 0 ? (
          <div className="col-span-full py-12 text-center text-sm text-content-secondary">
            No integrations configured.
          </div>
        ) : (
          data.map((integration) => (
            <ConnectionCard key={integration.id} integration={integration} />
          ))
        )}
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-3 rounded-card border border-border-default bg-surface-secondary p-card-padding">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-status-info" />
        <div>
          <p className="text-sm font-medium text-content-primary">
            Connections are configured via connections.yaml
          </p>
          <p className="mt-1 text-sm text-content-secondary">
            See documentation for setup instructions. Integration management UI will be available in
            a future release.
          </p>
        </div>
      </div>
    </div>
  );
}
