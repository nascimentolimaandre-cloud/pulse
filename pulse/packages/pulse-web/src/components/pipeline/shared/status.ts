import {
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Loader2,
  CircleDot,
  RefreshCw,
  Gauge,
  Unplug,
  Clock,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { StatusKey, Severity } from '@/types/pipeline';

export interface StatusConfig {
  label: string;
  icon: LucideIcon;
  bg: string;
  text: string;
  color: string;
  border: string;
  spin: boolean;
}

/**
 * Maps each status key to Tailwind classes and a Lucide icon.
 *
 * Backgrounds use the extended `status.*Bg` tokens from tailwind.config.ts.
 * Text uses `status.*Text`. Color (for icons/bars) uses `status.*` direct.
 */
export const STATUS_MAP: Record<StatusKey, StatusConfig> = {
  healthy: {
    label: 'Saudavel',
    icon: CheckCircle2,
    bg: 'bg-status-successBg',
    text: 'text-status-successText',
    color: 'text-status-success',
    border: 'border-status-success/20',
    spin: false,
  },
  idle: {
    label: 'Idle',
    icon: CircleDot,
    bg: 'bg-status-idleBg',
    text: 'text-status-idleText',
    color: 'text-status-idle',
    border: 'border-status-idle/20',
    spin: false,
  },
  running: {
    label: 'Sincronizando',
    icon: Loader2,
    bg: 'bg-status-infoBg',
    text: 'text-status-infoText',
    color: 'text-status-info',
    border: 'border-status-info/20',
    spin: true,
  },
  backfilling: {
    label: 'Backfill',
    icon: RefreshCw,
    bg: 'bg-status-infoBg',
    text: 'text-status-infoText',
    color: 'text-status-info',
    border: 'border-status-info/20',
    spin: true,
  },
  degraded: {
    label: 'Degradado',
    icon: AlertTriangle,
    bg: 'bg-status-warningBg',
    text: 'text-status-warningText',
    color: 'text-status-warning',
    border: 'border-status-warning/20',
    spin: false,
  },
  error: {
    label: 'Erro',
    icon: AlertCircle,
    bg: 'bg-status-dangerBg',
    text: 'text-status-dangerText',
    color: 'text-status-danger',
    border: 'border-status-danger/20',
    spin: false,
  },
  done: {
    label: 'Concluido',
    icon: CheckCircle2,
    bg: 'bg-status-successBg',
    text: 'text-status-successText',
    color: 'text-status-success',
    border: 'border-status-success/20',
    spin: false,
  },
  slow: {
    label: 'Rate-limited',
    icon: Gauge,
    bg: 'bg-status-warningBg',
    text: 'text-status-warningText',
    color: 'text-status-warning',
    border: 'border-status-warning/20',
    spin: false,
  },
  disabled: {
    label: 'Desabilitado',
    icon: Unplug,
    bg: 'bg-status-idleBg',
    text: 'text-status-idleText',
    color: 'text-status-idle',
    border: 'border-status-idle/20',
    spin: false,
  },
  pending: {
    label: 'Pendente',
    icon: Clock,
    bg: 'bg-status-warningBg',
    text: 'text-status-warningText',
    color: 'text-status-warning',
    border: 'border-status-warning/20',
    spin: false,
  },
};

export function getStatusConfig(status: string): StatusConfig {
  return STATUS_MAP[status as StatusKey] ?? STATUS_MAP.idle;
}

/* Severity color mapping for timeline events */
export interface SeverityConfig {
  dot: string;
  bg: string;
  text: string;
}

export const SEVERITY_MAP: Record<Severity, SeverityConfig> = {
  success: { dot: 'bg-status-success', bg: 'bg-status-successBg', text: 'text-status-success' },
  info: { dot: 'bg-status-info', bg: 'bg-status-infoBg', text: 'text-status-info' },
  warning: { dot: 'bg-status-warning', bg: 'bg-status-warningBg', text: 'text-status-warning' },
  error: { dot: 'bg-status-danger', bg: 'bg-status-dangerBg', text: 'text-status-danger' },
};

export function getSeverityConfig(severity: string): SeverityConfig {
  return SEVERITY_MAP[severity as Severity] ?? SEVERITY_MAP.info;
}
