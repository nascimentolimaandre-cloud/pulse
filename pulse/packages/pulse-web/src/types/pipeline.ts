/* ── Pipeline Monitor v2 Types ── */

export type SourceStatus = 'healthy' | 'backfilling' | 'degraded' | 'error' | 'slow';
export type EntityStatus = 'idle' | 'healthy' | 'running' | 'backfilling' | 'degraded' | 'error';
export type StepStatus = 'pending' | 'running' | 'done' | 'error' | 'degraded';
export type GlobalHealth = 'healthy' | 'degraded' | 'error' | 'backfilling' | 'slow';
export type Severity = 'success' | 'info' | 'warning' | 'error';

export type StatusKey =
  | 'healthy'
  | 'idle'
  | 'running'
  | 'backfilling'
  | 'degraded'
  | 'error'
  | 'done'
  | 'slow'
  | 'disabled'
  | 'pending';

/* ── Health ── */

export interface PipelineHealthResponse {
  health: GlobalHealth;
  lastUpdatedAt: string;
  kpis: {
    recordsToday: number;
    recordsTrendPct: number;
    prIssueLinkRate: number;
    prIssueLinkTrendPp: number;
    reposWithDeploy30d: { covered: number; total: number };
    avgSyncLagSec: number;
    p95SyncLagSec: number;
  };
}

/* ── Sources ── */

export interface Step {
  name: 'fetch' | 'changelog' | 'normalize' | 'upsert';
  status: StepStatus;
  processed: number;
  total: number;
  durationSec?: number;
  etaSec?: number;
  throughputPerSec?: number;
}

export interface Entity {
  type: string;
  label: string;
  status: EntityStatus;
  watermark: string;
  lastCycleRecords?: number;
  lastCycleDurationSec?: number;
  error?: string;
  steps?: Step[];
}

export interface SourceCatalog {
  active: number;
  discovered: number;
  paused: number;
  blocked: number;
  archived: number;
}

export interface Source {
  id: string;
  name: string;
  status: SourceStatus;
  connections: number;
  rateLimitPct: number;
  watermark: string;
  catalog: SourceCatalog;
  entities: Entity[];
}

/* ── Integrations ── */

export interface Integration {
  id: string;
  name: string;
  connected: boolean;
  status: 'healthy' | 'backfilling' | 'degraded' | 'error' | 'disabled';
  detail: string;
}

/* ── Teams ── */

export interface TeamHealth {
  id: string;
  name: string;
  tribe: string | null;
  squadKey: string;
  health: 'healthy' | 'backfilling' | 'degraded' | 'error';
  repos: number;
  jiraProjects: string[];
  jenkinsJobs: number;
  prCount: number;
  issueCount: number;
  deployCount: number;
  linkRate: number;
  lastSync: string;
  lagSec: number;
}

/* ── Timeline ── */

export interface TimelineEvent {
  ts: string;
  severity: Severity;
  stage: string;
  message: string;
}

/* ── Coverage ── */

export interface CoverageResponse {
  reposWithDeploy: { covered: number; total: number };
  prIssueLinkRate: number;
  orphanPrefixes: Array<{ prefix: string; prMentions: number }>;
  activeProjectsWithoutIssues: Array<{ key: string; name: string }>;
}

/* ── Pipeline Phase (used for pipeline tab view) ── */

export interface PipelinePhaseCell {
  phase: string;
  status: StatusKey;
  line1: string;
  line2: string;
  steps?: Array<{ n: string; s: StepStatus; p: number }>;
}

export interface PipelineSourceRow {
  sourceId: string;
  sourceName: string;
  phases: PipelinePhaseCell[];
}
