// ---------------------------------------------------------------------------
// @pulse/shared — Public API
// ---------------------------------------------------------------------------

// BC1 Identity
export type {
  Organization,
  User,
  Team,
  TeamExternalMapping,
  Membership,
} from './types/identity';

// BC2 Integration
export type {
  SourceType,
  ConnectionStatus,
  Connection,
  ConnectionScope,
} from './types/integration';

// BC4 Metrics
export type {
  DoraClassification,
  DoraMetrics,
  CycleTimePhase,
  CycleTimeBreakdown,
  LeadTimeDistribution,
  ThroughputData,
  SprintOverview,
  PullRequestSummary,
  MetricTrend,
  WipStatus,
} from './types/metrics';

// BC2 Integration — Jira Admin (Dynamic Discovery, ADR-014)
export type {
  JiraDiscoveryMode,
  JiraProjectStatus,
  JiraActivationSource,
  JiraDiscoveryRunStatus,
  JiraProjectSyncStatus,
  JiraAuditEventType,
  TenantJiraConfig,
  UpdateTenantJiraConfigInput,
  JiraProjectCatalogEntry,
  JiraProjectCatalogListResponse,
  JiraProjectCatalogQuery,
  JiraProjectActionInput,
  JiraDiscoveryResult,
  JiraDiscoveryStatusResponse,
  JiraDiscoveryAuditEntry,
  JiraAuditQuery,
  JiraAuditListResponse,
  JiraSmartSuggestion,
  JiraSmartSuggestionsResponse,
} from './types/jira-admin';
