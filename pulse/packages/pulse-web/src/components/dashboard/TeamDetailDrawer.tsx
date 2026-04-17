import { useCallback, useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  CartesianGrid,
} from 'recharts';
import type { DoraClassification } from '@/types/metrics';
import type { DashboardMetric } from '@/stores/filterStore';
import type { TeamDetailData } from '@/lib/dashboard/mockDerive';
import { METRIC_META, classifLabel } from '@/lib/dashboard/classify';

interface TeamDetailDrawerProps {
  data: TeamDetailData | null;
  activeMetric: DashboardMetric;
  open: boolean;
  onClose: () => void;
}

const VALUE_COLOR: Record<DoraClassification, string> = {
  elite: 'text-emerald-700',
  high: 'text-blue-700',
  medium: 'text-amber-700',
  low: 'text-red-700',
};

const METRICS_ORDER: DashboardMetric[] = [
  'deployFreq',
  'leadTime',
  'cfr',
  'cycleTime',
  'wip',
  'throughput',
];

function formatValue(v: number): string {
  if (Number.isInteger(v)) return v.toString();
  return v.toFixed(1);
}

export function TeamDetailDrawer({ data, activeMetric, open, onClose }: TeamDetailDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'Tab' && drawerRef.current) {
        const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
          'button, [tabindex]:not([tabindex="-1"]), a[href], input, select, textarea',
        );
        if (focusable.length === 0) return;
        const first = focusable[0]!;
        const last = focusable[focusable.length - 1]!;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [open, onClose],
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [handleKey]);

  useEffect(() => {
    if (open) {
      const t = setTimeout(() => {
        const btn = drawerRef.current?.querySelector<HTMLElement>('button');
        btn?.focus();
      }, 50);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [open]);

  if (!open || !data) return null;

  const meta = METRIC_META[activeMetric]!;
  const evoPoints = data.evolution[activeMetric] ?? [];
  const evoData = evoPoints.map((value, i) => ({
    week: `S-${evoPoints.length - 1 - i}`,
    value,
  }));
  const distData = [
    { label: 'P50', value: data.cycleTimeP50 },
    { label: 'P85', value: data.cycleTimeP85 },
  ];

  return (
    <aside
      ref={drawerRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby="team-drawer-title"
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col border-l border-border-default bg-surface-primary shadow-elevated"
      style={{
        transform: 'translateX(0)',
        transition: 'transform 200ms ease-out',
      }}
    >
      <header className="flex items-start justify-between gap-3 border-b border-border-default px-5 py-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-widest text-content-tertiary">
            Tribo {data.tribe}
          </p>
          <h2 id="team-drawer-title" className="mt-0.5 text-lg font-semibold text-content-primary">
            {data.name}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fechar detalhe"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-content-secondary hover:bg-surface-tertiary hover:text-content-primary focus:outline-none focus:ring-2 focus:ring-brand-primary"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-5">
        {/* Metric tiles grid */}
        <div className="mb-5 grid grid-cols-2 gap-2.5">
          {METRICS_ORDER.map((m) => {
            const item = data.metrics[m];
            const mm = METRIC_META[m];
            if (!item || !mm) return null;
            return (
              <div
                key={m}
                className="rounded-[8px] border border-border-subtle bg-surface-secondary p-2.5"
              >
                <div className="text-[10px] font-medium uppercase tracking-wide text-content-secondary">
                  {mm.label}
                </div>
                <div className={`mt-1 font-mono text-lg font-semibold tabular-nums ${VALUE_COLOR[item.classification]}`}>
                  {formatValue(item.value)}{' '}
                  <span className="text-[11px] text-content-tertiary">{item.unit}</span>
                </div>
                <div className="mt-1 inline-flex rounded-badge bg-surface-tertiary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary">
                  {classifLabel(item.classification)}
                </div>
              </div>
            );
          })}
        </div>

        {/* Evolution chart */}
        <div className="mb-5">
          <h4 className="mb-2 text-[13px] font-semibold text-content-primary">
            Evolução (12 sem) · {meta.label}
          </h4>
          <div className="h-[160px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={evoData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="var(--color-border-subtle)" strokeDasharray="2 2" vertical={false} />
                <XAxis
                  dataKey="week"
                  tick={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fill: 'var(--color-text-tertiary)' }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fill: 'var(--color-text-tertiary)' }}
                  axisLine={false}
                  tickLine={false}
                  width={32}
                />
                <Tooltip
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: '1px solid var(--color-border-default)',
                  }}
                  labelStyle={{ color: 'var(--color-text-secondary)' }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="var(--color-brand-primary)"
                  strokeWidth={2}
                  dot={{ r: 2, fill: 'var(--color-brand-primary)' }}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Cycle time distribution */}
        <div>
          <h4 className="mb-2 text-[13px] font-semibold text-content-primary">
            Distribuição Cycle Time (P50 / P85)
          </h4>
          <div className="h-[140px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={distData}
                layout="vertical"
                margin={{ top: 4, right: 20, bottom: 4, left: 16 }}
              >
                <CartesianGrid stroke="var(--color-border-subtle)" strokeDasharray="2 2" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', fill: 'var(--color-text-tertiary)' }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  dataKey="label"
                  type="category"
                  tick={{ fontSize: 11, fill: 'var(--color-text-secondary)' }}
                  axisLine={false}
                  tickLine={false}
                  width={40}
                />
                <Tooltip
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: '1px solid var(--color-border-default)',
                  }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                  {distData.map((_, i) => (
                    <Bar
                      key={i}
                      dataKey="value"
                      fill={i === 0 ? 'var(--color-brand-primary)' : 'var(--color-warning)'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1 text-[11px] text-content-tertiary">
            Unidade: dias · calculado sobre issues fechadas no período.
          </p>
        </div>
      </div>
    </aside>
  );
}
