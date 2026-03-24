import { dataClient } from './client';
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

export interface MetricsQueryParams {
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

export async function fetchThroughput(params: MetricsQueryParams): Promise<ThroughputResponse> {
  const response = await dataClient.get<ThroughputResponse>('/metrics/throughput', {
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

export async function fetchSprintMetrics(params: MetricsQueryParams): Promise<SprintResponse> {
  const response = await dataClient.get<SprintResponse>('/metrics/sprints', {
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

export async function fetchHomeMetrics(params: MetricsQueryParams): Promise<HomeMetrics> {
  const response = await dataClient.get<HomeMetrics>('/metrics/home', {
    params: buildParams(params),
  });
  return response.data;
}

export async function fetchIntegrations(): Promise<Integration[]> {
  const response = await dataClient.get<Integration[]>('/integrations');
  return response.data;
}
