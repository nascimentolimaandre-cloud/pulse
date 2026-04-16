import { RefreshCw, Link2, Rocket, Clock } from 'lucide-react';
import { Badge } from './shared/Badge';
import { fmt, fmtD, pct, rel } from './shared/format';
import type { PipelineHealthResponse } from '@/types/pipeline';

interface TrustStripProps {
  health?: PipelineHealthResponse;
  isLoading?: boolean;
}

function Divider() {
  return <div className="w-px h-[22px] bg-border-default" />;
}

function Skeleton() {
  return (
    <div className="flex items-center gap-[14px] py-[12px] px-[18px] rounded-card bg-surface-primary border border-border-default shadow-card mb-[16px] flex-wrap">
      <div className="h-[36px] w-[120px] rounded-badge bg-surface-tertiary animate-pulse motion-reduce:animate-none" />
      <div className="flex gap-[18px] flex-1 flex-wrap items-center">
        {[160, 140, 100, 130].map((w, i) => (
          <div key={i} className="flex items-center gap-[18px]">
            <div className={`h-[18px] rounded bg-surface-tertiary animate-pulse motion-reduce:animate-none`} style={{ width: w }} />
            {i < 3 && <Divider />}
          </div>
        ))}
      </div>
    </div>
  );
}

export function TrustStrip({ health, isLoading }: TrustStripProps) {
  if (isLoading || !health) return <Skeleton />;

  const { kpis } = health;

  return (
    <div className="flex items-center gap-[14px] py-[12px] px-[18px] rounded-card bg-surface-primary border border-border-default shadow-card mb-[16px] flex-wrap">
      <Badge status={health.health} size="lg" />
      <div className="flex gap-[18px] flex-1 flex-wrap items-center">
        {/* Records today */}
        <div className="text-[13px] text-content-secondary">
          <span className="font-bold text-[18px] text-content-primary mr-[4px]">
            {fmt(kpis.recordsToday)}
          </span>
          registros hoje
          <span className="text-status-success text-[12px] font-semibold ml-[5px]">
            +{kpis.recordsTrendPct}%
          </span>
        </div>
        <Divider />

        {/* PR-Issue link rate */}
        <div className="text-[13px] text-content-secondary">
          <Link2 size={13} className="inline align-middle mr-[3px]" />
          PR&#x2194;Issue{' '}
          <span className="font-bold text-content-primary">{pct(kpis.prIssueLinkRate)}</span>
          <span className="text-status-success text-[12px] font-semibold ml-[4px]">
            +{kpis.prIssueLinkTrendPp}pp
          </span>
        </div>
        <Divider />

        {/* Deploy coverage */}
        <div className="text-[13px] text-content-secondary">
          <Rocket size={13} className="inline align-middle mr-[3px]" />
          Deploy{' '}
          <span className="font-bold text-content-primary">
            {kpis.reposWithDeploy30d.covered}/{kpis.reposWithDeploy30d.total}
          </span>
        </div>
        <Divider />

        {/* Sync lag */}
        <div className="text-[13px] text-content-secondary">
          <Clock size={13} className="inline align-middle mr-[3px]" />
          Lag{' '}
          <span className="font-bold text-content-primary">
            {fmtD(kpis.avgSyncLagSec)}
          </span>
          <span className="text-[11px] text-content-tertiary ml-[4px]">
            p95 {fmtD(kpis.p95SyncLagSec)}
          </span>
        </div>
      </div>

      <span className="text-[11px] text-content-tertiary whitespace-nowrap">
        <RefreshCw size={11} className="inline align-middle mr-[3px]" />
        Atualizado {rel(health.lastUpdatedAt)}
      </span>
    </div>
  );
}
