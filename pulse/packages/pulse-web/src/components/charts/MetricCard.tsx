import { TrendingUp, TrendingDown, Minus, Info, Check, X } from 'lucide-react';
import type { MetricTrend, MetricTarget } from '@/types/metrics';

interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  trend: MetricTrend;
  sparklineData?: number[];
  target?: MetricTarget;
  onClick?: () => void;
  loading?: boolean;
  tooltipContent?: string;
}

interface MetricCardSkeletonProps {
  className?: string;
}

function TrendBadge({ trend }: { trend: MetricTrend }) {
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

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-badge px-2 py-0.5 text-xs font-medium ${colorClass}`}
    >
      <Icon className="h-3 w-3" />
      {trend.percentage > 0 ? `${trend.percentage}%` : `${Math.abs(trend.percentage)}%`}
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

export function MetricCard({
  label,
  value,
  unit,
  trend,
  sparklineData,
  target,
  onClick,
  loading,
  tooltipContent,
}: MetricCardProps) {
  if (loading) {
    return <MetricCardSkeleton />;
  }

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
        ${onClick ? 'cursor-pointer hover:shadow-elevated' : ''}
      `}
    >
      {/* Header: label + info icon */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-content-secondary">{label}</h3>
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
          <span className="text-3xl font-bold leading-tight text-content-primary">
            {value}
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
    </div>
  );
}

export function MetricCardSkeleton({ className = '' }: MetricCardSkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card ${className}`}
    >
      {/* Label skeleton */}
      <div className="mb-3 h-4 w-32 rounded bg-surface-tertiary" />

      {/* Value + trend skeleton */}
      <div className="mb-3 flex items-end justify-between">
        <div className="h-9 w-24 rounded bg-surface-tertiary" />
        <div className="h-5 w-14 rounded-badge bg-surface-tertiary" />
      </div>

      {/* Sparkline skeleton */}
      <div className="mb-3 h-8 w-full rounded bg-surface-tertiary" />

      {/* Target skeleton */}
      <div className="h-4 w-28 rounded bg-surface-tertiary" />
    </div>
  );
}
