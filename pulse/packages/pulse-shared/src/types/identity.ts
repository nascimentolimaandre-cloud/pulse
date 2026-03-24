// ---------------------------------------------------------------------------
// BC1 Identity — Shared type definitions
// ---------------------------------------------------------------------------

export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: 'free' | 'team' | 'business' | 'enterprise';
  createdAt: string;
  updatedAt: string;
}

export interface User {
  id: string;
  organizationId: string;
  email: string;
  displayName: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  avatarUrl?: string;
  createdAt: string;
  updatedAt: string;
}

export interface Team {
  id: string;
  organizationId: string;
  name: string;
  slug: string;
  description?: string;
  /** External identifiers for mapping to source systems */
  externalMappings?: TeamExternalMapping[];
  createdAt: string;
  updatedAt: string;
}

export interface TeamExternalMapping {
  source: 'github' | 'gitlab' | 'jira' | 'azure_devops';
  /** The team/project identifier in the source system */
  externalId: string;
  externalName: string;
}

export interface Membership {
  id: string;
  userId: string;
  teamId: string;
  role: 'lead' | 'member';
  joinedAt: string;
}
