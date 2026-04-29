/**
 * FDD-OPS-015 — Per-scope ingestion progress table.
 *
 * One row per active or recently-completed ingestion scope (Jira project,
 * GitHub repo, Jenkins job). Backend orders running first; UI adds
 * client-side filters by entity_type and status. Polling every 5s for
 * live ETA updates.
 *
 * Operator goal: answer "is the BG project still progressing or stuck?"
 * in seconds, without reading server logs. Stalled badge appears when
 * the backend computes `isStalled=true` (status='running' AND no
 * progress for >60s).
 */

import { useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock, XCircle, Loader2, PauseCircle, Filter } from 'lucide-react';
import { usePipelineJobs } from '@/hooks/usePipeline';
import type { ProgressJob, ProgressJobStatus } from '@/types/pipeline';

type EntityFilter = 'all' | 'issues' | 'pull_requests' | 'deployments' | 'sprints';
type StatusFilter = 'all' | ProgressJobStatus;

const ENTITY_OPTIONS: Array<{ value: EntityFilter; label: string }> = [
  { value: 'all', label: 'All entities' },
  { value: 'issues', label: 'Issues' },
  { value: 'pull_requests', label: 'Pull Requests' },
  { value: 'deployments', label: 'Deployments' },
  { value: 'sprints', label: 'Sprints' },
];

const STATUS_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: 'All statuses' },
  { value: 'running', label: 'Running' },
  { value: 'done', label: 'Done' },
  { value: 'failed', label: 'Failed' },
  { value: 'paused', label: 'Paused' },
];

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtETA(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds === 0) return 'done';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function fmtRate(rate: number): string {
  if (rate === 0) return '—';
  if (rate < 1) return `${rate.toFixed(2)}/s`;
  if (rate < 10) return `${rate.toFixed(1)}/s`;
  return `${Math.round(rate)}/s`;
}

