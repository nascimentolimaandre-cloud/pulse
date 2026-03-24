import { useQuery } from '@tanstack/react-query';
import { fetchDoraMetrics } from '@/lib/api/metrics';
import { useFilterStore } from '@/stores/filterStore';
import type { DoraMetrics } from '@/types/metrics';

export function useDoraMetrics() {
  const { teamId, period, startDate, endDate } = useFilterStore();

  return useQuery<DoraMetrics>({
    queryKey: ['dora-metrics', teamId, period, startDate, endDate],
    queryFn: () =>
      fetchDoraMetrics({
        teamId,
        period,
        startDate,
        endDate,
      }),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 60 * 1000,
  });
}
