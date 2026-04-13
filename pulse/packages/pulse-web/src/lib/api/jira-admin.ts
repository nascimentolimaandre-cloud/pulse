import { apiClient } from './client';
import type {
  TenantJiraConfig,
  UpdateTenantJiraConfigInput,
  JiraProjectCatalogListResponse,
  JiraProjectCatalogQuery,
  JiraProjectCatalogEntry,
  JiraProjectActionInput,
  JiraDiscoveryStatusResponse,
  JiraAuditListResponse,
  JiraAuditQuery,
  JiraSmartSuggestionsResponse,
} from '@pulse/shared';

const BASE = '/v1/admin/integrations/jira';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export async function getJiraConfig(): Promise<TenantJiraConfig> {
  const response = await apiClient.get<TenantJiraConfig>(`${BASE}/config`);
  return response.data;
}

export async function updateJiraConfig(
  input: UpdateTenantJiraConfigInput,
): Promise<TenantJiraConfig> {
  const response = await apiClient.put<TenantJiraConfig>(`${BASE}/config`, input);
  return response.data;
}

// ---------------------------------------------------------------------------
// Project catalog
// ---------------------------------------------------------------------------

function buildCatalogParams(query: JiraProjectCatalogQuery): Record<string, string> {
  const params: Record<string, string> = {};
  if (query.status) {
    params.status = Array.isArray(query.status) ? query.status.join(',') : query.status;
  }
  if (query.search) params.search = query.search;
  if (query.limit != null) params.limit = String(query.limit);
  if (query.offset != null) params.offset = String(query.offset);
  if (query.sortBy) params.sortBy = query.sortBy;
  if (query.sortDir) params.sortDir = query.sortDir;
  return params;
}

export async function listJiraProjects(
  query: JiraProjectCatalogQuery = {},
): Promise<JiraProjectCatalogListResponse> {
  const response = await apiClient.get<JiraProjectCatalogListResponse>(`${BASE}/projects`, {
    params: buildCatalogParams(query),
  });
  return response.data;
}

export async function getJiraProject(key: string): Promise<JiraProjectCatalogEntry> {
  const response = await apiClient.get<JiraProjectCatalogEntry>(`${BASE}/projects/${key}`);
  return response.data;
}

export async function activateProject(
  key: string,
  body: JiraProjectActionInput = {},
): Promise<JiraProjectCatalogEntry> {
  const response = await apiClient.post<JiraProjectCatalogEntry>(
    `${BASE}/projects/${key}/activate`,
    body,
  );
  return response.data;
}

export async function pauseProject(
  key: string,
  body: JiraProjectActionInput = {},
): Promise<JiraProjectCatalogEntry> {
  const response = await apiClient.post<JiraProjectCatalogEntry>(
    `${BASE}/projects/${key}/pause`,
    body,
  );
  return response.data;
}

export async function blockProject(
  key: string,
  body: JiraProjectActionInput = {},
): Promise<JiraProjectCatalogEntry> {
  const response = await apiClient.post<JiraProjectCatalogEntry>(
    `${BASE}/projects/${key}/block`,
    body,
  );
  return response.data;
}

export async function resumeProject(
  key: string,
  body: JiraProjectActionInput = {},
): Promise<JiraProjectCatalogEntry> {
  const response = await apiClient.post<JiraProjectCatalogEntry>(
    `${BASE}/projects/${key}/resume`,
    body,
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

export async function triggerDiscovery(): Promise<JiraDiscoveryStatusResponse> {
  const response = await apiClient.post<JiraDiscoveryStatusResponse>(`${BASE}/discovery/trigger`);
  return response.data;
}

export async function getDiscoveryStatus(): Promise<JiraDiscoveryStatusResponse> {
  const response = await apiClient.get<JiraDiscoveryStatusResponse>(`${BASE}/discovery/status`);
  return response.data;
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

function buildAuditParams(query: JiraAuditQuery): Record<string, string> {
  const params: Record<string, string> = {};
  if (query.eventType) {
    params.event_type = Array.isArray(query.eventType)
      ? query.eventType.join(',')
      : query.eventType;
  }
  if (query.projectKey) params.project_key = query.projectKey;
  if (query.since) params.since = query.since;
  if (query.limit != null) params.limit = String(query.limit);
  if (query.offset != null) params.offset = String(query.offset);
  return params;
}

export async function listAudit(query: JiraAuditQuery = {}): Promise<JiraAuditListResponse> {
  const response = await apiClient.get<JiraAuditListResponse>(`${BASE}/audit`, {
    params: buildAuditParams(query),
  });
  return response.data;
}

// ---------------------------------------------------------------------------
// Smart Suggestions
// ---------------------------------------------------------------------------

export async function getSmartSuggestions(): Promise<JiraSmartSuggestionsResponse> {
  const response = await apiClient.get<JiraSmartSuggestionsResponse>(
    `${BASE}/smart-suggestions`,
  );
  return response.data;
}
