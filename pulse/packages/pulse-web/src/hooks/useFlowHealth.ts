import { useQuery } from '@tanstack/react-query';
import { useFilterStore } from '@/stores/filterStore';
import { fetchFlowHealth } from '@/lib/api/flowHealth';
import type { FlowHealthResponse } from '@/types/flowHealth';

/**
 * useFlowHealth — TanStack Query hook for GET /metrics/flow-health.
 *
 * Cache strategy: staleTime 60s mirrors the backend request-level cache.
 * Keyed by (teamId, period, startDate, endDate) so changing filters in
 * the global TopBar refetches the right slice.
 *
 * Filter routing lives in `lib/api/flowHealth.ts#buildParams` — squad
 * keys (non-UUID) go as `squad_key`, UUIDs as `team_id`.
 */
export function useFlowHealth() {
  const { teamId, period, startDate, endDate } = useFilterStore();
  return useQuery<FlowHealthResponse>({
    queryKey: ['flow-health', teamId, period, startDate, endDate],
    queryFn: () => fetchFlowHealth({ teamId, period, startDate, endDate }),
    staleTime: 60 * 1000,
  });
}
