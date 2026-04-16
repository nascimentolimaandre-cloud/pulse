import { useEffect, useRef, useCallback } from 'react';
import { X, AlertCircle, RotateCcw } from 'lucide-react';
import { Badge } from './shared/Badge';
import { SourceIcon } from './shared/SourceIcon';
import { RateBar } from './shared/RateBar';
import { getStatusConfig } from './shared/status';
import { fmt, fmtD, fmtE, rel } from './shared/format';
import type { Source, Entity, Step } from '@/types/pipeline';

/**
 * Feature flag for retry button.
 * Currently OFF — will be enabled when RBAC + internal queue retry is ready.
 * See: docs/backlog.md — "Pipeline retry (data_platform role)"
 */
const FEATURE_RETRY = false;

interface EntityDrawerProps {
  source: Source;
  entity: Entity;
  onClose: () => void;
}

function buildSteps(entity: Entity): Step[] {
  if (entity.steps) return entity.steps;
  const rec = entity.lastCycleRecords ?? 0;
  const dur = entity.lastCycleDurationSec ?? 0;
  return [
    { name: 'fetch', status: 'done', processed: rec, total: rec, durationSec: dur * 0.5 },
    { name: 'normalize', status: 'done', processed: rec, total: rec, durationSec: dur * 0.3 },
    { name: 'upsert', status: 'done', processed: rec, total: rec, durationSec: dur * 0.2 },
  ];
}

function rateLimitDetail(sourceId: string, pct: number): string {
  if (sourceId === 'github') return `${Math.round(pct * 5000)} / 5.000 req/h`;
  if (sourceId === 'jira') return `${Math.round(pct * 100)} / 100 req/min`;
  return `${Math.round(pct * 60)} / 60 req/min`;
}

