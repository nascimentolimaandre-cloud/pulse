import { BarChart3 } from 'lucide-react';
import { fmt } from './shared/format';
import { usePipelineCoverage } from '@/hooks/usePipeline';

interface DonutProps {
  value: number;
  color: string;
  label: string;
  detail: string;
}

function Donut({ value, color, label, detail }: DonutProps) {
  const r = 28;
  const cx = 36;
  const cy = 36;
  const sw = 6;
  const circ = 2 * Math.PI * r;

  return (
    <div className="flex items-center gap-[12px] py-[6px]">
      <svg width={72} height={72} viewBox="0 0 72 72" aria-hidden="true">
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="currentColor"
          strokeWidth={sw}
          className="text-surface-tertiary"
        />
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={sw}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - value)}
          transform={`rotate(-90 ${cx} ${cy})`}
        />
        <text
          x={cx}
          y={cy}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize="14"
          fontWeight="700"
          fill="currentColor"
          className="text-content-primary"
        >
          {Math.round(value * 100)}%
        </text>
      </svg>
      <div>
        <div className="text-[13px] font-semibold">{label}</div>
        <div className="text-[11px] text-content-secondary">{detail}</div>
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card p-[16px]">
      <div className="h-[16px] w-[100px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none mb-[12px]" />
      <div className="h-[72px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none mb-[8px]" />
      <div className="h-[72px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none" />
    </div>
  );
}

export function CoveragePanel() {
  const { data: coverage, isLoading } = usePipelineCoverage();

  if (isLoading || !coverage) return <Skeleton />;

  const deployPct =
    coverage.reposWithDeploy.total > 0
      ? coverage.reposWithDeploy.covered / coverage.reposWithDeploy.total
      : 0;

  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card p-[16px]">
      <div className="text-[14px] font-semibold mb-[8px] flex items-center gap-[6px]">
        <BarChart3 size={15} className="text-brand-primary" />
        Cobertura
      </div>

      <Donut
        value={deployPct}
        color="#10B981"
        label="Repos com deploy"
        detail={`${coverage.reposWithDeploy.covered}/${coverage.reposWithDeploy.total} (30d)`}
      />

      <Donut
        value={coverage.prIssueLinkRate}
        color="#6366F1"
        label="PR &#x2194; Issue"
        detail={`${Math.round(coverage.prIssueLinkRate * 100)}% taxa de vinculo`}
      />

      {/* Orphan prefixes */}
      {coverage.orphanPrefixes.length > 0 && (
        <div className="border-t border-border-default mt-[6px] pt-[8px]">
          <div className="text-[11px] font-semibold text-content-secondary mb-[5px]">
            Prefixos orfaos
          </div>
          {coverage.orphanPrefixes.map((o) => (
            <div
              key={o.prefix}
              className="flex justify-between py-[2px] text-[12px]"
            >
              <span className="font-mono font-semibold text-status-warning">
                {o.prefix}-*
              </span>
              <span className="text-content-secondary">{fmt(o.prMentions)} PRs</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
