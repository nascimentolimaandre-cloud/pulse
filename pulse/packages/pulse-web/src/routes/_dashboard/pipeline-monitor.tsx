import { createRoute } from '@tanstack/react-router';
import { rootRoute } from '../__root';
import {
  usePipelineStatus,
  useSourceFilteredStatus,
  useMetricsWorkerStatus,
} from '@/hooks/useMetrics';
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Cloud,
  Database,
  GitBranch,
  GitPullRequest,
  Bug,
  Rocket,
  Zap,
  Loader2,
  RefreshCw,
  Waves,
  TrendingUp,
  TrendingDown,
  ArrowLeft,
  Filter,
  Activity,
  Timer,
  Cpu,
  Server,
  Send,
  Terminal,
  Gauge,
  Heart,
} from 'lucide-react';
import type {
  PipelineOverallStatus,
  PipelineStageStatus,
  PipelineStage,
  PipelineKpis,
  RecordCount,
  PipelineError,
  PipelineEvent,
  SourceConnection,
  SourceFilteredStatus,
  MetricsWorkerStatus,
  MetricsWorkerSnapshot,
} from '@/types/pipeline';

export const pipelineMonitorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/pipeline-monitor',
  component: PipelineMonitorPage,
});

/* ════════════════════════════════════════════
   Utility helpers
   ════════════════════════════════════════════ */

function formatRelativeTime(isoString: string): string {
  const diff = Math.max(0, Math.floor((Date.now() - new Date(isoString).getTime()) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatNumber(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return n.toLocaleString();
}

function formatNumberFull(n: number): string {
  return n.toLocaleString();
}

/* ════════════════════════════════════════════
   Freshness hook — ticks every second
   ════════════════════════════════════════════ */

function useFreshness(lastUpdated: string | undefined) {
  const [label, setLabel] = useState('');
  const lastUpdatedRef = useRef(lastUpdated);
  lastUpdatedRef.current = lastUpdated;

  useEffect(() => {
    function tick() {
      if (!lastUpdatedRef.current) { setLabel(''); return; }
      setLabel(formatRelativeTime(lastUpdatedRef.current));
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [lastUpdated]);

  return label;
}

/* ════════════════════════════════════════════
   View state: main | filtered | metrics-worker
   ════════════════════════════════════════════ */

type ViewMode = 'main' | 'filtered' | 'metrics-worker';

/* ════════════════════════════════════════════
   Status & icon config
   ════════════════════════════════════════════ */

const OVERALL_STATUS_CONFIG: Record<
  PipelineOverallStatus,
  { dotClass: string; label: string; textClass: string; bgClass: string }
> = {
  healthy: { dotClass: 'bg-emerald-500', label: 'Healthy', textClass: 'text-emerald-700', bgClass: 'bg-emerald-100' },
  syncing: { dotClass: 'bg-blue-500 animate-pulse', label: 'Syncing', textClass: 'text-blue-700', bgClass: 'bg-blue-100' },
  degraded: { dotClass: 'bg-amber-500', label: 'Degraded', textClass: 'text-amber-700', bgClass: 'bg-amber-100' },
  error: { dotClass: 'bg-red-500', label: 'Error', textClass: 'text-red-700', bgClass: 'bg-red-100' },
};

const STAGE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  sources: Cloud,
  devlake: Waves,
  sync_worker: RefreshCw,
  pulse_db: Database,
  metrics_worker: BarChart3,
};

const ENTITY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  pull_requests: GitPullRequest,
  issues: Bug,
  deployments: Rocket,
  sprints: Zap,
  commits: GitBranch,
  users: Activity,
  comments: Terminal,
};

const ENTITY_LABELS: Record<string, string> = {
  pull_requests: 'Pull Requests',
  issues: 'Issues',
  deployments: 'Deployments',
  sprints: 'Sprints',
  commits: 'Commits',
  users: 'Users',
  comments: 'Comments',
};

const SOURCE_ICONS: Record<string, string> = {
  github: 'https://cdn.simpleicons.org/github/181717',
  jira: 'https://cdn.simpleicons.org/jira/0052CC',
  jenkins: 'https://cdn.simpleicons.org/jenkins/D24939',
  bitbucket: 'https://cdn.simpleicons.org/bitbucket/0052CC',
  gitlab: 'https://cdn.simpleicons.org/gitlab/FC6D26',
};

const SEVERITY_COLORS: Record<string, { dot: string; text: string }> = {
  success: { dot: 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]', text: 'text-emerald-700' },
  info: { dot: 'bg-indigo-400', text: 'text-indigo-700' },
  warning: { dot: 'bg-amber-400', text: 'text-amber-700' },
  error: { dot: 'bg-red-400', text: 'text-red-700' },
};

/* ════════════════════════════════════════════
   Skeleton
   ════════════════════════════════════════════ */

function PageSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="h-8 w-52 animate-pulse rounded-lg bg-gray-100" />
        <div className="h-5 w-32 animate-pulse rounded-lg bg-gray-100" />
      </div>
      <div className="flex items-center gap-6 py-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex flex-col items-center gap-2">
            <div className="h-12 w-12 animate-pulse rounded-full bg-gray-100" />
            <div className="h-3 w-10 animate-pulse rounded bg-gray-100" />
          </div>
        ))}
      </div>
      <div className="h-40 animate-pulse rounded-xl bg-gray-50" />
      <div className="grid grid-cols-4 gap-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-xl bg-gray-50" />
        ))}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════
   A) Page Header (MVP-1.7.9)
   ════════════════════════════════════════════ */

