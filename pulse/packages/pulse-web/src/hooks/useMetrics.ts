import { useQuery } from '@tanstack/react-query';
import { useFilterStore } from '@/stores/filterStore';
import {
  fetchDoraMetrics,
  fetchCycleTime,
  fetchThroughput,
  fetchLeanMetrics,
  fetchSprintMetrics,
  fetchOpenPullRequests,
  fetchHomeMetrics,
  fetchIntegrations,
} from '@/lib/api/metrics';
import type {
  DoraMetrics,
  CycleTimeBreakdown,
  LeanMetrics,
  PullRequest,
  HomeMetrics,
  ThroughputResponse,
  SprintResponse,
  Integration,
} from '@/types/metrics';

function useFilterParams() {
  const { teamId, period, startDate, endDate } = useFilterStore();
  return { teamId, period, startDate, endDate };
}

export function useDoraMetrics() {
  const params = useFilterParams();
  return useQuery<DoraMetrics>({
    queryKey: ['dora-metrics', params.teamId, params.period, params.startDate, params.endDate],
    queryFn: () => fetchDoraMetrics(params),
  });
}

export function useCycleTimeMetrics() {
  const params = useFilterParams();
  return useQuery<CycleTimeBreakdown>({
    queryKey: ['cycle-time', params.teamId, params.period, params.startDate, params.endDate],
    queryFn: () => fetchCycleTime(params),
  });
}

export function useThroughputMetrics() {
  const params = useFilterParams();
  return useQuery<ThroughputResponse>({
    queryKey: ['throughput', params.teamId, params.period, params.startDate, params.endDate],
    queryFn: () => fetchThroughput(params),
  });
}

export function useLeanMetrics() {
  const params = useFilterParams();
  return useQuery<LeanMetrics>({
    queryKey: ['lean-metrics', params.teamId, params.period, params.startDate, params.endDate],
    queryFn: () => fetchLeanMetrics(params),
  });
}

export function useSprintMetrics() {
  const params = useFilterParams();
  return useQuery<SprintResponse>({
    queryKey: ['sprint-metrics', params.teamId, params.period, params.startDate, params.endDate],
    queryFn: () => fetchSprintMetrics(params),
  });
}

export function usePullRequests() {
  const params = useFilterParams();
  return useQuery<PullRequest[]>({
    queryKey: ['pull-requests', params.teamId, params.period, params.startDate, params.endDate],
    queryFn: () => fetchOpenPullRequests(params),
  });
}

export function useHomeMetrics() {
  const params = useFilterParams();
  return useQuery<HomeMetrics>({
    queryKey: ['home-metrics', params.teamId, params.period, params.startDate, params.endDate],
    queryFn: () => fetchHomeMetrics(params),
  });
}

export function useIntegrations() {
  return useQuery<Integration[]>({
    queryKey: ['integrations'],
    queryFn: fetchIntegrations,
    staleTime: 30 * 1000,
  });
}

