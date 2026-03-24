import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../../__root';
import { MetricCard, MetricCardSkeleton } from '@/components/charts/MetricCard';
import { useDoraMetrics } from '@/hooks/useMetrics';
import { AlertCircle } from 'lucide-react';
import type { DoraClassification } from '@/types/metrics';

export const doraRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/metrics/dora',
  component: DoraMetricsPage,
});

const CLASSIFICATION_STYLES: Record<DoraClassification, { bg: string; text: string; label: string }> = {
  elite: { bg: 'bg-emerald-50', text: 'text-dora-elite', label: 'Elite' },
  high: { bg: 'bg-blue-50', text: 'text-dora-high', label: 'High' },
  medium: { bg: 'bg-amber-50', text: 'text-dora-medium', label: 'Medium' },
  low: { bg: 'bg-red-50', text: 'text-dora-low', label: 'Low' },
};

function ClassificationBadge({
  classification,
  size = 'md',
}: {
  classification: DoraClassification;
  size?: 'sm' | 'md' | 'lg';
}) {
  const style = CLASSIFICATION_STYLES[classification];
  const sizeClass =
    size === 'lg'
      ? 'px-4 py-1.5 text-sm'
      : size === 'sm'
        ? 'px-2 py-0.5 text-xs'
        : 'px-3 py-1 text-xs';

  return (
    <span className={`inline-flex items-center rounded-badge font-semibold ${style.bg} ${style.text} ${sizeClass}`}>
      {style.label}
    </span>
  );
}

function DoraMetricsPage() {
  const { data, isLoading, isError, error } = useDoraMetrics();

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">Failed to load DORA metrics</h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-4">
        <h1 className="text-2xl font-semibold text-content-primary">DORA Metrics</h1>
        {data && <ClassificationBadge classification={data.overallClassification} size="lg" />}
      </div>

      <p className="mb-8 text-sm text-content-secondary">
        Deployment Frequency, Lead Time for Changes, Change Failure Rate, and Mean Time to Restore.
      </p>

      {/* Per-metric classification badges */}
      {data && (
        <div className="mb-6 flex flex-wrap items-center gap-3">
          {(
            [
              ['Deploy Freq', data.deploymentFrequency.classification],
              ['Lead Time', data.leadTimeForChanges.classification],
              ['Change Fail Rate', data.changeFailureRate.classification],
              ['MTTR', data.meanTimeToRestore.classification],
            ] as const
          ).map(([label, cls]) => (
            <div key={label} className="flex items-center gap-2">
              <span className="text-xs text-content-secondary">{label}:</span>
              <ClassificationBadge classification={cls} size="sm" />
            </div>
          ))}
        </div>
      )}

      {/* MetricCard grid */}
      <div className="grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-4">
        {isLoading || !data ? (
          <>
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
            <MetricCardSkeleton />
          </>
        ) : (
          <>
            <MetricCard
              label={data.deploymentFrequency.label}
              value={data.deploymentFrequency.value}
              unit={data.deploymentFrequency.unit}
              trend={data.deploymentFrequency.trend}
              sparklineData={data.deploymentFrequency.sparklineData}
              target={data.deploymentFrequency.target}
              tooltipContent="Number of deployments per day/week"
            />
            <MetricCard
              label={data.leadTimeForChanges.label}
              value={data.leadTimeForChanges.value}
              unit={data.leadTimeForChanges.unit}
              trend={data.leadTimeForChanges.trend}
              sparklineData={data.leadTimeForChanges.sparklineData}
              target={data.leadTimeForChanges.target}
              tooltipContent="Median time from commit to production"
            />
            <MetricCard
              label={data.changeFailureRate.label}
              value={data.changeFailureRate.value}
              unit={data.changeFailureRate.unit}
              trend={data.changeFailureRate.trend}
              sparklineData={data.changeFailureRate.sparklineData}
              target={data.changeFailureRate.target}
              tooltipContent="Percentage of deployments causing a failure"
            />
            <MetricCard
              label={data.meanTimeToRestore.label}
              value={data.meanTimeToRestore.value}
              unit={data.meanTimeToRestore.unit}
              trend={data.meanTimeToRestore.trend}
              sparklineData={data.meanTimeToRestore.sparklineData}
              target={data.meanTimeToRestore.target}
              tooltipContent="Median time to recover from failure"
            />
          </>
        )}
      </div>
    </div>
  );
}
