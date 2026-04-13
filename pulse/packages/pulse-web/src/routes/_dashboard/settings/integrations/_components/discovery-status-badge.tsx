import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import type { JiraDiscoveryStatusResponse } from '@pulse/shared';

interface DiscoveryStatusBadgeProps {
  status: JiraDiscoveryStatusResponse | undefined;
  isLoading: boolean;
}

export function DiscoveryStatusBadge({ status, isLoading }: DiscoveryStatusBadgeProps) {
  if (isLoading || !status) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-badge bg-surface-tertiary px-2.5 py-1 text-xs font-medium text-content-secondary">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Carregando...
      </span>
    );
  }

  if (status.inFlight) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-badge bg-blue-50 px-2.5 py-1 text-xs font-medium text-status-info">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Descobrindo...
      </span>
    );
  }

  const lastStatus = status.lastRun?.status;

  if (lastStatus === 'failed') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-badge bg-red-50 px-2.5 py-1 text-xs font-medium text-status-danger">
        <XCircle className="h-3.5 w-3.5" />
        Falha
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-badge bg-emerald-50 px-2.5 py-1 text-xs font-medium text-status-success">
      <CheckCircle2 className="h-3.5 w-3.5" />
      Idle
    </span>
  );
}
