import { PlugZap, Unplug } from 'lucide-react';
import { Badge } from './shared/Badge';
import { SourceIcon } from './shared/SourceIcon';
import { getStatusConfig } from './shared/status';
import { usePipelineIntegrations } from '@/hooks/usePipeline';
import type { Integration } from '@/types/pipeline';

function IntegrationCard({ ig }: { ig: Integration }) {
  const cfg = getStatusConfig(ig.status);
  const colorHex = getStatusHex(ig.status);

  return (
    <div
      className={`flex items-center gap-[11px] py-[10px] px-[14px] rounded-button relative transition-all duration-200
        ${ig.connected
          ? `border-[1.5px] opacity-100 ${cfg.bg}`
          : 'border-[1.5px] border-border-default bg-surface-secondary opacity-50'
        }
        flex-[1_1_170px] min-w-[170px] max-w-[260px]`}
      style={ig.connected ? { borderColor: `${colorHex}35` } : undefined}
    >
      {/* Icon box */}
      <div
        className={`w-[36px] h-[36px] rounded-[9px] flex items-center justify-center shrink-0
          ${ig.connected
            ? 'bg-surface-primary'
            : 'bg-surface-tertiary'
          }
          border-[1.5px]`}
        style={{
          borderColor: ig.connected ? `${colorHex}30` : undefined,
        }}
      >
        <SourceIcon
          id={ig.id}
          size={18}
          className={ig.connected ? cfg.color : 'text-content-tertiary'}
        />
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-[5px]">
          <span
            className={`text-[13px] font-semibold ${ig.connected ? 'text-content-primary' : 'text-content-tertiary'}`}
          >
            {ig.name}
          </span>
          {ig.connected ? (
            <PlugZap size={12} className={cfg.color} />
          ) : (
            <Unplug size={12} className="text-content-tertiary" />
          )}
        </div>
        <div
          className={`text-[10px] mt-[2px] overflow-hidden text-ellipsis whitespace-nowrap ${ig.connected ? 'text-content-secondary' : 'text-content-tertiary'}`}
        >
          {ig.detail}
        </div>
      </div>

      {/* Status badge */}
      {ig.connected && (
        <div className="absolute top-[5px] right-[7px]">
          <Badge status={ig.status} size="xs" showLabel={false} />
        </div>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card py-[16px] px-[20px] mb-[16px]">
      <div className="h-[13px] w-[180px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none mb-[14px]" />
      <div className="flex gap-[10px] flex-wrap">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="flex-[1_1_170px] min-w-[170px] max-w-[260px] h-[56px] rounded-button bg-surface-tertiary animate-pulse motion-reduce:animate-none"
          />
        ))}
      </div>
    </div>
  );
}

export function IntegrationBox() {
  const { data: integrations, isLoading } = usePipelineIntegrations();

  if (isLoading || !integrations) return <Skeleton />;

  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card py-[16px] px-[20px] mb-[16px]">
      <div className="text-[11px] font-semibold text-content-secondary uppercase tracking-[0.05em] mb-[14px] flex items-center gap-[6px]">
        <PlugZap size={13} className="text-brand-primary" />
        Integracoes configuradas
      </div>
      <div className="flex gap-[10px] flex-wrap">
        {integrations.map((ig) => (
          <IntegrationCard key={ig.id} ig={ig} />
        ))}
      </div>
    </div>
  );
}

/** Resolve hex color for dynamic inline border-color values */
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
