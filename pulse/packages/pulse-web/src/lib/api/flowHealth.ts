import { dataClient } from './client';
import type { FlowHealthResponse } from '@/types/flowHealth';

export interface FlowHealthQueryParams {
  teamId: string;
  period: string;
  startDate?: string | null;
  endDate?: string | null;
}

// Matches canonical UUID v1–v5 (shared with metrics.ts — small enough to duplicate
// rather than take a cross-module dep on a private regex).
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function buildParams(params: FlowHealthQueryParams): Record<string, string> {
  const result: Record<string, string> = { period: params.period };
  if (params.teamId && params.teamId !== 'default') {
    if (UUID_RE.test(params.teamId)) {
      result.team_id = params.teamId;
    } else {
      result.squad_key = params.teamId.toUpperCase();
    }
  }
  if (params.period === 'custom' && params.startDate && params.endDate) {
    result.start_date = params.startDate;
    result.end_date = params.endDate;
  }
  return result;
}

export async function fetchFlowHealth(
  params: FlowHealthQueryParams,
): Promise<FlowHealthResponse> {
  const response = await dataClient.get<FlowHealthResponse>('/metrics/flow-health', {
    params: buildParams(params),
  });
  return response.data;
}
