import { dataClient } from './client';
import type {
  DoraMetrics,
  CycleTimeBreakdown,
  ThroughputData,
  LeanMetrics,
  SprintOverview,
  PullRequest,
} from '@/types/metrics';

interface MetricsQueryParams {
  teamId: string;
  period: string;
  startDate?: string | null;
  endDate?: string | null;
}

function buildParams(params: MetricsQueryParams): Record<string, string> {
  const result: Record<string, string> = {
    team_id: params.teamId,
    period: params.period,
  };
  if (params.startDate) result.start_date = params.startDate;
  if (params.endDate) result.end_date = params.endDate;
  return result;
}

export async function fetchDoraMetrics(params: MetricsQueryParams): Promise<DoraMetrics> {
  const response = await dataClient.get<DoraMetrics>('/metrics/dora', {
    params: buildParams(params),
  });
  return response.data;
}

export async function fetchCycleTime(params: MetricsQueryParams): Promise<CycleTimeBreakdown> {
  const response = await dataClient.get<CycleTimeBreakdown>('/metrics/cycle-time', {
    params: buildParams(params),
  });
  return response.data;
}

export async function fetchThroughput(params: MetricsQueryParams): Promise<ThroughputData> {
  const response = await dataClient.get<ThroughputData>('/metrics/throughput', {
    params: buildParams(params),
  });
  return response.data;
}

export async function fetchLeanMetrics(params: MetricsQueryParams): Promise<LeanMetrics> {
  const response = await dataClient.get<LeanMetrics>('/metrics/lean', {
    params: buildParams(params),
  });
  return response.data;
}

export async function fetchSprintOverview(params: MetricsQueryParams): Promise<SprintOverview[]> {
  const response = await dataClient.get<SprintOverview[]>('/metrics/sprints', {
    params: buildParams(params),
  });
  return response.data;
}

export async function fetchOpenPullRequests(params: MetricsQueryParams): Promise<PullRequest[]> {
  const response = await dataClient.get<PullRequest[]>('/metrics/prs/open', {
    params: buildParams(params),
  });
  return response.data;
}
