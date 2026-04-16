import { useState } from 'react';
import {
  ChevronDown,
  ChevronUp,
  ChevronRight,
  AlertCircle,
  Clock,
} from 'lucide-react';
import { Badge } from './shared/Badge';
import { SourceIcon } from './shared/SourceIcon';
import { RateBar } from './shared/RateBar';
import { getStatusConfig } from './shared/status';
import { fmt, fmtD, fmtE, rel } from './shared/format';
import type { Source, Entity, Step } from '@/types/pipeline';

interface SourceCardProps {
  source: Source;
  onEntity?: (source: Source, entity: Entity) => void;
}

function StepRow({ step }: { step: Step }) {
  const cfg = getStatusConfig(step.status);
  const Icon = cfg.icon;
  const p = step.total ? Math.round((step.processed / step.total) * 100) : 100;
  const spin = step.status === 'running';

  return (
    <div className="flex items-center gap-[6px] text-[12px]">
      <Icon
        size={13}
        className={`${cfg.color} shrink-0 ${spin ? 'animate-spin motion-reduce:animate-none' : ''}`}
      />
      <span className="font-medium capitalize min-w-[72px]">{step.name}</span>
      <div className="flex-1 h-[5px] rounded-[3px] bg-surface-tertiary overflow-hidden min-w-[50px]">
        <div
          className={`h-full rounded-[3px] ${statusBarColor(step.status)} transition-[width] duration-400`}
          style={{ width: `${p}%` }}
        />
      </div>
      <span className="font-mono text-[11px] text-content-secondary min-w-[76px] text-right">
        {fmt(step.processed)}/{fmt(step.total)}
      </span>
      {step.etaSec != null && step.etaSec > 0 && (
        <span className={`font-mono text-[11px] font-medium ${cfg.color}`}>
          {fmtE(step.etaSec)}
        </span>
      )}
    </div>
  );
}

function EntityRow({
  source,
  entity,
  onEntity,
}: {
  source: Source;
  entity: Entity;
  onEntity?: (source: Source, entity: Entity) => void;
}) {
  const cfg = getStatusConfig(entity.status);
  const isHighlighted = entity.status === 'degraded' || entity.status === 'error';

  return (
    <div>
      <div
        onClick={() => onEntity?.(source, entity)}
        className={`flex items-center gap-[10px] py-[9px] px-[12px] rounded-button cursor-pointer transition-colors duration-150
          ${isHighlighted ? cfg.bg : 'hover:bg-surface-secondary'}`}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && onEntity?.(source, entity)}
      >
        <Badge status={entity.status} size="xs" showLabel={false} />
        <span className="text-[13px] font-medium min-w-[90px]">{entity.label}</span>

        {entity.lastCycleRecords != null && !entity.steps && (
          <span className="text-[12px] font-mono text-content-secondary">
            {fmt(entity.lastCycleRecords)} rec &middot; {fmtD(entity.lastCycleDurationSec)}
          </span>
        )}

        {entity.error && entity.status === 'degraded' && (
          <span className="text-[11px] text-status-warningText flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
            {entity.error}
          </span>
        )}

        <span className="text-[11px] font-mono text-content-tertiary ml-auto">
          {rel(entity.watermark)}
        </span>
        <ChevronRight size={14} className="text-content-tertiary shrink-0" />
      </div>

      {entity.steps && (
        <div className="py-[5px] px-[12px] pl-[38px] flex flex-col gap-[4px]">
          {entity.steps.map((st) => (
            <StepRow key={st.name} step={st} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SourceCard({ source, onEntity }: SourceCardProps) {
  const cfg = getStatusConfig(source.status);
  const autoExpand =
    source.status === 'backfilling' ||
    source.status === 'error' ||
    source.status === 'degraded';
  const [open, setOpen] = useState(autoExpand);

  const hasCriticalError = source.entities.some(
    (e) => e.error && e.status === 'error'
  );
  const criticalError = source.entities.find(
    (e) => e.error && e.status === 'error'
  );

  const connectionLabel =
    source.id === 'jira' ? 'projetos' : source.id === 'github' ? 'repos' : 'jobs';

  return (
    <div
      className={`rounded-card border shadow-card overflow-hidden
        ${source.status === 'degraded' || source.status === 'error'
          ? `${source.status === 'error' ? cfg.bg : ''}`
          : 'bg-surface-primary'
        }`}
      style={{
        borderColor:
          source.status === 'degraded' || source.status === 'error'
            ? `${getStatusHex(source.status)}40`
            : undefined,
      }}
    >
      {/* Header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-[12px] py-[13px] px-[18px] bg-transparent border-none cursor-pointer text-left"
      >
        {/* Icon */}
        <div
          className={`w-[36px] h-[36px] rounded-[9px] ${cfg.bg} flex items-center justify-center shrink-0 border-[1.5px]`}
          style={{ borderColor: `${getStatusHex(source.status)}25` }}
        >
          <SourceIcon id={source.id} size={18} className={cfg.color} />
        </div>

        {/* Info */}
        <div className="flex-1">
          <div className="flex items-center gap-[8px]">
            <span className="text-[15px] font-semibold">{source.name}</span>
            <Badge status={source.status} size="sm" />
            <span className="text-[12px] text-content-secondary">
              {source.connections} {connectionLabel}
            </span>
          </div>
          <div className="flex items-center gap-[14px] mt-[3px]">
            <span className="text-[11px] font-mono text-content-tertiary">
              <Clock size={10} className="inline mr-[3px] align-middle" />
              {rel(source.watermark)}
            </span>
            <RateBar value={source.rateLimitPct} compact />
          </div>
        </div>

        {open ? (
          <ChevronUp size={16} className="text-content-secondary" />
        ) : (
          <ChevronDown size={16} className="text-content-secondary" />
        )}
      </button>

      {/* Error banner */}
      {hasCriticalError && criticalError && (
        <div className="mx-[18px] mb-[10px] py-[9px] px-[12px] rounded-button bg-status-dangerBg border border-status-danger/[0.15] flex items-start gap-[8px] text-[13px] text-status-dangerText">
          <AlertCircle size={15} className="mt-[1px] shrink-0" />
          {criticalError.error}
        </div>
      )}

      {/* Entities */}
      {open && (
        <div className="px-[18px] pb-[12px] flex flex-col gap-[2px]">
          {source.entities.map((ent) => (
            <EntityRow
              key={ent.type}
              source={source}
              entity={ent}
              onEntity={onEntity}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function getStatusHex(status: string): string {
  const map: Record<string, string> = {
    healthy: '#10B981',
    backfilling: '#3B82F6',
    running: '#3B82F6',
    degraded: '#F59E0B',
    error: '#EF4444',
    slow: '#F59E0B',
    idle: '#D1D5DB',
    disabled: '#D1D5DB',
    done: '#10B981',
    pending: '#F59E0B',
  };
  return map[status] ?? '#D1D5DB';
}

function statusBarColor(status: string): string {
  const map: Record<string, string> = {
    done: 'bg-status-success',
    healthy: 'bg-status-success',
    running: 'bg-status-info',
    backfilling: 'bg-status-info',
    degraded: 'bg-status-warning',
    error: 'bg-status-danger',
    pending: 'bg-status-warning',
    idle: 'bg-status-idle',
  };
  return map[status] ?? 'bg-status-idle';
}
