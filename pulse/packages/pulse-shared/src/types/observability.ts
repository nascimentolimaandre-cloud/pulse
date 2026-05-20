// ---------------------------------------------------------------------------
// BC-Obs Observability — shared types for NestJS proxy <-> React client
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Datadog credential validation
// ---------------------------------------------------------------------------

export interface DatadogValidateRequest {
  api_key: string;
  app_key?: string | null;
  site: string;
  persist?: boolean;
}

export interface DatadogValidateResponse {
  valid: boolean;
  persisted: boolean;
  site: string;
  key_fingerprint?: string | null;
  validated_at?: string | null;
  message?: string | null;
}

// ---------------------------------------------------------------------------
// Credential metadata
// ---------------------------------------------------------------------------

export type CredentialStatus = 'validated' | 'pending_validation' | 'expired';

export interface CredentialMetadataResponse {
  provider: string;
  site: string;
  has_app_key: boolean;
  validated_at: string | null;
  last_rotated_at: string;
  key_fingerprint: string;
  status: CredentialStatus;
}

// ---------------------------------------------------------------------------
// Service Ownership Map
// ---------------------------------------------------------------------------

export interface OwnershipSyncResponse {
  services_seen: number;
  inferred_with_tag: number;
  inferred_with_alias: number;
  inferred_none: number;
  unchanged: number;
  duration_ms: number;
}

export interface OverrideRequest {
  squad_key: string | null;
}

export type InferredConfidence = 'tag' | 'alias' | 'heuristic' | 'none';

export interface OwnershipRowResponse {
  service_external_id: string;
  service_name: string;
  repo_url: string | null;
  inferred_squad_key: string | null;
  inferred_confidence: InferredConfidence | null;
  override_squad_key: string | null;
  effective_squad_key: string | null;
  last_inference_at: string;
  is_qualified_squad: boolean;
}

export interface OwnershipListResponse {
  services: OwnershipRowResponse[];
  coverage_pct: number;
}

// ---------------------------------------------------------------------------
// Team Alias Map
// ---------------------------------------------------------------------------

export interface AliasMapping {
  vendor_team_value: string;
  squad_key: string;
}

export interface AliasResponse {
  vendor_team_value: string;
  squad_key: string;
  created_at: string;
  updated_at: string;
}

export interface AliasListResponse {
  aliases: AliasResponse[];
  total: number;
}

export interface AliasBulkImportRequest {
  mappings: AliasMapping[];
}

export interface AliasBulkImportResponse {
  inserted: number;
  updated: number;
  rejected_invalid_squad: number;
  rejected_empty: number;
  total_submitted: number;
}

export interface AliasSuggestionsResponse {
  vendor_teams: string[];
  total: number;
}

// ---------------------------------------------------------------------------
// Deploy Health Timeline
// ---------------------------------------------------------------------------

export interface TimelineHealthBucket {
  hour_bucket: string;
  severity: number;
  samples_count: number;
  metric: string;
  service: string | null;
}

export interface TimelineDeployMarker {
  deployed_at: string;
  repo: string;
  environment: string | null;
  sha: string | null;
  is_failure: boolean;
  url: string | null;
  service: string | null;
}

export type TimelineScope = 'squad' | 'service';

export interface TimelineResponse {
  scope: TimelineScope;
  squad_key: string | null;
  service: string | null;
  since: string;
  until: string;
  buckets: TimelineHealthBucket[];
  deploys: TimelineDeployMarker[];
  services_in_squad: number;
  has_data: boolean;
}
