import { AlertTriangle, AlertCircle, ExternalLink } from 'lucide-react';
import { Link } from '@tanstack/react-router';

type Severity = 'degraded' | 'error';

interface FreshnessBannerProps {
  severity: Severity;
  message: string;
  /** Optional link to pipeline monitor */
  linkTo?: string;
  linkLabel?: string;
  onRetry?: () => void;
}

const VARIANTS: Record<Severity, { bg: string; border: string; text: string; icon: typeof AlertTriangle }> = {
  degraded: {
    bg: 'bg-status-warningBg',
    border: 'border-status-warning',
    text: 'text-status-warningText',
    icon: AlertTriangle,
  },
  error: {
    bg: 'bg-status-dangerBg',
    border: 'border-status-danger',
    text: 'text-status-dangerText',
    icon: AlertCircle,
  },
};

export function FreshnessBanner({
  severity,
  message,
  linkTo = '/pipeline-monitor',
  linkLabel = 'Ver pipeline',
  onRetry,
}: FreshnessBannerProps) {
  const v = VARIANTS[severity];
  const Icon = v.icon;
  return (
    <div
      role="status"
      aria-live="polite"
      className={`mb-4 flex flex-wrap items-center justify-between gap-3 rounded-card border ${v.border} ${v.bg} px-3.5 py-2.5`}
    >
      <div className={`flex items-center gap-2 text-sm ${v.text}`}>
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{message}</span>
      </div>
      <div className="flex items-center gap-3">
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="text-xs font-medium text-brand-primary hover:text-brand-primary-hover focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1"
          >
            Tentar novamente
          </button>
        )}
        <Link
          to={linkTo}
          className="inline-flex items-center gap-1 text-xs font-medium text-brand-primary hover:text-brand-primary-hover"
        >
          {linkLabel}
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}
