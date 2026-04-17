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

/* ──────────────────────────────────────────────────────────
 *  Dashboard redesign (Diagnostic-first) — per-team hooks.
 *
 *  TODO(pulse-data-engineer): these hooks currently derive data
 *  deterministically from `GET /data/v1/pipeline/teams`. Replace
 *  with real endpoints when ready:
 *    - GET /data/v1/metrics/by-team?metric={}&period={}
 *    - GET /data/v1/metrics/by-team/evolution?metric={}&period={}
 *    - GET /data/v1/teams/{id}/detail?period={}
 * ────────────────────────────────────────────────────────── */
import { fetchPipelineTeams } from '@/lib/api/pipeline';
import type { TeamHealth } from '@/types/pipeline';
import type { DashboardMetric } from '@/stores/filterStore';
import {
  deriveRanking,
  deriveEvolution,
  deriveTeamDetail,
  type TeamRankingRow,
  type TeamEvolutionSeries,
  type TeamDetailData,
} from '@/lib/dashboard/mockDerive';

export function usePipelineTeamsList() {
  return useQuery<TeamHealth[]>({
    queryKey: ['pipeline-teams'],
    queryFn: fetchPipelineTeams,
    staleTime: 60 * 1000,
  });
}

export function useMetricsByTeam(metric: DashboardMetric) {
  const { data: teams, isLoading, isError, error } = usePipelineTeamsList();
  const rows: TeamRankingRow[] = teams ? deriveRanking(teams, metric) : [];
  return { data: rows, isLoading, isError, error };
}

export function useMetricsByTeamEvolution(metric: DashboardMetric) {
  const { data: teams, isLoading, isError, error } = usePipelineTeamsList();
  const series: TeamEvolutionSeries[] = teams ? deriveEvolution(teams, metric) : [];
  return { data: series, isLoading, isError, error };
}

export function useTeamDetail(teamId: string | null) {
  const { data: teams } = usePipelineTeamsList();
  const team = teamId && teams ? teams.find((t) => t.id === teamId) : null;
  const detail: TeamDetailData | null = team ? deriveTeamDetail(team) : null;
  return { data: detail };
}

