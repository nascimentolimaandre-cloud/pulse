import { useState } from 'react';
import {
  Cable,
  Search,
  RefreshCw,
  Database,
  Calculator,
  ArrowRight,
  ChevronDown,
  Workflow,
} from 'lucide-react';
import { SourceIcon } from './shared/SourceIcon';
import { getStatusConfig } from './shared/status';
import { usePipelineSources, usePipelineIntegrations } from '@/hooks/usePipeline';
import type { LucideIcon } from 'lucide-react';

interface PhaseConfig {
  id: string;
  label: string;
  sub: string;
  icon: LucideIcon;
}

const PHASES: PhaseConfig[] = [
  { id: 'sources', label: 'Sources', sub: 'APIs externas', icon: Cable },
  { id: 'discovery', label: 'Discovery', sub: 'Catalog + PII', icon: Search },
  { id: 'sync', label: 'Sync Worker', sub: 'Fetch \u2192 Upsert', icon: RefreshCw },
  { id: 'storage', label: 'PULSE DB', sub: 'Postgres + Kafka', icon: Database },
  { id: 'metrics', label: 'Metrics', sub: 'DORA / Lean / Sprint', icon: Calculator },
];

function StatusDot({ status }: { status: string }) {
  const cfg = getStatusConfig(status);
  const Icon = cfg.icon;
  return (
    <Icon
      size={13}
      className={`${cfg.color} ${cfg.spin ? 'animate-spin motion-reduce:animate-none' : ''}`}
    />
  );
}

function MiniStepBars({ steps }: { steps: Array<{ n: string; s: string; p: number }> }) {
  return (
    <div className="flex gap-[2px] mt-[1px]">
      {steps.map((s) => (
        <div
          key={s.n}
          title={`${s.n}: ${s.p}%`}
          className="w-[14px] h-[3px] rounded-[2px] bg-surface-tertiary overflow-hidden"
        >
          <div
            className={`h-full rounded-[2px] ${stepBarColor(s.s)}`}
            style={{ width: `${s.p}%` }}
          />
        </div>
      ))}
    </div>
  );
}

