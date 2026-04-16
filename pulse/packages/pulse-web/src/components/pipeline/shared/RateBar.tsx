import { Gauge } from 'lucide-react';

interface RateBarProps {
  value: number;
  compact?: boolean;
}

function rateColor(pct: number): string {
  if (pct >= 90) return 'bg-status-danger';
  if (pct >= 70) return 'bg-status-warning';
  return 'bg-status-success';
}

function rateTextColor(pct: number): string {
  if (pct >= 70) return pct >= 90 ? 'text-status-danger' : 'text-status-warning';
  return 'text-content-tertiary';
}

function rateIconColor(pct: number): string {
  if (pct >= 90) return 'text-status-danger';
  if (pct >= 70) return 'text-status-warning';
  return 'text-status-success';
}

export function RateBar({ value, compact = false }: RateBarProps) {
  const p = Math.round(value * 100);

  return (
    <div className={`flex items-center ${compact ? 'gap-[5px]' : 'gap-[8px]'}`}>
      {!compact && <Gauge size={14} className={rateIconColor(p)} />}
      <div
        className={`${compact ? 'w-[40px]' : 'flex-1'} ${compact ? 'h-[4px]' : 'h-[6px]'} rounded-[3px] bg-surface-tertiary overflow-hidden`}
      >
        <div
          className={`h-full rounded-[3px] ${rateColor(p)} transition-[width] duration-500`}
          style={{ width: `${p}%` }}
        />
      </div>
      <span
        className={`font-mono ${compact ? 'text-[10px] min-w-[24px]' : 'text-[12px] min-w-[30px]'} font-medium ${rateTextColor(p)}`}
      >
        {p}%
      </span>
    </div>
  );
}