export function EntityDrawer({ source, entity, onClose }: EntityDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const steps = buildSteps(entity);
  const totalD = steps.reduce((s, st) => s + (st.durationSec ?? 0), 0);
  const cfg = getStatusConfig(entity.status);

  // Focus trap + Esc handler
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'Tab' && drawerRef.current) {
        const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
          'button, [tabindex]:not([tabindex="-1"]), a[href], input, select, textarea'
        );
        if (focusable.length === 0) return;
        const first = focusable[0] as HTMLElement | undefined;
        const last = focusable[focusable.length - 1] as HTMLElement | undefined;
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [onClose]
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    // Focus first focusable element
    const timer = setTimeout(() => {
      const firstBtn = drawerRef.current?.querySelector<HTMLElement>('button');
      firstBtn?.focus();
    }, 50);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      clearTimeout(timer);
    };
  }, [handleKeyDown]);

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/[0.12] z-[999]"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-label={`${source.name} -- ${entity.label}`}
        className="fixed top-0 right-0 bottom-0 w-full sm:w-[520px] sm:max-w-[92vw] bg-surface-primary shadow-[-8px_0_24px_rgba(0,0,0,0.12)] z-[1000] flex flex-col overflow-y-auto"
      >
        {/* Header (sticky) */}
        <div className="py-[14px] px-[20px] border-b border-border-default flex items-center gap-[10px] sticky top-0 bg-surface-primary z-[1]">
          <div
            className={`w-[30px] h-[30px] rounded-button ${cfg.bg} flex items-center justify-center`}
          >
            <SourceIcon id={source.id} size={15} className={cfg.color} />
          </div>
          <div className="flex-1">
            <div className="text-[15px] font-semibold">
              {source.name} -- {entity.label}
            </div>
            <div className="text-[11px] font-mono text-content-secondary">
              Watermark:{' '}
              {entity.watermark
                ? new Date(entity.watermark).toLocaleString('pt-BR', {
                    timeZone: 'America/Sao_Paulo',
                  })
                : '\u2014'}{' '}
              ({rel(entity.watermark)})
            </div>
          </div>
          <Badge status={entity.status} size="sm" />
          <button
            onClick={onClose}
            className="bg-transparent border-none cursor-pointer p-[4px] focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:outline-none rounded"
            aria-label="Fechar"
          >
            <X size={18} className="text-content-secondary" />
          </button>
        </div>

        {/* Error banner */}
        {entity.error && (
          <div className="mx-[20px] mt-[14px] py-[10px] px-[12px] rounded-button bg-status-dangerBg border border-status-danger/[0.15] text-[13px] text-status-dangerText flex gap-[8px]">
            <AlertCircle size={15} className="shrink-0 mt-[1px]" />
            {entity.error}
          </div>
        )}

        {/* Steps */}
        <div className="p-[20px]">
          <div className="text-[11px] font-semibold text-content-secondary uppercase tracking-[0.04em] mb-[10px]">
            Etapas do pipeline
          </div>
          <div className="flex flex-col gap-[10px]">
            {steps.map((st) => {
              const sc = getStatusConfig(st.status);
              const SIcon = sc.icon;
              const p = st.total
                ? Math.round((st.processed / st.total) * 100)
                : 100;
              const spin = st.status === 'running';

              return (
                <div
                  key={st.name}
                  className={`py-[11px] px-[14px] rounded-button border
                    ${spin ? `${sc.bg} ${sc.border}` : 'bg-surface-secondary border-border-default'}`}
                >
                  {/* Step header */}
                  <div className="flex justify-between items-center mb-[6px]">
                    <div className="flex items-center gap-[6px]">
                      <SIcon
                        size={14}
                        className={`${sc.color} ${spin ? 'animate-spin motion-reduce:animate-none' : ''}`}
                      />
                      <span className="font-semibold text-[13px] capitalize">
                        {st.name}
                      </span>
                      <Badge status={st.status} size="xs" />
                    </div>
                    {st.throughputPerSec != null && (
                      <span className="text-[11px] font-mono text-content-secondary">
                        {st.throughputPerSec} rec/s
                      </span>
                    )}
                  </div>

                  {/* Progress bar */}
                  <div className="flex items-center gap-[8px] mb-[4px]">
                    <div className="flex-1 h-[7px] rounded-[4px] bg-surface-tertiary overflow-hidden">
                      <div
                        className={`h-full rounded-[4px] ${stepBarColor(st.status)} transition-[width] duration-500`}
                        style={{ width: `${p}%` }}
                      />
                    </div>
                    <span
                      className={`font-mono text-[12px] font-semibold ${sc.color} min-w-[34px]`}
                    >
                      {p}%
                    </span>
                  </div>

                  {/* Counts + ETA */}
                  <div className="flex justify-between text-[11px] text-content-secondary font-mono">
                    <span>
                      {fmt(st.processed)} / {fmt(st.total)}
                    </span>
                    {st.etaSec != null && st.etaSec > 0 ? (
                      <span className={`${sc.color} font-medium`}>
                        ETA {fmtE(st.etaSec)}
                      </span>
                    ) : st.durationSec != null && st.durationSec > 0 ? (
                      <span>{fmtD(st.durationSec)}</span>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Duration stacked bar */}
        {totalD > 0 && (
          <div className="px-[20px] pb-[20px]">
            <div className="text-[11px] font-semibold text-content-secondary uppercase tracking-[0.04em] mb-[8px]">
              Duracao por etapa
            </div>
            <div className="flex h-[22px] rounded-[6px] overflow-hidden bg-surface-tertiary">
              {steps.map((st) => {
                const w = ((st.durationSec ?? 0) / totalD) * 100;
                if (w <= 0) return null;
                return (
                  <div
                    key={st.name}
                    title={`${st.name}: ${fmtD(st.durationSec)}`}
                    className="flex items-center justify-center text-[9px] font-semibold text-white capitalize"
                    style={{
                      width: `${w}%`,
                      backgroundColor: `${getStepHex(st.status)}CC`,
                    }}
                  >
                    {w > 14 ? st.name : ''}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Rate limit */}
        <div className="px-[20px] pb-[20px]">
          <div className="text-[11px] font-semibold text-content-secondary uppercase tracking-[0.04em] mb-[8px]">
            Rate limit ({source.name})
          </div>
          <RateBar value={source.rateLimitPct} />
          <div className="text-[11px] text-content-tertiary mt-[4px]">
            {rateLimitDetail(source.id, source.rateLimitPct)}
          </div>
        </div>

        {/* Retry button (feature-flagged OFF) */}
        {FEATURE_RETRY && (
          <div className="px-[20px] pb-[20px] border-t border-border-default pt-[14px]">
            <button className="flex items-center gap-[6px] py-[8px] px-[14px] rounded-button border border-border-default bg-surface-primary cursor-pointer text-[13px] font-medium text-content-secondary hover:bg-surface-secondary focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:outline-none">
              <RotateCcw size={14} />
              Retry failed items
            </button>
            <span className="text-[10px] text-content-tertiary mt-[4px] block">
              Visivel apenas para Data Platform role
            </span>
          </div>
        )}
      </div>
    </>
  );
}

function stepBarColor(status: string): string {
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

function getStepHex(status: string): string {
  const map: Record<string, string> = {
    done: '#10B981',
    healthy: '#10B981',
    running: '#3B82F6',
    backfilling: '#3B82F6',
    degraded: '#F59E0B',
    error: '#EF4444',
    pending: '#F59E0B',
    idle: '#D1D5DB',
  };
  return map[status] ?? '#D1D5DB';
}
