import type { DoraClassification, MetricTrend } from '@/types/metrics';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { classifLabel } from '@/lib/dashboard/classify';
import { InfoTooltip } from '@/components/dashboard/InfoTooltip';

interface KpiCardProps {
  label: string;
  value: string | number | null;
  unit?: string;
  trend?: MetricTrend;
  classification?: DoraClassification | null;
  sparklineData?: number[];
  /** When set, renders an info icon with tooltip — use to explain "sem dado" states. */
  infoTooltip?: string;
  /** Short badge shown next to the label when value is missing (e.g. "Em breve", "R1"). */
  pendingLabel?: string;
  /**
   * Optional second-line value rendered in 12px regular below the primary — e.g. "(404,7h)"
   * for time metrics where the primary shows days. Hidden on mobile (<640px).
   * See FDD-DSH-084.
   */
  valueSecondary?: string | null;
  /** Lead-Time-only: DORA deploy↔PR coverage ratio (0..1). Rendered as "Cobertura: 50%". */
  coveragePct?: number | null;
  /** Lead-Time-only calibration hint — rendered last (e.g. "Inclusivo: 5,0 d"). */
  extraNote?: string | null;
}

const BADGE_STYLES: Record<DoraClassification, string> = {
  elite: 'bg-dora-elite-bg text-emerald-800',
  high: 'bg-dora-high-bg text-blue-800',
  medium: 'bg-dora-medium-bg text-amber-800',
  low: 'bg-dora-low-bg text-red-800',
};

function formatValue(v: string | number | null): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'string') return v;
  if (!Number.isFinite(v)) return '—';
  if (Number.isInteger(v)) return v.toString();
  return v.toFixed(1);
}

function Sparkline({ data, classification }: { data: number[]; classification?: DoraClassification }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const w = 60;
  const h = 20;
  const stepX = w / (data.length - 1);
  const pts = data
    .map((v, i) => `${i * stepX},${h - ((v - min) / range) * h}`)
    .join(' ');
  const strokeColor =
    classification === 'elite'
      ? 'var(--color-dora-elite)'
      : classification === 'high'
        ? 'var(--color-dora-high)'
        : classification === 'medium'
          ? 'var(--color-dora-medium)'
          : classification === 'low'
            ? 'var(--color-dora-low)'
            : 'var(--color-brand-primary)';
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline
        points={pts}
        fill="none"
        stroke={strokeColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrendPill({ trend }: { trend: MetricTrend }) {
  if (trend.hasHistoricalData === false) {
    return (
      <span className="text-xs font-medium text-content-tertiary" title="Sem dados históricos">
        —
      </span>
    );
  }
  const Icon = trend.direction === 'up' ? TrendingUp : trend.direction === 'down' ? TrendingDown : Minus;
  const color = trend.isPositive
    ? 'text-status-success'
    : trend.direction === 'flat'
      ? 'text-content-tertiary'
      : 'text-status-danger';
  const sign = trend.direction === 'up' ? '+' : trend.direction === 'down' ? '-' : '';
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium tabular-nums ${color}`}>
      <Icon className="h-3 w-3" aria-hidden="true" />
      {sign}
      {trend.percentage}%
    </span>
  );
}

export function KpiCard({
  label,
  value,
  unit,
  trend,
  classification,
  sparklineData,
  infoTooltip,
  pendingLabel,
  valueSecondary,
  coveragePct,
  extraNote,
}: KpiCardProps) {
  const isEmpty = value === null || value === undefined || value === '—';
  const primaryText = formatValue(value);
  const ariaLabel = isEmpty ? label : `${label}: ${primaryText}${unit ? ` ${unit}` : ''}`;
  const coveragePctRounded =
    coveragePct !== null && coveragePct !== undefined && Number.isFinite(coveragePct)
      ? Math.round(coveragePct * 100)
      : null;
  // "Compact" layout = time metrics with any of secondary/coverage/extraNote:
  // trend pill + DORA badge on the same line to save vertical space.
  const hasCompactFooter =
    Boolean(valueSecondary) || coveragePctRounded !== null || Boolean(extraNote);
  const primarySizeCls = hasCompactFooter
    ? 'text-[20px] sm:text-[24px]'
    : 'text-[24px]';
  return (
    <div
      className={`flex flex-col gap-1.5 rounded-[10px] border p-3.5 ${
        isEmpty
          ? 'border-dashed border-border-default bg-surface-secondary'
          : 'border-border-subtle bg-surface-secondary'
      }`}
      role="group"
      aria-label={ariaLabel}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-medium uppercase tracking-wide text-content-secondary">
            {label}
          </span>
          {infoTooltip && <InfoTooltip content={infoTooltip} ariaLabel={`Sobre ${label}`} />}
        </div>
        {pendingLabel && isEmpty && (
          <span className="inline-flex items-center rounded-badge bg-surface-tertiary px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-content-tertiary">
            {pendingLabel}
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-1">
        <span
          className={`${primarySizeCls} font-bold leading-tight tabular-nums ${
            isEmpty ? 'text-content-tertiary' : 'text-content-primary'
          }`}
        >
          {primaryText}
        </span>
        {unit && !isEmpty && (
          <span className="text-xs font-medium text-content-secondary">{unit}</span>
        )}
      </div>
      {valueSecondary && !isEmpty && (
        <div className="hidden sm:block">
          <span className="text-xs font-normal text-content-secondary tabular-nums">
            {valueSecondary}
          </span>
        </div>
      )}
      {/* Compact layout for Lead Time-style cards (trend + DORA badge inline) */}
      {hasCompactFooter ? (
        <>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {trend && !isEmpty ? <TrendPill trend={trend} /> : <span />}
              {classification && !isEmpty && (
                <span
                  className={`inline-flex items-center rounded-badge px-2 py-0.5 text-[11px] font-semibold ${BADGE_STYLES[classification as DoraClassification]}`}
                >
                  {classifLabel(classification as DoraClassification)}
                </span>
              )}
            </div>
            {sparklineData && !isEmpty && (
              <Sparkline data={sparklineData} classification={classification ?? undefined} />
            )}
          </div>
          {coveragePctRounded !== null && !isEmpty && (
            <div className="text-[11px] font-normal text-content-secondary tabular-nums">
              Cobertura: {coveragePctRounded}%
            </div>
          )}
          {extraNote && !isEmpty && (
            <div className="text-[11px] font-normal text-content-secondary tabular-nums">
              {extraNote}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            {trend && !isEmpty ? <TrendPill trend={trend} /> : <span />}
            {sparklineData && !isEmpty && (
              <Sparkline data={sparklineData} classification={classification ?? undefined} />
            )}
          </div>
          {classification && !isEmpty && (
            <div className="mt-0.5">
              <span
                className={`inline-flex items-center rounded-badge px-2 py-0.5 text-[11px] font-semibold ${BADGE_STYLES[classification as DoraClassification]}`}
              >
                {classifLabel(classification as DoraClassification)}
              </span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function KpiCardSkeleton() {
  return (
    <div className="flex animate-pulse flex-col gap-2 rounded-[10px] border border-border-subtle bg-surface-secondary p-3.5">
      <div className="h-3 w-20 rounded bg-surface-tertiary" />
      <div className="h-6 w-16 rounded bg-surface-tertiary" />
      <div className="h-3 w-full rounded bg-surface-tertiary" />
      <div className="h-4 w-12 rounded-badge bg-surface-tertiary" />
    </div>
  );
}
