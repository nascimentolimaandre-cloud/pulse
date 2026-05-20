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

// BC-Obs Observability (FDD-OBS-001)
export type {
  DatadogValidateRequest,
  DatadogValidateResponse,
  CredentialStatus,
  CredentialMetadataResponse,
  OwnershipSyncResponse,
  OverrideRequest,
  InferredConfidence,
  OwnershipRowResponse,
  OwnershipListResponse,
  AliasMapping,
  AliasResponse,
  AliasListResponse,
  AliasBulkImportRequest,
  AliasBulkImportResponse,
  AliasSuggestionsResponse,
  TimelineHealthBucket,
  TimelineDeployMarker,
  TimelineScope,
  TimelineResponse,
} from './types/observability';

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
