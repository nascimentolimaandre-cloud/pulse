import { dataClient } from './client';
import {
  transformHomeMetrics,
  transformCycleTime,
  transformThroughput,
  transformLeanMetrics,
  transformSprintMetrics,
} from './transforms';
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
    period: params.period,
  };
  // Only send team_id if it's a real UUID (not the "default" placeholder)
  if (params.teamId && params.teamId !== 'default') {
    result.team_id = params.teamId;
  }
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const response = await dataClient.get<any>('/metrics/cycle-time', {
    params: buildParams(params),
  });
  return transformCycleTime(response.data);
}

export async function fetchThroughput(params: MetricsQueryParams): Promise<ThroughputResponse> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const response = await dataClient.get<any>('/metrics/throughput', {
    params: buildParams(params),
  });
  return transformThroughput(response.data);
}

export async function fetchLeanMetrics(params: MetricsQueryParams): Promise<LeanMetrics> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const response = await dataClient.get<any>('/metrics/lean', {
    params: buildParams(params),
  });
  return transformLeanMetrics(response.data);
}

export async function fetchSprintMetrics(params: MetricsQueryParams): Promise<SprintResponse> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const response = await dataClient.get<any>('/metrics/sprints', {
    params: buildParams(params),
  });
  return transformSprintMetrics(response.data);
}

export async function fetchOpenPullRequests(params: MetricsQueryParams): Promise<PullRequest[]> {
  const response = await dataClient.get<PullRequest[]>('/metrics/prs/open', {
    params: buildParams(params),
  });
  return response.data;
}

export async function fetchHomeMetrics(params: MetricsQueryParams): Promise<HomeMetrics> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const response = await dataClient.get<any>('/metrics/home', {
    params: buildParams(params),
  });
  return transformHomeMetrics(response.data);
}

export async function fetchIntegrations(): Promise<Integration[]> {
  const response = await dataClient.get<Integration[]>('/integrations');
  return response.data;
}