export function PipelinePhaseView() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: integrations } = usePipelineIntegrations();
  const { data: sources } = usePipelineSources();

  const connected = integrations?.filter((i) => i.connected) ?? [];

  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card py-[18px] px-[20px] mb-[16px]">
      <div className="text-[11px] font-semibold text-content-secondary uppercase tracking-[0.05em] mb-[16px] flex items-center gap-[6px]">
        <Workflow size={14} className="text-brand-primary" />
        Pipeline -- Source &#x2192; Metrica calculada
      </div>

      {/* Phase header row */}
      <div className="flex items-stretch pl-[96px] mb-[6px]">
        {PHASES.map((ph, i) => (
          <div key={ph.id} className="flex-1 flex items-center">
            <div className="flex-1 text-center">
              <div className="inline-flex flex-col items-center gap-[3px] py-[8px] px-[6px] rounded-button bg-surface-secondary border border-border-default min-w-[90px]">
                <ph.icon size={16} className="text-brand-primary" />
                <span className="text-[11px] font-semibold text-content-primary">
                  {ph.label}
                </span>
                <span className="text-[9px] text-content-tertiary">{ph.sub}</span>
              </div>
            </div>
            {i < PHASES.length - 1 && (
              <ArrowRight
                size={14}
                className="text-border-default shrink-0 -mx-[3px]"
              />
            )}
          </div>
        ))}
      </div>

      {/* Source rows */}
      {connected.map((ig) => {
        const source = sources?.find((s) => s.id === ig.id);
        if (!source) return null;
        const isOpen = expanded === ig.id;

        // Build phase cells from source data
        const phaseCells = buildPhaseCells(source);

        return (
          <div key={ig.id} className="border-t border-border-default">
            <button
              onClick={() => setExpanded(isOpen ? null : ig.id)}
              className="w-full flex items-center py-[10px] bg-transparent border-none cursor-pointer text-left"
            >
              {/* Source label */}
              <div className="w-[96px] flex items-center gap-[7px] shrink-0">
                <SourceIcon id={ig.id} size={15} />
                <span className="text-[13px] font-semibold text-content-primary">
                  {ig.name}
                </span>
              </div>

              {/* Phase cells */}
              {phaseCells.map((cell, i) => {
                const cfg = getStatusConfig(cell.status);
                const spin =
                  cell.status === 'running' || cell.status === 'backfilling';
                return (
                  <div key={cell.phase} className="flex-1 flex items-center">
                    <div
                      className={`flex-1 flex flex-col items-center gap-[2px] py-[7px] px-[4px] rounded-[6px] mx-[2px] transition-all duration-200
                        ${spin ? cfg.bg : 'bg-transparent'}
                        ${cell.status !== 'healthy' && cell.status !== 'idle' && cell.status !== 'done' ? `border ${cfg.border}` : 'border border-transparent'}`}
                    >
                      <StatusDot status={cell.status} />
                      <span className="text-[10px] text-content-secondary text-center leading-[1.3] max-w-[100px] overflow-hidden text-ellipsis whitespace-nowrap">
                        {cell.line1}
                      </span>
                      {cell.line2 && (
                        <span className={`text-[9px] font-mono font-medium ${cfg.text}`}>
                          {cell.line2}
                        </span>
                      )}
                      {cell.steps && <MiniStepBars steps={cell.steps} />}
                    </div>
                    {i < phaseCells.length - 1 && (
                      <div className="w-[10px] flex justify-center shrink-0">
                        <div
                          className="w-[6px] h-[1.5px] rounded-[1px]"
                          style={{
                            backgroundColor: `${getStatusHex(cell.status)}30`,
                          }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}

              <ChevronDown
                size={14}
                className={`text-content-tertiary shrink-0 ml-[4px] transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
              />
            </button>

            {/* Expanded detail */}
            {isOpen && (
              <div className="ml-[96px] py-[4px] pb-[16px] flex gap-[4px]">
                {phaseCells.map((cell) => {
                  const cfg = getStatusConfig(cell.status);
                  const phaseLabel = PHASES.find((p) => p.id === cell.phase)?.label;
                  return (
                    <div
                      key={cell.phase}
                      className="flex-1 py-[10px] px-[10px] rounded-[6px] bg-surface-secondary border border-border-default mx-[2px]"
                    >
                      <div className="text-[12px] font-semibold text-content-primary mb-[4px]">
                        {phaseLabel}
                      </div>
                      <div className="text-[11px] text-content-secondary mb-[2px]">
                        {cell.line1}
                      </div>
                      {cell.line2 && (
                        <div className={`text-[10px] font-mono ${cfg.text}`}>
                          {cell.line2}
                        </div>
                      )}
                      {cell.steps && (
                        <div className="mt-[6px] flex flex-col gap-[3px]">
                          {cell.steps.map((ss) => {
                            const sc = getStatusConfig(ss.s);
                            const SIcon = sc.icon;
                            return (
                              <div
                                key={ss.n}
                                className="flex items-center gap-[4px]"
                              >
                                <SIcon
                                  size={10}
                                  className={`${sc.color} shrink-0 ${ss.s === 'running' ? 'animate-spin motion-reduce:animate-none' : ''}`}
                                />
                                <span className="w-[56px] text-[10px] font-medium">
                                  {ss.n}
                                </span>
                                <div className="flex-1 h-[4px] rounded-[2px] bg-surface-tertiary overflow-hidden">
                                  <div
                                    className={`h-full rounded-[2px] ${stepBarColor(ss.s)}`}
                                    style={{ width: `${ss.p}%` }}
                                  />
                                </div>
                                <span className="text-[10px] font-mono min-w-[26px]">
                                  {ss.p}%
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface PhaseCell {
  phase: string;
  status: string;
  line1: string;
  line2: string;
  steps?: Array<{ n: string; s: string; p: number }>;
}

function buildPhaseCells(source: {
  id: string;
  status: string;
  connections: number;
  entities: Array<{
    type: string;
    status: string;
    steps?: Array<{
      name: string;
      status: string;
      processed: number;
      total: number;
    }>;
  }>;
}): PhaseCell[] {
  // Simplified: derive phase status from source/entity data
  const hasBackfill = source.entities.some(
    (e) => e.status === 'backfilling' || e.status === 'running'
  );
  const hasError = source.entities.some(
    (e) => e.status === 'error' || e.status === 'degraded'
  );

  const syncEntity = source.entities.find((e) => e.steps);
  const syncSteps = syncEntity?.steps?.map((s) => ({
    n: s.name.charAt(0).toUpperCase() + s.name.slice(1),
    s: s.status,
    p: s.total ? Math.round((s.processed / s.total) * 100) : 100,
  }));

  return [
    {
      phase: 'sources',
      status: source.status === 'error' ? 'error' : 'healthy',
      line1: `${source.connections} conexoes`,
      line2: '',
    },
    {
      phase: 'discovery',
      status: 'healthy',
      line1: `${source.connections} catalogados`,
      line2: '',
    },
    {
      phase: 'sync',
      status: hasBackfill ? 'backfilling' : hasError ? 'degraded' : 'healthy',
      line1: hasBackfill ? 'Em andamento' : hasError ? 'Com alertas' : 'OK',
      line2: '',
      steps: syncSteps,
    },
    {
      phase: 'storage',
      status: hasBackfill ? 'backfilling' : hasError ? 'degraded' : 'healthy',
      line1: hasBackfill ? 'Gravando...' : 'Atualizado',
      line2: '',
    },
    {
      phase: 'metrics',
      status: hasBackfill ? 'pending' : 'healthy',
      line1: hasBackfill ? 'Aguardando sync' : 'Atualizado',
      line2: '',
    },
  ];
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