function PageHeader({
  overallStatus,
  lastUpdated,
  isFetching,
}: {
  overallStatus: PipelineOverallStatus;
  lastUpdated: string;
  isFetching: boolean;
}) {
  const freshness = useFreshness(lastUpdated);
  const cfg = OVERALL_STATUS_CONFIG[overallStatus];

  return (
    <header className="flex items-end justify-between py-2">
      <div>
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-2xl font-bold tracking-tight text-content-primary">
            Pipeline Monitor
          </h1>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold ${cfg.textClass} ${cfg.bgClass}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${cfg.dotClass}`} />
            {cfg.label}
          </span>
        </div>
        <p className="text-sm text-content-secondary">
          Real-time data ingestion status across engineering clusters
        </p>
      </div>
      <div className="flex items-center gap-3 text-xs text-content-tertiary">
        {isFetching && (
          <span className="flex items-center gap-1 text-brand-primary">
            <Loader2 className="h-3 w-3 animate-spin" />
            Refreshing...
          </span>
        )}
        {freshness && (
          <div className="flex items-center gap-1.5 rounded-lg bg-gray-50 px-3 py-1.5 font-mono">
            <Clock className="h-3 w-3" />
            Updated {freshness}
          </div>
        )}
      </div>
    </header>
  );
}

/* ════════════════════════════════════════════
   B) Source Connection Filter Bar (MVP-1.7.14)
   ════════════════════════════════════════════ */

function SourceFilterBar({
  connections,
  activeSource,
  onSelectSource,
}: {
  connections: SourceConnection[];
  activeSource: string | null;
  onSelectSource: (source: string | null) => void;
}) {
  return (
    <section className="flex items-center gap-6 py-4 px-2 overflow-x-auto">
      {/* Show All button */}
      <div className="flex flex-col items-center gap-2">
        <button
          onClick={() => onSelectSource(null)}
          className={`h-12 w-12 rounded-full flex items-center justify-center border-2 transition-all
            ${!activeSource
              ? 'border-brand-primary bg-brand-light text-brand-primary'
              : 'border-gray-200 bg-white text-content-secondary hover:border-brand-primary/50'
            }`}
        >
          <Filter className="h-5 w-5" />
        </button>
        <span className={`text-[10px] font-bold uppercase tracking-tighter ${!activeSource ? 'text-brand-primary' : 'text-content-tertiary'}`}>
          Show All
        </span>
      </div>

      <div className="h-8 w-px bg-gray-200" />

      {/* Source icons */}
      <div className="flex items-center gap-8">
        {connections.map((conn) => {
          const isActive = conn.active;
          const isSelected = activeSource === conn.type;
          const isSyncing = conn.syncing;

          return (
            <div
              key={conn.type}
              className={`flex flex-col items-center gap-2 relative cursor-pointer group transition-all
                ${!isActive && !isSelected ? 'opacity-40 grayscale hover:opacity-70 hover:grayscale-0' : ''}`}
              onClick={() => isActive ? onSelectSource(isSelected ? null : conn.type) : undefined}
            >
              <div className="relative">
                {/* Pulse ring for syncing sources */}
                {isSyncing && (
                  <div className="absolute inset-0 rounded-full bg-brand-primary/20 animate-pulse-ring" />
                )}
                <div className={`h-12 w-12 rounded-full bg-white shadow-sm flex items-center justify-center relative z-10 transition-transform group-hover:scale-105 active:scale-95
                  ${isSelected ? 'ring-2 ring-brand-primary ring-offset-2' : 'border border-gray-100'}`}
                >
                  <img
                    src={SOURCE_ICONS[conn.type] || ''}
                    alt={conn.label}
                    className="h-6 w-6"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                  {isActive && (
                    <div className="absolute top-0 right-0 h-3 w-3 rounded-full bg-emerald-500 border-2 border-white" />
                  )}
                </div>
              </div>
              <span className="text-[10px] font-bold uppercase tracking-tighter text-content-secondary">
                {conn.label.split(' ')[0]}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* ════════════════════════════════════════════
   C) Pipeline Flow Diagram — Animated (MVP-1.7.5)
   ════════════════════════════════════════════ */

function PipelineFlowDiagram({
  stages,
  onClickMetrics,
}: {
  stages: PipelineStage[];
  onClickMetrics: () => void;
}) {
  const anySyncing = stages.some((s) => s.status === 'syncing');

  return (
    <section className="relative rounded-xl bg-[var(--pipeline-surface-low)] p-8 overflow-hidden">
      {/* Background connector line */}
      <div className="absolute inset-x-12 top-1/2 -translate-y-1/2 h-1 z-0">
        <div className="w-full h-1 rounded-full bg-emerald-200/30 relative overflow-hidden">
          {anySyncing && (
            <div className="absolute inset-0 animate-data-flow opacity-50" />
          )}
        </div>
      </div>

      {/* Nodes */}
      <div className="grid grid-cols-5 gap-4 items-center relative">
        {stages.map((stage) => {
          const Icon = STAGE_ICONS[stage.name] ?? Cloud;
          const isSyncing = stage.status === 'syncing';
          const isMetrics = stage.name === 'metrics_worker';
          const isPulseDb = stage.name === 'pulse_db';
          const statusLabel = stage.status.charAt(0).toUpperCase() + stage.status.slice(1);

          const statusColor =
            stage.status === 'healthy' || stage.status === 'standby'
              ? 'text-emerald-600'
              : stage.status === 'syncing'
                ? 'text-blue-600'
                : stage.status === 'error'
                  ? 'text-red-600'
                  : 'text-content-tertiary';

          return (
            <div
              key={stage.name}
              className={`relative z-10 flex flex-col items-center ${isMetrics ? 'cursor-pointer' : ''}`}
              onClick={isMetrics ? onClickMetrics : undefined}
            >
              <div
                className={`h-14 w-14 rounded-xl flex items-center justify-center mb-3 transition-all
                  ${isSyncing
                    ? 'pulse-gradient shadow-lg animate-node-glow'
                    : isPulseDb
                      ? 'bg-white shadow-md ring-1 ring-brand-primary/20'
                      : 'bg-white shadow-sm'
                  }`}
              >
                <Icon
                  className={`h-6 w-6 ${
                    isSyncing ? 'text-white animate-spin' : 'text-brand-primary'
                  }`}
                />
              </div>
              <p className="text-xs font-bold uppercase tracking-wider text-content-secondary mb-1">
                {stage.label}
              </p>
              <div className="flex flex-col items-center">
                <span className={`text-[10px] font-bold mb-1 ${statusColor}`}>
                  {statusLabel.toUpperCase()}
                </span>
                {stage.detail && (
                  <span className="font-mono text-sm font-semibold text-content-primary">
                    {stage.detail}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/* ════════════════════════════════════════════
   D) KPI Counter Strip (MVP-1.7.6a)
   ════════════════════════════════════════════ */

function KpiStrip({ kpis }: { kpis: PipelineKpis }) {
  const hasTrend = kpis.total_records_trend !== null && kpis.total_records_trend !== undefined;
  const trendUp = hasTrend && kpis.total_records_trend! > 0;
  const hasErrors = kpis.errors_24h > 0;
  const hasPending = kpis.pending_sync > 0;

  return (
    <section className="grid grid-cols-4 gap-6">
      {/* Total Records */}
      <div className="bg-white p-5 rounded-xl ghost-border">
        <p className="text-xs font-bold uppercase tracking-widest text-content-secondary mb-1">
          Total Records
        </p>
        <h3 className="text-3xl font-mono font-bold text-content-primary">
          {formatNumberFull(kpis.total_records)}
        </h3>
        {hasTrend && (
          <div className={`mt-4 flex items-center gap-1 text-xs font-bold ${trendUp ? 'text-emerald-600' : 'text-red-600'}`}>
            {trendUp ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
            {trendUp ? '+' : ''}{kpis.total_records_trend}% vs last week
          </div>
        )}
      </div>

      {/* Synced Today */}
      <div className="bg-white p-5 rounded-xl ghost-border">
        <p className="text-xs font-bold uppercase tracking-widest text-content-secondary mb-1">
          Synced Today
        </p>
        <h3 className="text-3xl font-mono font-bold text-content-primary">
          {formatNumberFull(kpis.synced_today)}
        </h3>
        <div className="mt-4 flex items-center gap-1 text-xs font-bold text-emerald-600">
          <TrendingUp className="h-3.5 w-3.5" />
          +4.2% daily avg
        </div>
      </div>

      {/* Pending Sync */}
      <div className="bg-white p-5 rounded-xl ghost-border">
        <p className="text-xs font-bold uppercase tracking-widest text-content-secondary mb-1">
          Pending Sync
        </p>
        <h3 className="text-3xl font-mono font-bold text-content-primary">
          {formatNumberFull(kpis.pending_sync)}
        </h3>
        {hasPending && (
          <div className="mt-4 flex items-center gap-1 text-xs text-content-secondary font-medium">
            <Timer className="h-3.5 w-3.5" />
            Est. {Math.ceil(kpis.pending_sync / 100 * 42)}s left
          </div>
        )}
      </div>

      {/* Errors 24h */}
      <div className={`p-5 rounded-xl ${hasErrors ? 'bg-white ring-1 ring-red-200/50' : 'bg-white ghost-border'}`}>
        <p className={`text-xs font-bold uppercase tracking-widest mb-1 ${hasErrors ? 'text-red-600' : 'text-content-secondary'}`}>
          Errors (24h)
        </p>
        <h3 className={`text-3xl font-mono font-bold ${hasErrors ? 'text-red-600' : 'text-content-primary'}`}>
          {kpis.errors_24h}
        </h3>
        {hasErrors && (
          <div className="mt-4 flex items-center gap-1 text-xs font-bold text-red-600">
            <AlertCircle className="h-3.5 w-3.5" />
            Critical attention
          </div>
        )}
      </div>
    </section>
  );
}

/* ════════════════════════════════════════════
   E) Details Area — Accordions + Timeline (Tela 1)
   ════════════════════════════════════════════ */

function AccordionSection({
  title,
  statusColor = 'bg-emerald-500',
  defaultOpen = false,
  children,
}: {
  title: string;
  statusColor?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="bg-white rounded-xl ghost-border overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className={`h-2 w-2 rounded-full ${statusColor}`} />
          <span className="font-bold text-sm tracking-tight text-content-primary">{title}</span>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-content-tertiary" /> : <ChevronDown className="h-4 w-4 text-content-tertiary" />}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

function DevLakeSyncTable({ syncs }: { syncs: Array<{ id: string; status: string; started_at: string; records_processed: Record<string, number> }> }) {
  if (syncs.length === 0) {
    return <p className="text-sm text-content-tertiary py-4 text-center">No recent sync cycles recorded.</p>;
  }

  return (
    <table className="w-full text-left">
      <thead>
        <tr className="text-[10px] font-bold uppercase tracking-widest text-content-secondary">
          <th className="pb-3 pt-2">Sync ID</th>
          <th className="pb-3 pt-2">Progress</th>
          <th className="pb-3 pt-2">Status</th>
          <th className="pb-3 pt-2">Last Sync</th>
        </tr>
      </thead>
      <tbody className="text-sm font-mono">
        {syncs.slice(0, 5).map((sync) => {
          const total = Object.values(sync.records_processed).reduce((a, b) => a + b, 0);
          const statusColors: Record<string, string> = {
            completed: 'bg-emerald-50 text-emerald-600',
            running: 'bg-indigo-50 text-indigo-600',
            failed: 'bg-red-50 text-red-600',
            partial: 'bg-amber-50 text-amber-600',
          };
          const statusClass = statusColors[sync.status] || 'bg-gray-50 text-gray-600';
          const progress = sync.status === 'completed' ? 100 : sync.status === 'running' ? 65 : 0;

          return (
            <tr key={sync.id} className="border-t border-gray-50">
              <td className="py-3 text-xs">{sync.id.slice(0, 8)}...</td>
              <td className="py-3 pr-8">
                <div className="w-full bg-gray-100 h-1.5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${sync.status === 'completed' ? 'bg-emerald-500' : 'bg-brand-primary'}`}
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </td>
              <td className="py-3">
                <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${statusClass}`}>
                  {sync.status.toUpperCase()}
                </span>
              </td>
              <td className="py-3 text-content-secondary text-xs">
                {formatRelativeTime(sync.started_at)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SyncWorkerLogs({ events }: { events: PipelineEvent[] }) {
  const logEvents = events.filter((e) => e.source !== 'metrics_worker').slice(0, 5);

  return (
    <div className="bg-[var(--pipeline-inverse)] text-gray-100 p-3 rounded-lg font-mono text-[11px] space-y-1 max-h-32 overflow-y-auto">
      {logEvents.length === 0 ? (
        <p className="text-gray-400 py-2">No recent log entries.</p>
      ) : (
        logEvents.map((ev, i) => (
          <p key={ev.id || i}>
            <span className="text-emerald-400">[{new Date(ev.occurred_at).toLocaleTimeString()}]</span>
            {' '}
            <span className="text-gray-400">{ev.severity.toUpperCase()}:</span>
            {' '}
            {ev.title}
            {ev.detail && <span className="text-gray-500"> — {ev.detail}</span>}
          </p>
        ))
      )}
      <span className="inline-block w-2 h-3 bg-emerald-400 animate-cursor-blink" />
    </div>
  );
}

/* ════════════════════════════════════════════
   F) Recent Activity Timeline (MVP-1.7.15)
   ════════════════════════════════════════════ */

function RecentActivityTimeline({ events }: { events: PipelineEvent[] }) {
  const timelineEvents = events.slice(0, 6);

  return (
    <div className="bg-white p-6 rounded-xl ghost-border">
      <h4 className="text-sm font-bold uppercase tracking-widest text-content-secondary mb-6">
        Recent Activity
      </h4>
      <div className="space-y-6 relative">
        {/* Vertical line */}
        <div className="absolute left-[7px] top-2 bottom-2 w-px bg-gray-100" />

        {timelineEvents.length === 0 ? (
          <p className="text-sm text-content-tertiary pl-8">No recent activity.</p>
        ) : (
          timelineEvents.map((ev, i) => {
            const sev = SEVERITY_COLORS[ev.severity] || SEVERITY_COLORS.info;
            const borderColor =
              ev.severity === 'success' ? 'border-emerald-500'
              : ev.severity === 'error' ? 'border-red-500'
              : ev.severity === 'warning' ? 'border-amber-500'
              : 'border-indigo-500';

            return (
              <div key={ev.id || i} className="flex items-start gap-4 relative">
                <div className={`h-4 w-4 rounded-full bg-white border-4 ${borderColor} z-10 shrink-0`} />
                <div className="min-w-0">
                  <p className="text-sm font-bold text-content-primary truncate">{ev.title}</p>
                  {ev.detail && (
                    <p className={`text-xs font-mono mt-1 ${sev.text} truncate`}>{ev.detail}</p>
                  )}
                  <span className="text-[10px] font-bold text-content-tertiary uppercase mt-2 block">
                    {formatRelativeTime(ev.occurred_at)}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════
   G) Performance Alert Card (MVP-1.7.21)
   ════════════════════════════════════════════ */

function PerformanceAlertCard({ kpis }: { kpis: PipelineKpis }) {
  const showAlert = kpis.pending_sync > 100 || kpis.errors_24h > 3;
  if (!showAlert) return null;

  return (
    <div className="pulse-gradient p-6 rounded-xl text-white">
      <h4 className="text-sm font-bold mb-2">Performance Alert</h4>
      <p className="text-xs opacity-90 leading-relaxed mb-4">
        {kpis.pending_sync > 100
          ? `Throughput is under pressure — ${formatNumberFull(kpis.pending_sync)} records pending sync.`
          : `${kpis.errors_24h} errors detected in the last 24 hours. System resources may need attention.`}
      </p>
      <button
        className="w-full bg-white text-brand-primary font-bold py-2 rounded-lg text-xs hover:bg-gray-50 transition-colors"
        onClick={() => {
          document.getElementById('error-panel')?.scrollIntoView({ behavior: 'smooth' });
        }}
      >
        View Resource Map
      </button>
    </div>
  );
}

/* ════════════════════════════════════════════
   H) Record Counts by Entity Grid (MVP-1.7.6b)
   ════════════════════════════════════════════ */

function RecordCountsGrid({ records }: { records: RecordCount[] }) {
  if (records.length === 0) return null;

  return (
    <div className="bg-white p-6 rounded-xl ghost-border">
      <div className="flex items-center justify-between mb-6">
        <h4 className="text-sm font-bold uppercase tracking-widest text-content-secondary">
          Record Counts by Entity
        </h4>
        <button className="text-brand-primary text-xs font-bold flex items-center gap-1">
          View Detailed Report
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </button>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {records.map((rec) => {
          const label = ENTITY_LABELS[rec.entity] ?? rec.entity;
          return (
            <div key={rec.entity} className="p-3 bg-gray-50 rounded-lg border border-gray-100">
              <p className="text-[10px] font-bold text-content-tertiary uppercase">{label}</p>
              <p className="text-lg font-mono font-bold text-content-primary">
                {formatNumberFull(rec.pulse_count)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════
   I) Error Panel (MVP-1.7.7)
   ════════════════════════════════════════════ */

function ErrorPanel({ errors }: { errors: PipelineError[] }) {
  const hasErrors = errors.length > 0;
  const [expanded, setExpanded] = useState(hasErrors);
  const [acknowledged, setAcknowledged] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (hasErrors) setExpanded(true);
  }, [hasErrors]);

  const handleAcknowledge = useCallback((index: number) => {
    setAcknowledged((prev) => new Set(prev).add(index));
  }, []);

  return (
    <div className={`rounded-xl overflow-hidden ${hasErrors ? 'bg-red-50/30 border-2 border-red-200/30' : 'bg-white ghost-border'}`}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className={`w-full flex items-center justify-between p-4 ${hasErrors ? 'bg-red-100 text-red-800' : 'hover:bg-gray-50'}`}
      >
        <div className="flex items-center gap-3">
          {hasErrors ? (
            <AlertTriangle className="h-5 w-5" />
          ) : (
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
          )}
          <span className="font-bold text-sm">Active Error Reports ({errors.length})</span>
        </div>
        {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>

      {expanded && (
        <div className="p-4 space-y-3">
          {errors.length === 0 ? (
            <p className="py-4 text-center text-sm text-content-tertiary">
              No active errors. All pipeline stages are operating normally.
            </p>
          ) : (
            errors.map((err, index) => {
              const isAck = acknowledged.has(index);
              return (
                <div
                  key={`${err.timestamp}-${err.stage}-${index}`}
                  className={`flex items-center justify-between bg-white/50 p-3 rounded-lg border border-red-100/50 ${isAck ? 'opacity-40' : ''}`}
                >
                  <div className="flex items-center gap-4">
                    {err.error_code && (
                      <span className="font-mono text-xs font-bold text-red-600">{err.error_code}</span>
                    )}
                    <span className="text-xs font-medium text-content-primary">{err.message}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleAcknowledge(index)}
                      disabled={isAck}
                      className="text-[10px] font-bold uppercase tracking-wider text-content-secondary bg-gray-200 px-2 py-1 rounded disabled:opacity-40"
                    >
                      {isAck ? 'Ignored' : 'Ignore'}
                    </button>
                    <button className="text-[10px] font-bold uppercase tracking-wider text-red-600 bg-red-100 px-2 py-1 rounded">
                      Retry
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   TELA 1 — MAIN VIEW  (combines all components above)
   ════════════════════════════════════════════════════════════════════════════ */

function MainView({
  data,
  isFetching,
  activeSource,
  onSelectSource,
  onOpenMetricsWorker,
}: {
  data: NonNullable<ReturnType<typeof usePipelineStatus>['data']>;
  isFetching: boolean;
  activeSource: string | null;
  onSelectSource: (source: string | null) => void;
  onOpenMetricsWorker: () => void;
}) {
  return (
    <div className="space-y-6">
      <PageHeader
        overallStatus={data.overall_status}
        lastUpdated={data.last_updated}
        isFetching={isFetching}
      />

      <SourceFilterBar
        connections={data.source_connections}
        activeSource={activeSource}
        onSelectSource={onSelectSource}
      />

      <PipelineFlowDiagram
        stages={data.stages}
        onClickMetrics={onOpenMetricsWorker}
      />

      <KpiStrip kpis={data.kpis} />

      {/* Two-column layout: Accordions + Timeline */}
      <section className="grid grid-cols-12 gap-6">
        <div className="col-span-8 space-y-4">
          <AccordionSection title="DevLake Sync Progress" defaultOpen>
            <DevLakeSyncTable syncs={data.recent_syncs} />
          </AccordionSection>

          <AccordionSection title="Sync Worker Logs">
            <SyncWorkerLogs events={data.recent_events} />
          </AccordionSection>

          <AccordionSection title="Metrics Calculator Stats">
            <div className="text-sm text-content-tertiary py-2">
              {data.kpis.total_records > 0
                ? `Processing ${formatNumberFull(data.kpis.total_records)} records across 4 metric categories.`
                : 'No metrics calculated yet.'}
            </div>
          </AccordionSection>
        </div>

        <div className="col-span-4 space-y-6">
          <RecentActivityTimeline events={data.recent_events} />
          <PerformanceAlertCard kpis={data.kpis} />
        </div>
      </section>

      <RecordCountsGrid records={data.record_counts} />

      <div id="error-panel">
        <ErrorPanel errors={data.recent_errors} />
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   TELA 2 — SOURCE FILTERED VIEW  (MVP-1.7.16, 1.7.17, 1.7.18)
   ════════════════════════════════════════════════════════════════════════════ */

function SourceFilteredView({
  sourceType,
  onBack,
}: {
  sourceType: string;
  onBack: () => void;
}) {
  const { data, isLoading } = useSourceFilteredStatus(sourceType);
  const sourceLabel = sourceType.charAt(0).toUpperCase() + sourceType.slice(1);

  if (isLoading || !data) {
    return <PageSkeleton />;
  }

  const kpis = data.kpis as Record<string, string | number>;

  return (
    <div className="space-y-6">
      {/* Header with back navigation */}
      <header className="flex items-center justify-between py-2">
        <div className="flex items-center gap-4">
          <button
            onClick={onBack}
            className="h-8 w-8 rounded-lg bg-gray-100 flex items-center justify-center hover:bg-gray-200 transition-colors"
          >
            <ArrowLeft className="h-4 w-4 text-content-secondary" />
          </button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-content-primary">
              Pipeline Monitor — {sourceLabel}
            </h1>
            <p className="text-sm text-content-secondary">
              Real-time status of the ingestion pipeline for {sourceLabel}.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <span className="px-3 py-1 rounded-full bg-emerald-100 text-emerald-700 text-[10px] font-bold uppercase tracking-wider">
            Health: {data.health_pct}%
          </span>
          <span className="px-3 py-1 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-bold uppercase tracking-wider">
            Mode: {data.sync_mode === 'delta' ? 'Delta Sync' : 'Full Sync'}
          </span>
        </div>
      </header>

      {/* Source filter bar (horizontal pills) */}
      <div className="flex items-center gap-4 overflow-x-auto pb-2">
        <button className="flex items-center gap-2 px-5 py-2.5 bg-white rounded-xl border-2 border-brand-primary text-brand-primary font-semibold text-sm shadow-sm whitespace-nowrap">
          <CheckCircle2 className="h-4 w-4" />
          {sourceLabel}
        </button>
        {['GitLab', 'Datadog', 'Jenkins'].map((name) => (
          <button
            key={name}
            className="flex items-center gap-2 px-5 py-2.5 bg-white rounded-xl border border-gray-200 text-content-secondary font-medium text-sm hover:bg-gray-50 transition-all whitespace-nowrap"
          >
            {name}
          </button>
        ))}
      </div>

      {/* Source-specific KPI cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {Object.entries(kpis).slice(0, 4).map(([key, value]) => {
          const label = key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
          return (
            <div key={key} className="bg-white p-6 rounded-xl ambient-shadow">
              <div className="flex justify-between items-start mb-4">
                <span className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary">{label}</span>
                <Database className="h-5 w-5 text-brand-primary" />
              </div>
              <span className="text-3xl font-bold text-content-primary">
                {typeof value === 'number' ? formatNumber(value) : String(value)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Pipeline flow filtered */}
      <div className="bg-white p-8 rounded-xl ambient-shadow relative overflow-hidden">
        <div className="flex justify-between items-center mb-10">
          <div>
            <h3 className="text-lg font-semibold text-content-primary">
              Live Data Flow: {sourceLabel} Integration
            </h3>
            <p className="text-sm text-content-secondary">
              Real-time status of the ingestion pipeline for {sourceLabel}.
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 relative">
          {data.stages.map((stage, idx) => (
            <div key={stage.name} className="flex items-center flex-1 gap-4">
              <div className="flex flex-col items-center gap-3 z-10">
                <div className={`h-16 w-16 rounded-2xl flex items-center justify-center border-2
                  ${stage.status === 'syncing' ? 'border-indigo-400 shadow-md bg-indigo-50' :
                    stage.name === 'pulse_db' ? 'border-brand-primary shadow-xl bg-[var(--pipeline-inverse)]' :
                    'border-indigo-200 bg-gray-50'}`}
                >
                  {(() => {
                    const Icon = STAGE_ICONS[stage.name] ?? Cloud;
                    return <Icon className={`h-7 w-7 ${stage.name === 'pulse_db' ? 'text-white' : 'text-brand-primary'}`} />;
                  })()}
                </div>
                <span className="text-xs font-bold font-mono text-content-primary">{stage.label}</span>
                <span className="text-[10px] text-content-tertiary">{stage.detail}</span>
              </div>
              {idx < data.stages.length - 1 && (
                <div className="flex-1 h-0.5 bg-indigo-100 relative min-w-[40px]">
                  {stage.status === 'syncing' && (
                    <div className="absolute inset-0 bg-brand-primary origin-left animate-pulse" style={{ transform: 'scaleX(0.75)' }} />
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Two-column: Active Board Syncs + Live Logs */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Active Board Syncs Table */}
        <div className="lg:col-span-2 bg-white p-6 rounded-xl ambient-shadow">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-base font-semibold text-content-primary">Active Board Syncs</h3>
            <button className="text-xs text-brand-primary font-bold hover:underline">View All Boards</button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-content-tertiary">Board Name</th>
                  <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-content-tertiary">Sync Strategy</th>
                  <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-content-tertiary">Progress</th>
                  <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-content-tertiary">Last SHA/Key</th>
                  <th className="pb-3 text-[10px] font-bold uppercase tracking-widest text-content-tertiary">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {(data.active_syncs || []).map((sync, i) => {
                  const statusColors: Record<string, string> = {
                    ACTIVE: 'bg-emerald-100 text-emerald-700',
                    IDLE: 'bg-emerald-100 text-emerald-700',
                    SYNCING: 'bg-amber-100 text-amber-700',
                    ERROR: 'bg-red-100 text-red-700',
                  };
                  const progressColor = sync.status === 'SYNCING' ? 'bg-amber-400' : sync.progress >= 100 ? 'bg-emerald-500' : 'bg-brand-primary';

                  return (
                    <tr key={i} className="hover:bg-gray-50 transition-colors">
                      <td className="py-4">
                        <div className="flex items-center gap-3">
                          <div className="h-8 w-8 rounded bg-blue-100 flex items-center justify-center">
                            <BarChart3 className="h-4 w-4 text-blue-600" />
                          </div>
                          <span className="text-sm font-semibold text-content-primary">{sync.name}</span>
                        </div>
                      </td>
                      <td className="py-4 text-xs font-mono text-content-tertiary">{sync.strategy}</td>
                      <td className="py-4">
                        <div className="w-24 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div className={`h-full ${progressColor}`} style={{ width: `${sync.progress}%` }} />
                        </div>
                      </td>
                      <td className="py-4 text-xs font-mono text-content-tertiary">{sync.last_key}</td>
                      <td className="py-4">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${statusColors[sync.status] || 'bg-gray-100 text-gray-600'}`}>
                          {sync.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Live Ingestion Logs */}
        <div className="bg-white p-6 rounded-xl ambient-shadow">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-base font-semibold text-content-primary">Live Ingestion Logs</h3>
            <Filter className="h-4 w-4 text-content-tertiary" />
          </div>
          <div className="space-y-6">
            {(data.recent_logs || []).slice(0, 5).map((log, i) => {
              const sev = SEVERITY_COLORS[log.severity] || SEVERITY_COLORS.info;
              return (
                <div key={log.id || i} className="flex gap-4">
                  <div className="mt-1">
                    <div className={`h-2 w-2 rounded-full ${sev.dot}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-content-primary truncate">{log.title}</p>
                    {log.detail && (
                      <p className="text-[11px] text-content-secondary mt-0.5 leading-relaxed line-clamp-2">{log.detail}</p>
                    )}
                    <span className="text-[10px] font-mono text-content-tertiary mt-2 block">
                      {new Date(log.occurred_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          <button className="w-full mt-6 py-2 border border-gray-200 rounded-lg text-[10px] font-bold uppercase tracking-widest text-content-secondary hover:bg-gray-50 transition-all">
            Open Terminal Logs
          </button>
        </div>
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   TELA 3 — METRICS WORKER DRILL-DOWN  (MVP-1.7.19, 1.7.20)
   ════════════════════════════════════════════════════════════════════════════ */

function MetricsWorkerView({ onBack }: { onBack: () => void }) {
  const { data, isLoading } = useMetricsWorkerStatus();

  if (isLoading || !data) {
    return <PageSkeleton />;
  }

  const kpis = data.kpis as Record<string, string | number>;

  const METRIC_COLORS: Record<string, string> = {
    DORA: 'bg-indigo-400',
    'Lean & Flow': 'bg-purple-400',
    'Cycle Time': 'bg-blue-400',
    Throughput: 'bg-orange-400',
    Sprint: 'bg-emerald-400',
  };

  const SNAPSHOT_STATUS_STYLES: Record<string, string> = {
    success: 'bg-emerald-100 text-emerald-700',
    calculating: 'bg-amber-100 text-amber-700 animate-pulse',
    idle: 'bg-gray-100 text-gray-500',
    error: 'bg-red-100 text-red-700',
  };

  const STAGE_ICONS_MW = [
    { name: 'Ingest', icon: Activity, active: true },
    { name: 'Metrics Worker', icon: BarChart3, active: true },
    { name: 'Persist', icon: Database, active: false },
    { name: 'Dispatch', icon: Send, active: false },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex items-end justify-between">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <button
              onClick={onBack}
              className="h-8 w-8 rounded-lg bg-gray-100 flex items-center justify-center hover:bg-gray-200 transition-colors"
            >
              <ArrowLeft className="h-4 w-4 text-content-secondary" />
            </button>
            <nav className="flex items-center gap-2 text-xs font-mono text-content-tertiary">
              <span>PIPELINES</span>
              <span className="text-[10px]">&gt;</span>
              <span className="text-brand-primary font-bold">PULSE-MONITOR-V2</span>
            </nav>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-content-primary">
            Metrics Worker Stage
          </h1>
        </div>
        <div className="flex gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 rounded-lg border border-gray-200">
            <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-medium text-content-secondary">Cluster: Oregon-1</span>
          </div>
        </div>
      </header>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white p-6 rounded-xl shadow-sm ghost-border">
          <p className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary mb-1">Processing Rate</p>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-content-primary">
              {kpis.processing_rate ?? '0'}
            </span>
            <span className="text-xs font-mono text-content-tertiary">req/s</span>
          </div>
          <div className="mt-4 h-1 w-full bg-gray-100 rounded-full overflow-hidden">
            <div className="h-full bg-brand-primary w-3/4" />
          </div>
        </div>
        <div className="bg-white p-6 rounded-xl shadow-sm ghost-border">
          <p className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary mb-1">Queue Latency</p>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-content-primary">
              {kpis.queue_latency ?? '0'}
            </span>
            <span className="text-xs font-mono text-content-tertiary">ms</span>
          </div>
          <div className="mt-4 flex items-center gap-1">
            <TrendingDown className="h-4 w-4 text-emerald-500" />
            <span className="text-[10px] text-emerald-600 font-bold">-12% from avg</span>
          </div>
        </div>
        <div className="bg-white p-6 rounded-xl shadow-sm ghost-border">
          <p className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary mb-1">Active Nodes</p>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-content-primary">
              {kpis.active_nodes ?? '1'}
            </span>
            <span className="text-xs font-mono text-content-tertiary">/ 24</span>
          </div>
          <div className="mt-4 flex -space-x-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-6 w-6 rounded-full border-2 border-white bg-gray-300" />
            ))}
            <div className="h-6 w-6 rounded-full border-2 border-white pulse-gradient text-[8px] flex items-center justify-center text-white font-bold">
              +{Math.max(0, Number(kpis.active_nodes || 1) - 3)}
            </div>
          </div>
        </div>
        <div className="bg-white p-6 rounded-xl shadow-sm ghost-border">
          <p className="text-[10px] font-bold uppercase tracking-widest text-content-tertiary mb-1">DORA Health</p>
          <span className="text-2xl font-bold text-emerald-600">
            {kpis.dora_health ?? 'Elite'}
          </span>
          <div className="mt-4 flex items-center gap-2">
            <Heart className="h-4 w-4 text-amber-500" />
            <span className="text-[10px] text-content-tertiary font-medium">Verified by Compliance</span>
          </div>
        </div>
      </div>

      {/* Stages Pipeline (simplified) */}
      <div className="bg-gray-50 p-6 rounded-xl flex items-center justify-between gap-8 overflow-x-auto ghost-border">
        {STAGE_ICONS_MW.map((st, idx) => {
          const Icon = st.icon;
          const isActive = st.name === 'Metrics Worker';
          return (
            <div key={st.name} className="flex items-center flex-1 gap-4">
              <div className="flex-shrink-0 flex flex-col items-center gap-2">
                <div className={`h-12 w-12 rounded-full flex items-center justify-center
                  ${isActive
                    ? 'pulse-gradient text-white ring-4 ring-brand-primary/20'
                    : st.active
                      ? 'bg-emerald-100 text-emerald-600'
                      : 'bg-gray-200 text-gray-400'
                  }`}
                >
                  <Icon className="h-5 w-5" />
                </div>
                <span className={`text-[10px] font-bold ${isActive ? 'text-brand-primary' : 'text-content-tertiary'}`}>
                  {st.name}
                </span>
              </div>
              {idx < STAGE_ICONS_MW.length - 1 && (
                <div className="flex-1 h-px bg-gray-200 relative">
                  {st.active && <div className="absolute inset-0 bg-brand-primary" />}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Snapshot Inspector Table */}
      <div className="bg-white rounded-xl shadow-sm ghost-border overflow-hidden">
        <div className="flex items-center justify-between p-5 bg-gradient-to-r from-brand-light to-transparent">
          <div className="flex items-center gap-4">
            <div className="p-2 bg-brand-primary/10 rounded-lg">
              <Cpu className="h-5 w-5 text-brand-primary" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-content-primary">Metrics Worker Details</h3>
              <p className="text-xs text-content-tertiary">Snapshot inspector</p>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] font-bold uppercase tracking-wider text-content-tertiary border-b border-gray-100">
                <th className="px-6 py-4">Snapshot ID</th>
                <th className="px-6 py-4">Metric Type</th>
                <th className="px-6 py-4">Timestamp</th>
                <th className="px-6 py-4">Duration</th>
                <th className="px-6 py-4">Records Processed</th>
                <th className="px-6 py-4 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {(data.snapshots || []).map((snap) => {
                const dotColor = METRIC_COLORS[snap.metric_type] || 'bg-gray-400';
                const statusStyle = SNAPSHOT_STATUS_STYLES[snap.status] || SNAPSHOT_STATUS_STYLES.idle;

                return (
                  <tr key={snap.snapshot_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4">
                      <span className="font-mono text-xs text-brand-primary font-medium">
                        {snap.snapshot_id.slice(0, 16)}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <span className={`h-2 w-2 rounded-full ${dotColor}`} />
                        <span className="text-sm font-medium text-content-primary">{snap.metric_type}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-xs text-content-tertiary font-mono">
                      {snap.timestamp
                        ? new Date(snap.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
                        : 'Pending...'}
                    </td>
                    <td className="px-6 py-4 text-xs text-content-primary">
                      {snap.duration_seconds ? `${snap.duration_seconds.toFixed(1)}s` : '--'}
                    </td>
                    <td className="px-6 py-4 text-xs font-medium text-content-primary">
                      {snap.records_processed > 0 ? formatNumberFull(snap.records_processed) : '--'}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold ${statusStyle}`}>
                        {snap.status.toUpperCase()}
                      </span>
                    </td>
                  </tr>
                );
              })}
              {(data.snapshots || []).length === 0 && (
                <tr>
                  <td colSpan={6} className="px-6 py-8 text-center text-sm text-content-tertiary">
                    No metric snapshots recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {(data.snapshots || []).length > 0 && (
          <div className="p-4 border-t border-gray-50 flex items-center justify-between text-[11px] font-medium text-content-tertiary">
            <p>Showing 1-{data.snapshots.length} metric snapshots</p>
            <div className="flex gap-2">
              <button className="px-3 py-1 bg-gray-50 rounded border border-gray-200 hover:bg-gray-100 transition-colors">Previous</button>
              <button className="px-3 py-1 pulse-gradient text-white rounded shadow-sm">1</button>
              <button className="px-3 py-1 bg-gray-50 rounded border border-gray-200 hover:bg-gray-100 transition-colors">Next</button>
            </div>
          </div>
        )}
      </div>

      {/* Global Cluster Logs */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-bold uppercase tracking-widest text-content-tertiary">
            Global Cluster Logs
          </h2>
          <div className="px-2 py-1 rounded bg-[var(--pipeline-inverse)] text-[10px] font-mono text-emerald-400">
            tail -f system.log
          </div>
        </div>
        <div className="bg-[var(--pipeline-inverse)] rounded-xl overflow-hidden p-4 shadow-xl">
          <div className="font-mono text-xs space-y-1.5 max-h-40 overflow-y-auto">
            {(data.cluster_logs || []).length === 0 ? (
              <p className="text-gray-500">No cluster logs available.</p>
            ) : (
              data.cluster_logs.map((log, i) => {
                const levelColor =
                  log.level === 'INFO' ? 'text-emerald-400'
                  : log.level === 'DEBUG' ? 'text-blue-400'
                  : log.level === 'WARNING' ? 'text-amber-400'
                  : log.level === 'ERROR' ? 'text-red-400'
                  : 'text-gray-400';

                return (
                  <div key={i} className="flex gap-4">
                    <span className="text-gray-500 shrink-0">
                      [{new Date(log.timestamp).toLocaleTimeString()}]
                    </span>
                    <span className={levelColor}>{log.level}</span>
                    <span className="text-gray-300">{log.message}</span>
                  </div>
                );
              })
            )}
            <span className="inline-block w-2 h-3 bg-emerald-400 animate-cursor-blink" />
          </div>
        </div>
      </section>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   ROOT PAGE — View Router
   ════════════════════════════════════════════════════════════════════════════ */

function PipelineMonitorPage() {
  const [viewMode, setViewMode] = useState<ViewMode>('main');
  const [activeSource, setActiveSource] = useState<string | null>(null);

  const { data, isLoading, isError, error, isFetching } = usePipelineStatus();

  // When user selects a source from the filter bar, switch view
  const handleSelectSource = useCallback((source: string | null) => {
    setActiveSource(source);
    if (source) {
      setViewMode('filtered');
    } else {
      setViewMode('main');
    }
  }, []);

  const handleOpenMetricsWorker = useCallback(() => {
    setViewMode('metrics-worker');
  }, []);

  const handleBackToMain = useCallback(() => {
    setViewMode('main');
    setActiveSource(null);
  }, []);

  // Error state
  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">
          Failed to load pipeline status
        </h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'An unexpected error occurred.'}
        </p>
      </div>
    );
  }

  // Loading state
  if (isLoading || !data) {
    return <PageSkeleton />;
  }

  // Route to the correct view
  switch (viewMode) {
    case 'filtered':
      return (
        <SourceFilteredView
          sourceType={activeSource!}
          onBack={handleBackToMain}
        />
      );
    case 'metrics-worker':
      return <MetricsWorkerView onBack={handleBackToMain} />;
    default:
      return (
        <MainView
          data={data}
          isFetching={isFetching}
          activeSource={activeSource}
          onSelectSource={handleSelectSource}
          onOpenMetricsWorker={handleOpenMetricsWorker}
        />
      );
  }
}
