import { useQuery } from '@tanstack/react-query';
import { dataClient } from '@/lib/api/client';
import type { TenantCapabilities, CapabilityKey } from '@/types/tenant';

/**
 * Fetches tenant capability flags. Cached for 5min on the client (matches
 * backend Redis TTL) so the hook is safe to call from many components.
 *
 * When `squadKey` is provided, the response is scoped to that single squad —
 * useful for routes that need to know whether THIS squad has sprints (Webmotors:
 * FID / PTURB do, the other 25 don't). Cache is keyed per-squad so selecting a
 * different squad does not invalidate the tenant-wide value.
 *
 * Invalid squad keys (non-uppercase, contains separators) are handled
 * server-side by falling back to tenant-wide — the UI still receives a valid
 * payload.
 */
export function useTenantCapabilities(squadKey?: string | null) {
  const normalized =
    squadKey && squadKey !== 'default' ? squadKey.toUpperCase() : null;

  return useQuery<TenantCapabilities>({
    queryKey: ['tenant-capabilities', normalized],
    queryFn: async () => {
      const { data } = await dataClient.get<TenantCapabilities>(
        '/tenant/capabilities',
        normalized ? { params: { squad_key: normalized } } : undefined,
      );
      return data;
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: 1,
  });
}

/**
 * Convenience boolean: returns true when the capability is confirmed absent
 * (query settled and flag is false). While loading or on error, returns false
 * so UI stays visible — we never hide features speculatively.
 */
export function useLacksCapability(
  key: CapabilityKey,
  squadKey?: string | null,
): boolean {
  const { data, isSuccess } = useTenantCapabilities(squadKey);
  if (!isSuccess || !data) return false;
  return key === 'sprints' ? !data.hasSprints : !data.hasKanban;
}
