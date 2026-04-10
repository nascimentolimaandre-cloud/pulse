/* ── Pipeline Monitor Types ── */

export type PipelineOverallStatus = 'healthy' | 'syncing' | 'degraded' | 'error';

export type PipelineStageStatus = 'healthy' | 'syncing' | 'idle' | 'error' | 'standby';

export interface PipelineStage {
  name: string;
  status: PipelineStageStatus;
  label: string;
  detail: string | null;
  last_activity: string | null;
}

export interface PipelineKpis {
  total_records: number;
  synced_today: number;
  pending_sync: number;
  errors_24h: number;
  total_records_trend: number | null;
}

export interface RecordCount {
  entity: string;
  /** @deprecated Renamed from devlake_count — now mirrors pulse_count (no intermediate DB). */
  devlake_count: number;
  pulse_count: number;
  difference: number;
  is_synced: boolean;
}

export interface RecentSync {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  trigger: string;
  duration_seconds: number | null;
  records_processed: Record<string, number>;
  error_count: number;
}

export interface PipelineError {
  stage: string;
  message: string;
  timestamp: string;
  error_code: string | null;
  context: Record<string, unknown>;
}

/** @deprecated Kept for API response backward compatibility. Always returns defaults. */
export interface DevLakeStatus {
  is_running: boolean;
  last_status: string | null;
  last_finished_at: string | null;
}

/* ── Source Connection (MVP-1.7.14) ── */

export interface SourceConnection {
  type: string;
  label: string;
  icon: string;
  active: boolean;
  syncing: boolean;
}

/* ── Pipeline Event (MVP-1.7.10 / MVP-1.7.15) ── */

export interface PipelineEvent {
  id: string;
  event_type: string;
  source: string;
  title: string;
  detail: string | null;
  severity: 'info' | 'warning' | 'error' | 'success';
  metadata: Record<string, unknown>;
  occurred_at: string;
}

/* ── Main Status Response (Tela 1) ── */

export interface PipelineStatusData {
  overall_status: PipelineOverallStatus;
  stages: PipelineStage[];
  kpis: PipelineKpis;
  record_counts: RecordCount[];
  recent_syncs: RecentSync[];
  recent_errors: PipelineError[];
  recent_events: PipelineEvent[];
  source_connections: SourceConnection[];
  devlake: DevLakeStatus;
  last_updated: string;
}

/* ── Source Filtered Status (Tela 2 — MVP-1.7.12/16/17/18) ── */

export interface ActiveSync {
  name: string;
  strategy: string;
  progress: number;
  last_key: string;
  status: string;
}

export interface SourceFilteredStatus {
  source: string;
  kpis: Record<string, unknown>;
  stages: PipelineStage[];
  active_syncs: ActiveSync[];
  recent_logs: PipelineEvent[];
  health_pct: number;
  sync_mode: string;
}

/* ── Metrics Worker Status (Tela 3 — MVP-1.7.19/20) ── */

export interface MetricsWorkerSnapshot {
  snapshot_id: string;
  metric_type: string;
  timestamp: string | null;
  duration_seconds: number | null;
  records_processed: number;
  status: string;
}

export interface MetricsWorkerStage {
  name: string;
  icon: string;
  active: boolean;
  label: string;
}

export interface MetricsWorkerClusterLog {
  timestamp: string;
  level: string;
  message: string;
}

export interface MetricsWorkerStatus {
  kpis: Record<string, unknown>;
  stages: MetricsWorkerStage[];
  snapshots: MetricsWorkerSnapshot[];
  cluster_logs: MetricsWorkerClusterLog[];
}
