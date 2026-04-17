/**
 * Tenant capability flags returned by GET /data/v1/tenant/capabilities.
 *
 * Used to conditionally render sprint-specific and Kanban-specific UI.
 * Backend response is camelCase (Pydantic alias_generator=to_camel).
 */
export interface TenantCapabilitySources {
  jiraConnected: boolean;
  githubConnected: boolean;
  jenkinsConnected: boolean;
}

export interface TenantCapabilities {
  tenantId: string;
  /** Present when the response is squad-scoped (uppercase Jira project key). */
  squadKey: string | null;
  hasSprints: boolean;
  hasKanban: boolean;
  sprintCount: number;
  issueCount30D: number;
  /** Jira board ids linked to the squad (empty when tenant-wide). */
  boards: string[];
  /** Up to 3 recent sprint names — helps operators sanity-check the heuristic. */
  sampleSprints: string[];
  lastEvaluatedAt: string;
  sources: TenantCapabilitySources;
}

/** Capability names that CapabilityGuard can gate rendering on. */
export type CapabilityKey = 'sprints' | 'kanban';
