import { useRouterState } from '@tanstack/react-router';
import { useFilterStore } from '@/stores/filterStore';
import { useHomeMetrics, usePipelineTeamsList } from '@/hooks/useMetrics';
import { TeamCombobox } from '@/components/dashboard/TeamCombobox';
import { PeriodSegmented } from '@/components/dashboard/PeriodSegmented';
import { DateRangeFilter } from '@/components/dashboard/DateRangeFilter';

// Routes where global filters are not meaningful. Pipeline Monitor is
// real-time pipeline status (no period concept), and Jira Settings is a
// catalog management page (no time window). We hide the filter bar on those
// routes rather than rendering disabled controls.
const FILTER_EXEMPT_ROUTES = ['/pipeline-monitor', '/settings/integrations', '/integrations'];

function isFilterExempt(pathname: string): boolean {
  return FILTER_EXEMPT_ROUTES.some((prefix) => pathname.startsWith(prefix));
}

export function TopBar() {
  const {
    teamId,
    period,
    startDate,
    endDate,
    setTeamId,
    setPeriod,
    setCustomRange,
    reset,
  } = useFilterStore();

  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const showFilters = !isFilterExempt(pathname);

  // Pipeline teams list — always fetched (same 60s stale time as elsewhere) so
  // the TopBar has the 27 squads ready without a waterfall from the page body.
  const teamsQ = usePipelineTeamsList();
  const teams = teamsQ.data ?? [];

  // Home metrics query — kept warm so we can pre-trigger the fetch in the
  // background when the user navigates around. Cheap because TanStack Query
  // dedupes by key.
  useHomeMetrics();

  return (
    <header className="flex min-h-14 items-center justify-between gap-4 border-b border-border-default bg-surface-primary px-page-padding py-2">
      {/* Left: Breadcrumb placeholder (populated by route context in future) */}
      <div className="min-w-0 flex-shrink truncate text-sm text-content-secondary">
        {/* Breadcrumb slot */}
      </div>

      {/* Right: Global Filters (hidden on exempt routes) */}
      {showFilters && (
        <div className="flex flex-wrap items-end justify-end gap-3">
          <TeamCombobox teams={teams} value={teamId} onChange={setTeamId} />
          <PeriodSegmented value={period} onChange={setPeriod} />
          {period === 'custom' && (
            <DateRangeFilter
              startDate={startDate}
              endDate={endDate}
              onSubmit={setCustomRange}
            />
          )}
          <button
            type="button"
            onClick={reset}
            className="h-9 rounded-button px-3 text-xs font-medium text-content-secondary hover:bg-surface-tertiary hover:text-content-primary focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1"
          >
            Limpar
          </button>
        </div>
      )}
    </header>
  );
}
