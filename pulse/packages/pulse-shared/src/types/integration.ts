// ---------------------------------------------------------------------------
// BC2 Integration — Shared type definitions
// ---------------------------------------------------------------------------

export type SourceType = 'github' | 'gitlab' | 'jira' | 'azure_devops';

export type ConnectionStatus =
  | 'pending'
  | 'connected'
  | 'syncing'
  | 'error'
  | 'disabled';

export interface Connection {
  id: string;
  organizationId: string;
  name: string;
  source: SourceType;
  status: ConnectionStatus;
  /** Base URL for self-hosted instances */
  baseUrl?: string;
  /** Scopes/repos/projects included in the sync */
  scope: ConnectionScope;
  /** Last successful sync timestamp */
  lastSyncAt?: string;
  /** Error message if status is 'error' */
  lastError?: string;
  /** Sync interval in minutes */
  syncIntervalMinutes: number;
  createdAt: string;
  updatedAt: string;
}

export interface ConnectionScope {
  /** GitHub/GitLab: repository full names (owner/repo) */
  repositories?: string[];
  /** Jira: project keys */
  projects?: string[];
  /** Azure DevOps: project names */
  azureProjects?: string[];
}
