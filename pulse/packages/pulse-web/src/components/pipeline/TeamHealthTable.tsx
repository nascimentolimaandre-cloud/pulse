import { useState, useMemo } from 'react';
import { Users } from 'lucide-react';
import { Badge } from './shared/Badge';
import { SourceIcon } from './shared/SourceIcon';
import { getStatusConfig } from './shared/status';
import { fmt, fmtD, pct, rel } from './shared/format';
import { usePipelineTeams } from '@/hooks/usePipeline';

type SortKey = 'health' | 'lag' | 'link';

const HEALTH_ORDER: Record<string, number> = {
  error: 0,
  degraded: 1,
  backfilling: 2,
  slow: 3,
  running: 4,
  healthy: 5,
  idle: 6,
};

const SORT_OPTIONS: Array<{ key: SortKey; label: string }> = [
  { key: 'health', label: 'Saude' },
  { key: 'lag', label: 'Lag' },
  { key: 'link', label: 'Link rate' },
];

function lagColor(sec: number): string {
  if (sec > 1800) return 'text-status-danger';
  if (sec > 600) return 'text-status-warning';
  return 'text-content-secondary';
}

function linkColor(rate: number): string {
  if (rate < 0.15) return 'text-status-danger';
  if (rate < 0.25) return 'text-status-warning';
  return 'text-status-success';
}

function Skeleton() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card overflow-hidden">
      <div className="p-[14px_20px] border-b border-border-default">
        <div className="h-[20px] w-[200px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none" />
      </div>
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className="h-[44px] mx-[20px] border-b border-border-default bg-surface-tertiary/30 animate-pulse motion-reduce:animate-none"
        />
      ))}
    </div>
  );
}

export function TeamHealthTable() {
  const [sort, setSort] = useState<SortKey>('health');
  const { data: teams, isLoading } = usePipelineTeams();

  const sorted = useMemo(() => {
    if (!teams) return [];
    return [...teams].sort((a, b) => {
      if (sort === 'health')
        return (HEALTH_ORDER[a.health] ?? 9) - (HEALTH_ORDER[b.health] ?? 9);
      if (sort === 'lag') return b.lagSec - a.lagSec;
      if (sort === 'link') return a.linkRate - b.linkRate;
      return 0;
    });
  }, [teams, sort]);

  if (isLoading || !teams) return <Skeleton />;

  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card overflow-hidden">
      {/* Title bar */}
      <div className="py-[14px] px-[20px] border-b border-border-default flex items-center justify-between">
        <div className="flex items-center gap-[8px]">
          <Users size={16} className="text-brand-primary" />
          <span className="text-[14px] font-semibold">Saude por time</span>
          <span className="text-[12px] text-content-tertiary">
            {teams.length} squads
          </span>
        </div>
        <div className="flex gap-[4px]">
          {SORT_OPTIONS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSort(s.key)}
              className={`py-[3px] px-[10px] rounded-badge text-[11px] font-medium cursor-pointer border transition-colors
                ${sort === s.key
                  ? 'border-brand-primary bg-brand-primary/[0.06] text-brand-primary'
                  : 'border-border-default bg-transparent text-content-secondary hover:border-content-tertiary'
                }
                focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:outline-none`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Header */}
      <div
        className="grid items-center py-[7px] px-[20px] border-b border-border-default bg-surface-secondary gap-[6px]"
        style={{
          gridTemplateColumns:
            '180px 64px 100px 1fr 72px 72px 60px 68px 72px 72px',
        }}
      >
        {[
          'TIME',
          '',
          'TRIBO',
          'FONTES',
          'PRs',
          'ISSUES',
          'DEPLOYS',
          'LINK',
          'LAG',
          'SYNC',
        ].map((h, i) => (
          <span
            key={i}
            className={`text-[10px] font-semibold text-content-tertiary uppercase tracking-[0.04em] ${i > 3 ? 'text-right' : 'text-left'}`}
          >
            {h}
          </span>
        ))}
      </div>

      {/* Rows */}
      {sorted.map((t) => {
        const cfg = getStatusConfig(t.health);
        const isHighlighted = t.health === 'degraded' || t.health === 'error';

        return (
          <div
            key={t.id}
            className={`grid items-center py-[9px] px-[20px] border-b border-border-default gap-[6px] transition-colors duration-150
              ${isHighlighted ? cfg.bg : 'hover:bg-surface-secondary'}`}
            style={{
              gridTemplateColumns:
                '180px 64px 100px 1fr 72px 72px 60px 68px 72px 72px',
            }}
          >
            {/* Team name */}
            <div className="flex items-center gap-[7px] overflow-hidden">
              <div
                className={`w-[26px] h-[26px] rounded-[6px] ${cfg.bg} flex items-center justify-center shrink-0 border`}
                style={{
                  borderColor: `${getStatusHex(t.health)}15`,
                }}
              >
                <Users size={13} className={cfg.color} />
              </div>
              <span className="text-[13px] font-semibold text-content-primary overflow-hidden text-ellipsis whitespace-nowrap">
                {t.name}
              </span>
            </div>

            {/* Badge */}
            <div className="flex justify-center">
              <Badge status={t.health} size="xs" showLabel={false} />
            </div>

            {/* Tribe */}
            <span className="text-[11px] text-content-secondary overflow-hidden text-ellipsis whitespace-nowrap">
              {t.tribe ?? '\u2014'}
            </span>

            {/* Sources */}
            <div className="flex gap-[10px] text-[11px] text-content-secondary">
              <span className="flex items-center gap-[2px]">
                <SourceIcon id="github" size={11} className="text-content-tertiary" />
                {t.repos}
              </span>
              <span className="flex items-center gap-[2px]">
                <SourceIcon id="jira" size={11} className="text-content-tertiary" />
                {t.jiraProjects.length}
              </span>
              <span className="flex items-center gap-[2px]">
                <SourceIcon id="jenkins" size={11} className="text-content-tertiary" />
                {t.jenkinsJobs}
              </span>
            </div>

            {/* PRs */}
            <span className="text-right text-[12px] font-mono text-content-secondary">
              {fmt(t.prCount)}
            </span>

            {/* Issues */}
            <span className="text-right text-[12px] font-mono text-content-secondary">
              {fmt(t.issueCount)}
            </span>

            {/* Deploys */}
            <span className="text-right text-[12px] font-mono text-content-secondary">
              {fmt(t.deployCount)}
            </span>

            {/* Link rate */}
            <span
              className={`text-right text-[12px] font-mono font-semibold ${linkColor(t.linkRate)}`}
            >
              {pct(t.linkRate)}
            </span>

            {/* Lag */}
            <span
              className={`text-right text-[12px] font-mono font-medium ${lagColor(t.lagSec)}`}
            >
              {fmtD(t.lagSec)}
            </span>

            {/* Sync */}
            <span className="text-right text-[10px] font-mono text-content-tertiary">
              {rel(t.lastSync)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function getStatusHex(status: string): string {
  const map: Record<string, string> = {
    healthy: '#10B981',
    backfilling: '#3B82F6',
    degraded: '#F59E0B',
    error: '#EF4444',
    idle: '#D1D5DB',
  };
  return map[status] ?? '#D1D5DB';
}
