import type { ReactNode } from 'react';
import { useTenantCapabilities } from '@/hooks/useTenantCapabilities';
import type { CapabilityKey } from '@/types/tenant';

interface CapabilityGuardProps {
  /** Required capability — children only render if this flag is true. */
  requires: CapabilityKey;
  /**
   * Optional Jira project key (e.g. 'FID'). When provided, the capability is
   * evaluated against the squad-specific response instead of the tenant-wide
   * one. Useful on pages where the active squad changes the answer (Webmotors:
   * FID has sprints, BG does not).
   */
  squadKey?: string | null;
  children: ReactNode;
  /**
   * What to render while capabilities are still loading. Default: children.
   * Rationale: never hide features speculatively. Only hide AFTER confirmed
   * absent; pre-confirmation we show content to avoid flicker.
   */
  loadingFallback?: ReactNode;
  /** Rendered when the capability is confirmed absent. Default: null. */
  fallback?: ReactNode;
}

/**
 * Conditionally renders `children` based on tenant (or squad) capability flags.
 *
 * Behaviour:
 *   - loading  -> renders `loadingFallback` (defaults to children, avoiding flicker)
 *   - success + capability present -> renders children
 *   - success + capability absent  -> renders `fallback` (default null)
 *   - error    -> renders children (fail-open — features remain visible)
 */
export function CapabilityGuard({
  requires,
  squadKey,
  children,
  loadingFallback,
  fallback = null,
}: CapabilityGuardProps) {
  const { data, isLoading, isError } = useTenantCapabilities(squadKey);

  if (isLoading) {
    return <>{loadingFallback ?? children}</>;
  }

  if (isError || !data) {
    return <>{children}</>;
  }

  const has = requires === 'sprints' ? data.hasSprints : data.hasKanban;
  return <>{has ? children : fallback}</>;
}