function fmtRel(iso: string): string {
  const dt = new Date(iso).getTime();
  const now = Date.now();
  const sec = Math.max(0, Math.floor((now - dt) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function fmtScope(scopeKey: string): { source: string; label: string } {
  // 'jira:project:BG' → { source: 'jira', label: 'BG' }
  // 'github:repo:webmotors-private/foo' → { source: 'github', label: 'webmotors-private/foo' }
  const parts = scopeKey.split(':');
  if (parts.length >= 3) {
    return { source: parts[0] ?? '?', label: parts.slice(2).join(':') };
  }
  return { source: '?', label: scopeKey };
}

// ---------------------------------------------------------------------------
// Status icon + color
// ---------------------------------------------------------------------------

function statusIcon(job: ProgressJob) {
  if (job.isStalled) {
    return <AlertCircle size={14} className="text-status-warning" />;
  }
  switch (job.status) {
    case 'running':
      return <Loader2 size={14} className="text-status-info animate-spin motion-reduce:animate-none" />;
    case 'done':
      return <CheckCircle2 size={14} className="text-status-success" />;
    case 'failed':
      return <XCircle size={14} className="text-status-danger" />;
    case 'paused':
    case 'cancelled':
      return <PauseCircle size={14} className="text-content-secondary" />;
    default:
      return <Clock size={14} className="text-content-secondary" />;
  }
}

function statusLabel(job: ProgressJob): string {
  if (job.isStalled) return 'STALLED';
  return job.status.toUpperCase();
}

function statusBadgeColor(job: ProgressJob): string {
  if (job.isStalled) return 'bg-status-warning/10 text-status-warning border-status-warning/30';
  switch (job.status) {
    case 'running':
      return 'bg-status-info/10 text-status-info border-status-info/30';
    case 'done':
      return 'bg-status-success/10 text-status-success border-status-success/30';
    case 'failed':
      return 'bg-status-danger/10 text-status-danger border-status-danger/30';
    default:
      return 'bg-surface-tertiary text-content-secondary border-border-default';
  }
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function ProgressBar({ job }: { job: ProgressJob }) {
  const pct = job.progressPct ?? 0;
  const hasEstimate = job.itemsEstimate !== null;

  // When no estimate available, show indeterminate stripe via diff color
  let barClass = 'bg-status-info';
  if (job.status === 'failed') barClass = 'bg-status-danger';
  else if (job.status === 'done') barClass = 'bg-status-success';
  else if (job.isStalled) barClass = 'bg-status-warning';

  return (
    <div className="flex flex-col gap-[3px] min-w-[140px]">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-content-secondary">
          {job.itemsDone.toLocaleString()}
          {hasEstimate && (
            <>
              {' / '}
              <span className="text-content-tertiary">
                {job.itemsEstimate!.toLocaleString()}
              </span>
            </>
          )}
        </span>
        <span className="font-medium text-content-primary tabular-nums">
          {hasEstimate ? `${pct.toFixed(0)}%` : '?'}
        </span>
      </div>
      <div className="h-[6px] rounded-full bg-surface-tertiary overflow-hidden">
        <div
          className={`h-full ${barClass} transition-all duration-300 ease-out`}
          style={{ width: hasEstimate ? `${Math.min(100, pct)}%` : '15%' }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty / loading
// ---------------------------------------------------------------------------

function Skeleton() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card overflow-hidden">
      <div className="p-[14px_20px] border-b border-border-default">
        <div className="h-[20px] w-[200px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none" />
      </div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="h-[52px] mx-[20px] border-b border-border-default bg-surface-tertiary/30 animate-pulse motion-reduce:animate-none"
        />
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card p-[40px] text-center">
      <Clock size={32} className="text-content-tertiary mx-auto mb-[12px]" />
      <h3 className="text-[16px] font-semibold text-content-primary mb-[6px]">
        No active ingestion jobs
      </h3>
      <p className="text-[13px] text-content-secondary max-w-[400px] mx-auto">
        Per-scope progress appears here when the sync worker is processing
        scopes (Jira projects, GitHub repos). The page polls every 5 seconds.
      </p>
    </div>
  );
}

function ErrorState({ message }: { message?: string }) {
  return (
    <div className="rounded-card border border-status-danger/30 bg-status-danger/5 shadow-card p-[20px]">
      <div className="flex items-start gap-[10px]">
        <AlertCircle size={18} className="text-status-danger mt-[1px]" />
        <div className="flex-1">
          <h3 className="text-[14px] font-semibold text-content-primary mb-[4px]">
            Failed to load pipeline jobs
          </h3>
          <p className="text-[12px] text-content-secondary">
            {message || 'Try refreshing — the polling will retry automatically.'}
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row component
// ---------------------------------------------------------------------------

function JobRow({ job }: { job: ProgressJob }) {
  const { source, label } = fmtScope(job.scopeKey);
  const stalledClass = job.isStalled
    ? 'bg-status-warning/5 hover:bg-status-warning/10'
    : 'hover:bg-surface-tertiary/50';

  return (
    <div
      className={`grid grid-cols-[2fr_1fr_140px_1.5fr_80px_90px_120px] gap-[12px] items-center px-[20px] py-[12px] border-b border-border-default text-[13px] ${stalledClass} transition-colors`}
    >
      {/* Scope */}
      <div className="min-w-0">
        <div className="font-medium text-content-primary truncate" title={job.scopeKey}>
          {label}
        </div>
        <div className="text-[11px] text-content-tertiary uppercase tracking-wide">
          {source}
        </div>
      </div>

      {/* Entity type */}
      <div className="text-content-secondary text-[12px]">
        {job.entityType.replace('_', ' ')}
      </div>

      {/* Progress */}
      <ProgressBar job={job} />

      {/* Status badge */}
      <div className="flex items-center gap-[8px]">
        <span
          className={`inline-flex items-center gap-[4px] px-[8px] py-[2px] rounded-pill border text-[11px] font-medium ${statusBadgeColor(job)}`}
        >
          {statusIcon(job)}
          {statusLabel(job)}
        </span>
        {job.lastError && (
          <span
            className="text-[11px] text-status-danger truncate max-w-[180px]"
            title={job.lastError}
          >
            {job.lastError}
          </span>
        )}
      </div>

      {/* Rate */}
      <div className="text-content-secondary tabular-nums">
        {fmtRate(job.itemsPerSecond)}
      </div>

      {/* ETA */}
      <div className="text-content-primary font-medium tabular-nums">
        {fmtETA(job.etaSeconds)}
      </div>

      {/* Last activity */}
      <div className="text-content-tertiary text-[11px]">
        {fmtRel(job.lastProgressAt)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PerScopeJobs() {
  const [entityFilter, setEntityFilter] = useState<EntityFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  // Backend supports filter params but we filter client-side too for
  // instant UI feedback (no extra request) and because we need all rows
  // for the count summary.
  const { data: jobs, isLoading, isError, error } = usePipelineJobs({ limit: 200 });

  const filtered = useMemo(() => {
    if (!jobs) return [];
    return jobs.filter((j) => {
      if (entityFilter !== 'all' && j.entityType !== entityFilter) return false;
      if (statusFilter !== 'all' && j.status !== statusFilter) return false;
      return true;
    });
  }, [jobs, entityFilter, statusFilter]);

  const counts = useMemo(() => {
    if (!jobs) return { running: 0, done: 0, failed: 0, stalled: 0, total: 0 };
    return jobs.reduce(
      (acc, j) => {
        acc.total += 1;
        if (j.isStalled) acc.stalled += 1;
        else if (j.status === 'running') acc.running += 1;
        else if (j.status === 'done') acc.done += 1;
        else if (j.status === 'failed') acc.failed += 1;
        return acc;
      },
      { running: 0, done: 0, failed: 0, stalled: 0, total: 0 },
    );
  }, [jobs]);

  if (isLoading) return <Skeleton />;
  if (isError) {
    return <ErrorState message={error instanceof Error ? error.message : undefined} />;
  }
  if (!jobs || jobs.length === 0) return <EmptyState />;

  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card overflow-hidden">
      {/* Header with summary + filters */}
      <div className="flex items-center justify-between p-[14px_20px] border-b border-border-default flex-wrap gap-[12px]">
        <div className="flex items-center gap-[16px] flex-wrap">
          <h2 className="text-[15px] font-semibold text-content-primary">
            Per-scope ingestion progress
          </h2>
          <div className="flex items-center gap-[10px] text-[12px]">
            {counts.running > 0 && (
              <span className="inline-flex items-center gap-[4px] text-status-info">
                <Loader2 size={11} className="animate-spin motion-reduce:animate-none" />
                <span className="font-medium tabular-nums">{counts.running}</span>{' '}
                running
              </span>
            )}
            {counts.stalled > 0 && (
              <span className="inline-flex items-center gap-[4px] text-status-warning">
                <AlertCircle size={11} />
                <span className="font-medium tabular-nums">{counts.stalled}</span>{' '}
                stalled
              </span>
            )}
            {counts.done > 0 && (
              <span className="inline-flex items-center gap-[4px] text-status-success">
                <CheckCircle2 size={11} />
                <span className="font-medium tabular-nums">{counts.done}</span>{' '}
                done
              </span>
            )}
            {counts.failed > 0 && (
              <span className="inline-flex items-center gap-[4px] text-status-danger">
                <XCircle size={11} />
                <span className="font-medium tabular-nums">{counts.failed}</span>{' '}
                failed
              </span>
            )}
          </div>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-[8px]">
          <Filter size={14} className="text-content-tertiary" />
          <select
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value as EntityFilter)}
            className="text-[12px] px-[10px] py-[5px] rounded-pill border border-border-default bg-surface-primary text-content-primary cursor-pointer focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:outline-none"
            aria-label="Filter by entity type"
          >
            {ENTITY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="text-[12px] px-[10px] py-[5px] rounded-pill border border-border-default bg-surface-primary text-content-primary cursor-pointer focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:outline-none"
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[2fr_1fr_140px_1.5fr_80px_90px_120px] gap-[12px] px-[20px] py-[8px] bg-surface-secondary text-[11px] font-semibold uppercase tracking-wide text-content-tertiary border-b border-border-default">
        <div>Scope</div>
        <div>Entity</div>
        <div>Progress</div>
        <div>Status</div>
        <div>Rate</div>
        <div>ETA</div>
        <div>Last activity</div>
      </div>

      {/* Rows */}
      {filtered.length === 0 ? (
        <div className="p-[40px] text-center text-content-secondary text-[13px]">
          No jobs match the current filters.
        </div>
      ) : (
        <div>
          {filtered.map((j) => (
            <JobRow key={`${j.entityType}-${j.scopeKey}`} job={j} />
          ))}
        </div>
      )}

      {/* Footer */}
      <div className="p-[10px_20px] text-[11px] text-content-tertiary border-t border-border-default bg-surface-secondary">
        Polling every 5 seconds. Stalled = running with no progress for &gt;60s.
      </div>
    </div>
  );
}
