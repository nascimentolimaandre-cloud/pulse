import { TrendingUp, TrendingDown, Minus, Info, Check, X } from 'lucide-react';
import type { MetricTrend, MetricTarget, DoraClassification, BenchmarkThresholds } from '@/types/metrics';

interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  trend: MetricTrend;
  sparklineData?: number[];
  target?: MetricTarget;
  classification?: DoraClassification;
  benchmarks?: BenchmarkThresholds;
  onClick?: () => void;
  loading?: boolean;
  tooltipContent?: string;
}

interface MetricCardSkeletonProps {
  className?: string;
}

/* ── Color system ── */

const CLASSIFICATION_STYLES: Record<DoraClassification, {
  border: string;
  badge: string;
  badgeText: string;
  valueColor: string;
}> = {
  elite: {
    border: 'border-l-emerald-500',
    badge: 'bg-emerald-50 text-emerald-700',
    badgeText: 'Elite',
    valueColor: 'text-emerald-700',
  },
  high: {
    border: 'border-l-emerald-400',
    badge: 'bg-emerald-50 text-emerald-600',
    badgeText: 'High',
    valueColor: 'text-emerald-600',
  },
  medium: {
    border: 'border-l-amber-400',
    badge: 'bg-amber-50 text-amber-700',
    badgeText: 'Medium',
    valueColor: 'text-amber-600',
  },
  low: {
    border: 'border-l-red-400',
    badge: 'bg-red-50 text-red-700',
    badgeText: 'Low',
    valueColor: 'text-red-600',
  },
};

const BENCH_LEVEL_COLORS: Record<DoraClassification, string> = {
  elite: 'text-emerald-600',
  high: 'text-emerald-500',
  medium: 'text-amber-600',
  low: 'text-red-500',
};

/* ── Sub-components ── */

function TrendBadge({ trend }: { trend: MetricTrend }) {
  // No historical data → show info indicator
  if (trend.hasHistoricalData === false) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-badge bg-surface-tertiary px-2 py-0.5 text-xs font-medium text-content-tertiary"
        title="Ainda nao temos dados historicos para comparar com o periodo atual"
      >
        <Info className="h-3 w-3" />
        Sem dados anteriores
      </span>
    );
  }

  const Icon =
    trend.direction === 'up'
      ? TrendingUp
      : trend.direction === 'down'
        ? TrendingDown
        : Minus;

  const colorClass = trend.isPositive
    ? 'text-status-success bg-emerald-50'
    : trend.direction === 'flat'
      ? 'text-content-tertiary bg-surface-tertiary'
      : 'text-status-danger bg-red-50';

  const sign = trend.direction === 'up' ? '+' : trend.direction === 'down' ? '-' : '';

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-badge px-2 py-0.5 text-xs font-medium ${colorClass}`}
    >
      <Icon className="h-3 w-3" />
      {sign}{trend.percentage}%
    </span>
  );
}

function SparklinePlaceholder({ data }: { data: number[] }) {
  if (data.length === 0) return null;

  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const height = 32;
  const width = 120;
  const stepX = width / (data.length - 1 || 1);

  const points = data
    .map((val, i) => {
      const x = i * stepX;
      const y = height - ((val - min) / range) * height;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="text-brand-primary"
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TargetIndicator({ target }: { target: MetricTarget }) {
  return (
    <div className="flex items-center justify-between text-xs text-content-secondary">
      <span>Target: {target.value}</span>
      {target.met ? (
        <Check className="h-4 w-4 text-status-success" />
      ) : (
        <X className="h-4 w-4 text-status-danger" />
      )}
    </div>
  );
}

function ClassificationBadge({ classification }: { classification: DoraClassification }) {
  const styles = CLASSIFICATION_STYLES[classification];
  return (
    <span className={`inline-flex items-center rounded-badge px-2 py-0.5 text-xs font-semibold ${styles.badge}`}>
      {styles.badgeText}
    </span>
  );
}

function BenchmarkBar({ benchmarks, classification }: { benchmarks: BenchmarkThresholds; classification: DoraClassification }) {
  const levels: DoraClassification[] = ['elite', 'high', 'medium', 'low'];
  return (
    <div className="mt-2 border-t border-border-subtle pt-2">
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] leading-4">
        {levels.map((level) => (
          <span
            key={level}
            className={`${level === classification ? 'font-bold underline' : 'font-normal opacity-50'} ${BENCH_LEVEL_COLORS[level]}`}
          >
            {level.charAt(0).toUpperCase() + level.slice(1)}: {benchmarks[level]}
          </span>
        ))}
      </div>
    </div>
  );
}

function formatValue(value: string | number): string {
  if (typeof value === 'string') return value;
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(2);
}

/* ── Main component ── */

export function MetricCard({
  label,
  value,
  unit,
  trend,
  sparklineData,
  target,
  classification,
  benchmarks,
  onClick,
  loading,
  tooltipContent,
}: MetricCardProps) {
  if (loading) {
    return <MetricCardSkeleton />;
  }

  const styles = classification ? CLASSIFICATION_STYLES[classification] : null;
  const borderClass = styles ? `border-l-4 ${styles.border}` : '';
  const valueColorClass = styles ? styles.valueColor : 'text-content-primary';

  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onClick();
        }
      }}
      className={`
        rounded-card border border-border-default bg-surface-primary p-card-padding
        shadow-card transition-shadow
        ${borderClass}
        ${onClick ? 'cursor-pointer hover:shadow-elevated' : ''}
      `}
    >
      {/* Header: label + classification badge + info icon */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-content-secondary">{label}</h3>
          {classification && <ClassificationBadge classification={classification} />}
        </div>
        {tooltipContent && (
          <button
            className="text-content-tertiary transition-colors hover:text-content-secondary"
            title={tooltipContent}
            aria-label={`Info: ${tooltipContent}`}
          >
            <Info className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Value + Trend */}
      <div className="mb-3 flex items-end justify-between">
        <div className="flex items-baseline gap-1">
          <span className={`text-3xl font-bold leading-tight ${valueColorClass}`}>
            {formatValue(value)}
          </span>
          {unit && (
            <span className="text-sm font-medium text-content-tertiary">{unit}</span>
          )}
        </div>
        <TrendBadge trend={trend} />
      </div>

      {/* Sparkline */}
      {sparklineData && sparklineData.length > 0 && (
        <div className="mb-3">
          <SparklinePlaceholder data={sparklineData} />
        </div>
      )}

      {/* Target */}
      {target && <TargetIndicator target={target} />}

      {/* Benchmark thresholds */}
      {benchmarks && classification && (
        <BenchmarkBar benchmarks={benchmarks} classification={classification} />
      )}
    </div>
  );
}

export function MetricCardSkeleton({ className = '' }: MetricCardSkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card ${className}`}
    >
      {/* Label skeleton */}
      <div className="mb-3 flex items-center gap-2">
        <div className="h-4 w-32 rounded bg-surface-tertiary" />
        <div className="h-4 w-12 rounded-badge bg-surface-tertiary" />
      </div>

      {/* Value + trend skeleton */}
      <div className="mb-3 flex items-end justify-between">
        <div className="h-9 w-24 rounded bg-surface-tertiary" />
        <div className="h-5 w-20 rounded-badge bg-surface-tertiary" />
      </div>

      {/* Benchmark skeleton */}
      <div className="mt-2 border-t border-border-subtle pt-2">
        <div className="h-3 w-full rounded bg-surface-tertiary" />
      </div>
    </div>
  );
}
