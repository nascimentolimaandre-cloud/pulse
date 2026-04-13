// ---------------------------------------------------------------------------
// @pulse/shared — Jira Admin (Dynamic Project Discovery)
// Shared types for the admin API + UI surface defined in ADR-014.
// ---------------------------------------------------------------------------

/**
 * Per-tenant operating mode for Jira project discovery + ingestion.
 *
 * - `auto`      — every discovered project is active; blocklist overrides
 * - `allowlist` — only explicitly approved projects sync (default, safe)
 * - `blocklist` — all discovered projects active except blocked ones
 * - `smart`     — auto-activate projects referenced by >= N PRs in lookback
 */
export type JiraDiscoveryMode = 'auto' | 'allowlist' | 'blocklist' | 'smart';

/** Lifecycle status of a catalogued Jira project. */
export type JiraProjectStatus =
  | 'discovered' // found by discovery, awaiting decision
  | 'active'     // actively synced
  | 'paused'     // temporarily halted (auto or manual)
  | 'blocked'    // hard-blocked, overrides any mode
  | 'archived';  // Jira side no longer returns this project

/** Where a project's `active` status originated. */
export type JiraActivationSource =
  | 'manual'         // admin clicked activate in UI
  | 'auto_mode'      // mode=auto promoted on first discovery
  | 'smart_pr_scan'  // smart prioritizer activated based on PR refs
  | 'env_bootstrap'; // seeded from legacy JIRA_PROJECTS env var

/** Outcome of a single discovery run. */
export type JiraDiscoveryRunStatus = 'success' | 'partial' | 'failed';

/** Outcome of a per-project sync cycle. */
export type JiraProjectSyncStatus = 'success' | 'partial' | 'failed';

/** Audit event types (append-only trail). */
export type JiraAuditEventType =
  | 'discovery_run'
  | 'mode_changed'
  | 'project_activated'
  | 'project_paused'
  | 'project_blocked'
  | 'project_resumed'
  | 'project_auto_paused'     // triggered by Guardrails (N consecutive failures)
  | 'project_cap_enforced'    // Guardrails demoted due to max_active_projects
  | 'project_pii_flagged'     // PII-sensitive name detected on discovery
  | 'project_pii_gated';      // auto/smart activation blocked due to PII flag

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface TenantJiraConfig {
  tenantId: string;
  mode: JiraDiscoveryMode;
  discoveryEnabled: boolean;
  discoveryScheduleCron: string;
  maxActiveProjects: number;
  maxIssuesPerHour: number;
  smartPrScanDays: number;
  smartMinPrReferences: number;
  lastDiscoveryAt: string | null;
  lastDiscoveryStatus: JiraDiscoveryRunStatus | null;
  lastDiscoveryError: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Fields an admin can mutate via PUT /config. */
export interface UpdateTenantJiraConfigInput {
  mode?: JiraDiscoveryMode;
  discoveryEnabled?: boolean;
  discoveryScheduleCron?: string;
  maxActiveProjects?: number;
  maxIssuesPerHour?: number;
  smartPrScanDays?: number;
  smartMinPrReferences?: number;
}

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

export interface JiraProjectCatalogEntry {
  id: string;
  tenantId: string;
  projectKey: string;
  projectId: string | null;
  name: string | null;
  projectType: string | null;
  leadAccountId: string | null;
  status: JiraProjectStatus;
  activationSource: JiraActivationSource | null;
  issueCount: number;
  prReferenceCount: number;
  firstSeenAt: string;
  activatedAt: string | null;
  lastSyncAt: string | null;
  lastSyncStatus: JiraProjectSyncStatus | null;
  consecutiveFailures: number;
  lastError: string | null;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface JiraProjectCatalogListResponse {
  items: JiraProjectCatalogEntry[];
  total: number;
  counts: Record<JiraProjectStatus, number>;
}

/** Query params accepted by GET /projects. */
export interface JiraProjectCatalogQuery {
  status?: JiraProjectStatus | JiraProjectStatus[];
  search?: string; // matches project_key or name
  limit?: number;
  offset?: number;
  sortBy?: 'project_key' | 'pr_reference_count' | 'issue_count' | 'last_sync_at';
  sortDir?: 'asc' | 'desc';
}

/** Body for POST /projects/:key/{action}. */
export interface JiraProjectActionInput {
  reason?: string; // recorded in audit trail
}

// ---------------------------------------------------------------------------
// Discovery run
// ---------------------------------------------------------------------------

export interface JiraDiscoveryResult {
  runId: string;
  startedAt: string;
  finishedAt: string | null;
  status: JiraDiscoveryRunStatus;
  discoveredCount: number;    // net new catalog rows
  activatedCount: number;     // moved to 'active' by mode/smart
  archivedCount: number;      // present in catalog but gone from Jira
  updatedCount: number;       // metadata refreshed
  errors: string[];
}

export interface JiraDiscoveryStatusResponse {
  inFlight: boolean;
  currentRunId: string | null;
  lastRun: JiraDiscoveryResult | null;
  tenantConfig: Pick<
    TenantJiraConfig,
    'mode' | 'discoveryEnabled' | 'discoveryScheduleCron' | 'lastDiscoveryAt' | 'lastDiscoveryStatus'
  >;
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

export interface JiraDiscoveryAuditEntry {
  id: string;
  tenantId: string;
  eventType: JiraAuditEventType;
  projectKey: string | null;
  actor: string; // user id | 'system' | 'smart_auto'
  beforeValue: unknown;
  afterValue: unknown;
  reason: string | null;
  createdAt: string;
}

export interface JiraAuditQuery {
  eventType?: JiraAuditEventType | JiraAuditEventType[];
  projectKey?: string;
  since?: string; // ISO timestamp
  limit?: number;
  offset?: number;
}

export interface JiraAuditListResponse {
  items: JiraDiscoveryAuditEntry[];
  total: number;
}

// ---------------------------------------------------------------------------
// Smart Suggestions (UI banner)
// ---------------------------------------------------------------------------

export interface JiraSmartSuggestion {
  projectKey: string;
  prReferenceCount: number;
  suggestedAction: 'activate';
  reason: string; // human-readable (e.g. "Referenced in 524 PRs across 37 repos")
}

export interface JiraSmartSuggestionsResponse {
  items: JiraSmartSuggestion[];
  thresholdPrReferences: number;
}
