import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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
  JiraProjectStatus,
} from '@pulse/shared';
import {
  getJiraConfig,
  updateJiraConfig,
  listJiraProjects,
  getJiraProject,
  activateProject,
  pauseProject,
  blockProject,
  resumeProject,
  triggerDiscovery,
  getDiscoveryStatus,
  listAudit,
  getSmartSuggestions,
} from '@/lib/api/jira-admin';

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const jiraAdminKeys = {
  all: ['jira-admin'] as const,
  config: () => [...jiraAdminKeys.all, 'config'] as const,
  projects: () => [...jiraAdminKeys.all, 'projects'] as const,
  projectList: (query: JiraProjectCatalogQuery) =>
    [...jiraAdminKeys.projects(), query] as const,
  projectDetail: (key: string) => [...jiraAdminKeys.projects(), key] as const,
  discoveryStatus: () => [...jiraAdminKeys.all, 'discovery-status'] as const,
  audit: () => [...jiraAdminKeys.all, 'audit'] as const,
  auditList: (query: JiraAuditQuery) => [...jiraAdminKeys.audit(), query] as const,
  suggestions: () => [...jiraAdminKeys.all, 'suggestions'] as const,
};

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export function useJiraConfigQuery() {
  return useQuery<TenantJiraConfig>({
    queryKey: jiraAdminKeys.config(),
    queryFn: getJiraConfig,
    staleTime: 30_000,
  });
}

export function useJiraConfigMutation() {
  const queryClient = useQueryClient();
  return useMutation<TenantJiraConfig, Error, UpdateTenantJiraConfigInput>({
    mutationFn: updateJiraConfig,
    onSuccess: (data) => {
      queryClient.setQueryData(jiraAdminKeys.config(), data);
      // Discovery status might change after config update
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.discoveryStatus() });
    },
  });
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export function useJiraProjectsQuery(query: JiraProjectCatalogQuery) {
  return useQuery<JiraProjectCatalogListResponse>({
    queryKey: jiraAdminKeys.projectList(query),
    queryFn: () => listJiraProjects(query),
    staleTime: 15_000,
  });
}

export function useJiraProjectQuery(key: string, enabled = true) {
  return useQuery<JiraProjectCatalogEntry>({
    queryKey: jiraAdminKeys.projectDetail(key),
    queryFn: () => getJiraProject(key),
    enabled,
    staleTime: 15_000,
  });
}

// ---------------------------------------------------------------------------
// Project actions (activate / pause / block / resume)
// ---------------------------------------------------------------------------

type ProjectAction = 'activate' | 'pause' | 'block' | 'resume';

const ACTION_FNS: Record<
  ProjectAction,
  (key: string, body: JiraProjectActionInput) => Promise<JiraProjectCatalogEntry>
> = {
  activate: activateProject,
  pause: pauseProject,
  block: blockProject,
  resume: resumeProject,
};

/** Maps action to the optimistic next status */
const OPTIMISTIC_STATUS: Record<ProjectAction, JiraProjectStatus> = {
  activate: 'active',
  pause: 'paused',
  block: 'blocked',
  resume: 'active',
};

interface ProjectActionVars {
  action: ProjectAction;
  projectKey: string;
  body?: JiraProjectActionInput;
}

interface ProjectActionContext {
  previousQueries: [readonly unknown[], JiraProjectCatalogListResponse | undefined][];
}

export function useProjectActionMutation() {
  const queryClient = useQueryClient();

  return useMutation<JiraProjectCatalogEntry, Error, ProjectActionVars, ProjectActionContext>({
    mutationFn: ({ action, projectKey, body }) =>
      ACTION_FNS[action](projectKey, body ?? {}),

    onMutate: async ({ action, projectKey }) => {
      // Cancel in-flight queries to avoid overwriting optimistic update
      await queryClient.cancelQueries({ queryKey: jiraAdminKeys.projects() });

      // Snapshot for rollback
      const previousQueries = queryClient.getQueriesData<JiraProjectCatalogListResponse>({
        queryKey: jiraAdminKeys.projects(),
      });

      // Optimistic update: patch the status in all cached project lists
      queryClient.setQueriesData<JiraProjectCatalogListResponse>(
        { queryKey: jiraAdminKeys.projects() },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            items: old.items.map((item) =>
              item.projectKey === projectKey
                ? { ...item, status: OPTIMISTIC_STATUS[action] }
                : item,
            ),
          };
        },
      );

      return { previousQueries };
    },

    onError: (_err, _vars, context) => {
      // Rollback on error
      if (context?.previousQueries) {
        for (const [queryKey, data] of context.previousQueries) {
          queryClient.setQueryData(queryKey, data);
        }
      }
    },

    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.projects() });
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.audit() });
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.suggestions() });
    },
  });
}

// ---------------------------------------------------------------------------
// Bulk action (applies the same action to multiple keys)
// ---------------------------------------------------------------------------

export function useBulkProjectActionMutation() {
  const queryClient = useQueryClient();

  return useMutation<
    JiraProjectCatalogEntry[],
    Error,
    { action: ProjectAction; projectKeys: string[]; body?: JiraProjectActionInput }
  >({
    mutationFn: async ({ action, projectKeys, body }) => {
      const fn = ACTION_FNS[action];
      return Promise.all(projectKeys.map((key) => fn(key, body ?? {})));
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.projects() });
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.audit() });
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.suggestions() });
    },
  });
}

// ---------------------------------------------------------------------------
// Discovery status (polls while in-flight)
// ---------------------------------------------------------------------------

export function useDiscoveryStatusQuery() {
  return useQuery<JiraDiscoveryStatusResponse>({
    queryKey: jiraAdminKeys.discoveryStatus(),
    queryFn: getDiscoveryStatus,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.inFlight ? 5_000 : false;
    },
    staleTime: 5_000,
  });
}

export function useDiscoveryTriggerMutation() {
  const queryClient = useQueryClient();
  return useMutation<JiraDiscoveryStatusResponse, Error>({
    mutationFn: triggerDiscovery,
    onSuccess: (data) => {
      queryClient.setQueryData(jiraAdminKeys.discoveryStatus(), data);
    },
    onSettled: () => {
      // After trigger, refresh projects and status
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.discoveryStatus() });
      void queryClient.invalidateQueries({ queryKey: jiraAdminKeys.projects() });
    },
  });
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

export function useJiraAuditQuery(query: JiraAuditQuery) {
  return useQuery<JiraAuditListResponse>({
    queryKey: jiraAdminKeys.auditList(query),
    queryFn: () => listAudit(query),
    staleTime: 30_000,
  });
}

// ---------------------------------------------------------------------------
// Smart Suggestions
// ---------------------------------------------------------------------------

export function useSmartSuggestionsQuery() {
  return useQuery<JiraSmartSuggestionsResponse>({
    queryKey: jiraAdminKeys.suggestions(),
    queryFn: getSmartSuggestions,
    staleTime: 60_000,
  });
}
