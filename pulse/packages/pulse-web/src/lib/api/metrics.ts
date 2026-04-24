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

// Matches canonical UUID v1–v5 (with hyphens). Case-insensitive.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Build the query params the backend expects for any /metrics/* endpoint.
 *
 * Exported for direct unit testing (see tests/unit/buildParams.test.ts) —
 * this is the function that regressed in FDD-DSH-060 when it briefly sent
 * `team_id=<non-uuid-squad-key>` and triggered HTTP 422 on the backend.
 * Pure function, safe to unit-test in isolation.
 *
 * @internal — consumers should call fetch* helpers below, not buildParams directly.
 */
export function buildParams(params: MetricsQueryParams): Record<string, string> {
  const result: Record<string, string> = {
    period: params.period,
  };
  // Team scoping: backend accepts either `team_id` (UUID from the teams table)
  // or `squad_key` (Jira project key derived from PR titles — the 27 active
  // squads surfaced by /pipeline/teams). We route to whichever matches.
  // See FDD-DSH-060 (resolved via squad_key passthrough).
  if (params.teamId && params.teamId !== 'default') {
    if (UUID_RE.test(params.teamId)) {
      result.team_id = params.teamId;
    } else {
      // Squad keys come in lowercase from /pipeline/teams (TeamHealth.id); the
      // backend expects the canonical uppercase project key. Uppercase here
      // so the regex match on PR titles (case-insensitive anyway) stays clean.
      result.squad_key = params.teamId.toUpperCase();
    }
  }
  // Custom date range: only forward dates when period=custom AND both set.
  // Backend rejects partial custom windows with HTTP 400.
  if (params.period === 'custom' && params.startDate && params.endDate) {
    result.start_date = params.startDate;
    result.end_date = params.endDate;
  }
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

