import { useQuery } from '@tanstack/react-query';
import {
  fetchPipelineHealth,
  fetchPipelineSources,
  fetchPipelineIntegrations,
  fetchPipelineTeams,
  fetchPipelineTimeline,
  fetchPipelineCoverage,
} from '@/lib/api/pipeline';
import type {
  PipelineHealthResponse,
  Source,
  Integration,
  TeamHealth,
  TimelineEvent,
  CoverageResponse,
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
