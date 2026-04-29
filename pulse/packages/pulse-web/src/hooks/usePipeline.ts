import { useQuery } from '@tanstack/react-query';
import {
  fetchPipelineHealth,
  fetchPipelineSources,
  fetchPipelineIntegrations,
  fetchPipelineTeams,
  fetchPipelineTimeline,
  fetchPipelineCoverage,
  fetchPipelineJobs,
} from '@/lib/api/pipeline';
import type {
  PipelineHealthResponse,
  Source,
  Integration,
  TeamHealth,
  TimelineEvent,
  CoverageResponse,
  ProgressJob,
} from '@/types/pipeline';

export function usePipelineHealth() {
  return useQuery<PipelineHealthResponse>({
    queryKey: ['pipeline-health'],
    queryFn: fetchPipelineHealth,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}

export function usePipelineSources() {
  return useQuery<Source[]>({
    queryKey: ['pipeline-sources'],
    queryFn: fetchPipelineSources,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}

export function usePipelineIntegrations() {
  return useQuery<Integration[]>({
    queryKey: ['pipeline-integrations'],
    queryFn: fetchPipelineIntegrations,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function usePipelineTeams() {
  return useQuery<TeamHealth[]>({
    queryKey: ['pipeline-teams'],
    queryFn: fetchPipelineTeams,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function usePipelineTimeline(params?: {
  severity?: string;
  limit?: number;
}) {
  return useQuery<TimelineEvent[]>({
    queryKey: ['pipeline-timeline', params?.severity, params?.limit],
    queryFn: () => fetchPipelineTimeline(params),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

export function usePipelineCoverage() {
  return useQuery<CoverageResponse>({
    queryKey: ['pipeline-coverage'],
    queryFn: fetchPipelineCoverage,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

/**
 * FDD-OPS-015 — Per-scope progress jobs.
 *
 * 5s polling for live operator visibility. The endpoint is cheap (single
 * indexed table query) and the UI is the primary use case for this data,
 * so polling at 5s keeps "is it stuck?" answerable in near real-time.
 */
export function usePipelineJobs(params?: {
  status?: string;
  entity_type?: string;
  limit?: number;
}) {
  return useQuery<ProgressJob[]>({
    queryKey: ['pipeline-jobs', params?.status, params?.entity_type, params?.limit],
    queryFn: () => fetchPipelineJobs(params),
    refetchInterval: 5_000,
    staleTime: 2_000,
  });
}
