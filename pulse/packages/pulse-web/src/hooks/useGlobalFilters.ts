import { useCallback, useEffect } from 'react';
import { useSearch, useNavigate } from '@tanstack/react-router';
import { useFilterStore } from '@/stores/filterStore';
import type { PeriodOption } from '@/stores/filterStore';

interface SearchParams {
  teamId?: string;
  period?: string;
  startDate?: string;
  endDate?: string;
}

/**
 * Hook that syncs filterStore with URL search params.
 * Reads from URL on mount, writes to URL on store changes.
 */
export function useGlobalFilters() {
  const search = useSearch({ strict: false }) as SearchParams;
  const navigate = useNavigate();

  const { teamId, period, startDate, endDate, setTeamId, setPeriod, setCustomRange } =
    useFilterStore();

  // Sync URL params -> store on mount
  useEffect(() => {
    if (search.teamId && search.teamId !== teamId) {
      setTeamId(search.teamId);
    }
    if (search.period && search.period !== period) {
      const validPeriods: PeriodOption[] = ['7d', '30d', '60d', '90d', '120d', 'custom'];
      if (validPeriods.includes(search.period as PeriodOption)) {
        setPeriod(search.period as PeriodOption);
      }
    }
    if (search.startDate && search.endDate) {
      setCustomRange(search.startDate, search.endDate);
    }
    // Only run on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync store -> URL params on change
  const syncToUrl = useCallback(() => {
    const params: Record<string, string> = {
      teamId,
      period,
    };
    if (startDate) params.startDate = startDate;
    if (endDate) params.endDate = endDate;

    // Type assertion needed: TanStack Router's strict search param types
    // require route-level search schema definitions (added in Phase 3).
    // For now, we cast to allow URL sync without full route typing.
    void navigate({
      search: params as never,
      replace: true,
    });
  }, [teamId, period, startDate, endDate, navigate]);

  useEffect(() => {
    syncToUrl();
  }, [syncToUrl]);

  return {
    teamId,
    period,
    startDate,
    endDate,
    setTeamId,
    setPeriod,
    setCustomRange,
  };
}
