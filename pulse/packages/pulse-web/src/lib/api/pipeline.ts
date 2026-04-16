import { dataClient } from './client';
import type {
  PipelineHealthResponse,
  Source,
  Integration,
  TeamHealth,
  TimelineEvent,
  CoverageResponse,
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
