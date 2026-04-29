import { dataClient } from './client';
import type {
  PipelineHealthResponse,
  Source,
  Integration,
  TeamHealth,
  TimelineEvent,
  CoverageResponse,
  ProgressJob,
} from '@/types/pipeline';

export async function fetchPipelineHealth(): Promise<PipelineHealthResponse> {
  const response = await dataClient.get<PipelineHealthResponse>('/pipeline/health');
  return response.data;
}

export async function fetchPipelineSources(): Promise<Source[]> {
  const response = await dataClient.get<Source[]>('/pipeline/sources');
  return response.data;
}

export async function fetchPipelineIntegrations(): Promise<Integration[]> {
  const response = await dataClient.get<Integration[]>('/pipeline/integrations');
  return response.data;
}

export async function fetchPipelineTeams(): Promise<TeamHealth[]> {
  const response = await dataClient.get<TeamHealth[]>('/pipeline/teams');
  return response.data;
}

export async function fetchPipelineTimeline(params?: {
  severity?: string;
  limit?: number;
}): Promise<TimelineEvent[]> {
  const response = await dataClient.get<TimelineEvent[]>('/pipeline/timeline', {
    params: {
      ...(params?.severity && { severity: params.severity }),
      ...(params?.limit && { limit: params.limit }),
    },
  });
  return response.data;
}

export async function fetchPipelineCoverage(): Promise<CoverageResponse> {
  const response = await dataClient.get<CoverageResponse>('/pipeline/coverage');
  return response.data;
}

/**
 * FDD-OPS-015 — per-scope ingestion progress (live + recently completed).
 *
 * Returns 1 row per active or recently-completed scope. Backend orders
 * running first (most recent activity), then by last_progress_at desc.
 *
 * Used by PerScopeJobs tab in Pipeline Monitor with 5s polling.
 */
export async function fetchPipelineJobs(params?: {
  status?: string;
  entity_type?: string;
  limit?: number;
}): Promise<ProgressJob[]> {
  const response = await dataClient.get<ProgressJob[]>('/pipeline/jobs', {
    params: {
      ...(params?.status && { status: params.status }),
      ...(params?.entity_type && { entity_type: params.entity_type }),
      ...(params?.limit && { limit: params.limit }),
    },
  });
  return response.data;
}
