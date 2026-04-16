import { getStatusConfig } from './status';
import type { StatusKey } from '@/types/pipeline';

interface BadgeProps {
  status: string;
  size?: 'xs' | 'sm' | 'lg';
  showLabel?: boolean;
}

const SIZE_CLASSES = {
  xs: 'px-[7px] py-[2px] text-[11px] gap-[3px]',
  sm: 'px-[10px] py-[4px] text-[12px] gap-[5px]',
  lg: 'px-[16px] py-[10px] text-[14px] gap-[5px]',
} as const;

const ICON_SIZE = { xs: 11, sm: 13, lg: 17 } as const;

export function Badge({ status, size = 'sm', showLabel = true }: BadgeProps) {
  const cfg = getStatusConfig(status as StatusKey);
  const Icon = cfg.icon;
  const sz = SIZE_CLASSES[size];
  const iconPx = ICON_SIZE[size];

  return (
    <span
      className={`inline-flex items-center ${sz} rounded-badge ${cfg.bg} ${cfg.text} font-medium whitespace-nowrap leading-[1.3]`}
    >
      <Icon
        size={iconPx}
        className={cfg.spin ? 'animate-spin motion-reduce:animate-none' : ''}
      />
      {showLabel && cfg.label}
    </span>
  );
}
